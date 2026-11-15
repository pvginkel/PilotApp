"""When a Block became a person's to answer (DB §2.2, Block's `handed_at`;
decision 79): the Blocks that are Pilot's before a move and after it, and
the `handed_at` their comparison writes."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Document, Item, User
from app.models.reference import SessionState
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer
from app.services.handing import hand_over, sides
from tests.support.working_on import Camp

AT = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
LATER = AT + timedelta(hours=2)

PITCH = """# Where do we pitch?

```question id=Q1
```

```decision id=D1
options:
  - Lake
  - Hill
```
"""

CUT_OVER = """# The cut-over

```action id=A1
answer: Pilot does it
by: agent
at: 2026-11-02T09:00:00Z
```

```action id=A2
```
"""
"""An action the pass claimed beside one that waits on the person."""

RULED = """# Where do we pitch?

```question id=Q1
answer: By the lake
by: agent
at: 2026-11-02T09:05:00Z
```

```decision id=D1
options:
  - Lake
  - Hill
```
"""
"""`PITCH` with its question answered by Pilot."""


@pytest.fixture
def camp(container: ServiceContainer, session: DbSession, person: User) -> Camp:
    return Camp(container, session)


def _ids(camp: Camp, document: Item, *local_ids: str) -> frozenset[int]:
    return frozenset(camp.block(document, local_id).id for local_id in local_ids)


def _handed(camp: Camp, document: Item, local_id: str) -> datetime | None:
    camp.session.expire_all()
    return camp.block(document, local_id).handed_at


def _document(camp: Camp, item: Item) -> Document:
    return camp.session.get_one(Document, item.id)


def _under_pass(camp: Camp, text: str = PITCH) -> tuple[Item, models.Session]:
    """`text` registered by a worker whose turn ended, its pass running."""
    writer = camp.worker()
    document = camp.registered(writer, text)
    camp.ended(writer)
    return document, camp.job_after(writer)


class TestSides:
    def test_the_blocks_of_a_document_under_its_pass_are_pilots(
        self, camp: Camp
    ) -> None:
        pitch, _ = _under_pass(camp)

        found = sides(camp.session, camp.project.id)

        assert found.project_id == camp.project.id
        assert found.pilots == _ids(camp, pitch, "Q1", "D1")

    def test_a_block_a_run_holds_is_pilots_and_the_one_beside_it_is_not(
        self, camp: Camp
    ) -> None:
        cut_over, job = _under_pass(camp, CUT_OVER)
        camp.ended(job)
        camp.claim(cut_over, "A1", camp.worker(conversation="conversation-2"))

        assert sides(camp.session, camp.project.id).pilots == _ids(camp, cut_over, "A1")

    def test_an_answered_block_is_not_among_them(self, camp: Camp) -> None:
        pitch, _ = _under_pass(camp, RULED)

        assert sides(camp.session, camp.project.id).pilots == _ids(camp, pitch, "D1")

    def test_a_block_of_a_document_that_is_the_persons_is_not_among_them(
        self, camp: Camp
    ) -> None:
        _, job = _under_pass(camp)
        camp.ended(job)

        assert sides(camp.session, camp.project.id).pilots == frozenset()

    def test_a_block_of_a_done_item_is_not_among_them(self, camp: Camp) -> None:
        pitch, _ = _under_pass(camp)
        pitch.done_at = AT
        pitch.done_cause_code = "cancelled"
        camp.session.flush()

        assert sides(camp.session, camp.project.id).pilots == frozenset()

    def test_another_projects_blocks_are_not_among_them(
        self, container: ServiceContainer, session: DbSession, camp: Camp
    ) -> None:
        _under_pass(camp)
        other = container.test_data_service().project(
            InventedProjectCreateSchema.model_validate(
                {"members": ["ada"], "name": "Elsewhere"}
            )
        )

        assert sides(session, other.id).pilots == frozenset()


class TestHandOver:
    def test_a_block_that_was_pilots_and_is_the_persons_is_handed_at_the_move(
        self, camp: Camp
    ) -> None:
        pitch, job = _under_pass(camp)
        before = sides(camp.session, camp.project.id)
        camp.ended(job)

        hand_over(camp.session, before, AT)

        assert _handed(camp, pitch, "Q1") == AT
        assert _handed(camp, pitch, "D1") == AT

    def test_a_block_that_stays_pilots_has_none(self, camp: Camp) -> None:
        pitch, _ = _under_pass(camp)
        before = sides(camp.session, camp.project.id)

        hand_over(camp.session, before, AT)

        assert _handed(camp, pitch, "Q1") is None

    def test_a_block_pilot_answered_has_none(self, camp: Camp) -> None:
        """Answered while Pilot's, it is no person's to answer once the pass
        ends; the one beside it is."""
        pitch, job = _under_pass(camp)
        before = sides(camp.session, camp.project.id)
        camp.container.document_service().publish_read(
            _document(camp, pitch), RULED, job.id
        )
        camp.ended(job)

        hand_over(camp.session, before, AT)

        assert _handed(camp, pitch, "Q1") is None
        assert _handed(camp, pitch, "D1") == AT

    def test_a_block_of_an_item_closed_by_the_move_is_not_handed(
        self, camp: Camp
    ) -> None:
        pitch, job = _under_pass(camp)
        before = sides(camp.session, camp.project.id)
        camp.ended(job)
        pitch.done_at = AT
        pitch.done_cause_code = "cancelled"
        camp.session.flush()

        hand_over(camp.session, before, AT)

        assert _handed(camp, pitch, "Q1") is None

    def test_a_block_that_is_the_persons_from_its_put_keeps_none(
        self, camp: Camp
    ) -> None:
        """A Block that was no one's before the move and is the person's
        after it came from no side of Pilot's."""
        writer = camp.worker()
        camp.ended(writer)
        job = camp.job_after(writer)
        before = sides(camp.session, camp.project.id)
        camp.ended(job)
        pitch = camp.registered(writer, PITCH)

        hand_over(camp.session, before, AT)

        assert _handed(camp, pitch, "Q1") is None

    def test_a_block_that_becomes_pilots_again_loses_its_handed_at(
        self, camp: Camp
    ) -> None:
        pitch, job = _under_pass(camp)
        before = sides(camp.session, camp.project.id)
        job.state_code = SessionState.FAILED
        camp.session.flush()
        hand_over(camp.session, before, AT)
        assert _handed(camp, pitch, "Q1") == AT
        failed = sides(camp.session, camp.project.id)
        camp.retried(job)

        hand_over(camp.session, failed, LATER)

        assert _handed(camp, pitch, "Q1") is None
        assert _handed(camp, pitch, "D1") is None

    def test_a_block_handed_twice_keeps_the_later_time(self, camp: Camp) -> None:
        pitch, job = _under_pass(camp)
        before = sides(camp.session, camp.project.id)
        job.state_code = SessionState.FAILED
        camp.session.flush()
        hand_over(camp.session, before, AT)
        failed = sides(camp.session, camp.project.id)
        retry = camp.retried(job)
        hand_over(camp.session, failed, AT)
        retried = sides(camp.session, camp.project.id)
        camp.ended(retry)

        hand_over(camp.session, retried, LATER)

        assert _handed(camp, pitch, "Q1") == LATER

    def test_a_handed_block_a_later_move_leaves_the_persons_keeps_its_time(
        self, camp: Camp
    ) -> None:
        pitch, job = _under_pass(camp)
        before = sides(camp.session, camp.project.id)
        camp.ended(job)
        hand_over(camp.session, before, AT)
        other = camp.worker(conversation="conversation-2")
        again = sides(camp.session, camp.project.id)
        camp.stopped(other)

        hand_over(camp.session, again, LATER)

        assert _handed(camp, pitch, "Q1") == AT

    def test_a_claimed_action_its_run_hands_back_is_handed(self, camp: Camp) -> None:
        cut_over, job = _under_pass(camp, CUT_OVER)
        camp.ended(job)
        doing = camp.worker(conversation="conversation-2")
        camp.claim(cut_over, "A1", doing)
        before = sides(camp.session, camp.project.id)
        camp.stopped(doing)

        hand_over(camp.session, before, AT)

        assert _handed(camp, cut_over, "A1") == AT
        assert _handed(camp, cut_over, "A2") is None

    @pytest.mark.parametrize("research", [False, True])
    def test_a_block_its_run_is_done_with_is_handed_when_the_job_after_it_ends(
        self, camp: Camp, research: bool
    ) -> None:
        """A claim's or a research's run that ended without the Block's
        `done` or answer: done with it once the job after its turn ends,
        having asked the person nothing."""
        held, job = _under_pass(camp, PITCH if research else CUT_OVER)
        camp.ended(job)
        doing = camp.worker(conversation="conversation-2")
        if research:
            camp.research(held, "Q1", doing)
        else:
            camp.claim(held, "A1", doing)
        local_id = "Q1" if research else "A1"
        camp.ended(doing)
        after = camp.job_after(doing)
        before = sides(camp.session, camp.project.id)
        assert camp.block(held, local_id).id in before.pilots
        camp.ended(after)

        hand_over(camp.session, before, AT)

        assert _handed(camp, held, local_id) == AT

    def test_a_published_text_read_again_keeps_the_blocks_handed_at(
        self, camp: Camp
    ) -> None:
        """`handed_at` is the server's and read from no text: a new version
        of the document rewrites the Block's row and leaves it."""
        pitch, job = _under_pass(camp)
        before = sides(camp.session, camp.project.id)
        camp.ended(job)
        hand_over(camp.session, before, AT)

        camp.container.document_service().publish_read(
            _document(camp, pitch), PITCH + "\nA line more.\n", job.id
        )

        assert _handed(camp, pitch, "Q1") == AT
        assert _handed(camp, pitch, "D1") == AT
