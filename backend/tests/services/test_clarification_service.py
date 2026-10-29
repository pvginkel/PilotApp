"""The clarification run (design 3 §6.4; F52.2, D059; DB decision 63, 252 to
257): the questions a pass asked, their headings, the run's first turn and
its title; its placement when the pass's job ends; the writer's reply; each
document's clarification and each asked block's part of the reply."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from dependency_injector import providers
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.engine.bus import EngineEvent, ProjectChanged
from app.models import (
    Block,
    ClarificationRun,
    Document,
    Environment,
    Item,
    Project,
    Turn,
    Work,
    WriterQuestion,
)
from app.models.reference import SessionState, WorkTrigger
from app.services.clarification_service import (
    Asked,
    ClarificationService,
    asked,
    headings,
    message,
    of_pass,
    on_documents,
    reply_parts,
    title,
)
from app.services.container import ServiceContainer
from app.services.session_start_service import SessionStartService
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.starts import configured_starts
from tests.support.supervisor import Supervise

CUT_OVER = "/work/Example/docs/cut-over.md"
DRAIN = "/work/Example/docs/drain.md"
SURVEY = "/work/Example/docs/survey.md"

CUT_OVER_TEXT = """The cut-over.

```decision id=D1
options:
  - Friday
  - Monday
```

```question id=Q1
```
"""

DRAIN_TEXT = """The drain.

```question id=Q1
```

```decision id=D2
options:
  - Now
  - Later
```
"""

AT = datetime(2026, 9, 24, 14, 2, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def starts(
    container: ServiceContainer, supervise: Supervise
) -> Iterator[SessionStartService]:
    """The start the clarification run is placed through, its loops never
    run."""
    configured = configured_starts(container, supervise)
    container.session_start_service.override(providers.Object(configured))
    try:
        yield configured
    finally:
        container.session_start_service.reset_override()


def _service(container: ServiceContainer) -> ClarificationService:
    service: ClarificationService = container.clarification_service()
    return service


def _run(
    db: DbSession, container: ServiceContainer, project: Project, env: Environment
) -> models.Session:
    """A worker's run on its conversation, its turn ended and its work item
    done."""
    run = models.Session(
        project_id=project.id,
        environment_id=env.id,
        kind_code="work",
        conversation_id="conv-camp",
        cwd="/work/Example",
        agent="writer",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.IDLE,
        turns=1,
    )
    db.add(run)
    db.flush()
    records = container.record_service()
    records.place_work(project, run, "Cutting over", repo="example/Example")
    records.work_done(run.id, datetime.now(UTC))
    return run


def _registered(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    run: models.Session,
    path: str,
    text: str,
) -> Item:
    """A document the run registered, read at its end."""
    documents = container.document_service()
    item = documents.register(project, run, path).item
    documents.publish_read(db.get_one(Document, item.id), text, run.id)
    return item


def _job(
    db: DbSession,
    container: ServiceContainer,
    project: Project,
    trigger: WorkTrigger,
    trigger_item: models.Session | None,
) -> tuple[models.Session, Turn]:
    """A job of `trigger` after `trigger_item`, its one Turn in flight."""
    now = datetime.now(UTC)
    job = models.Session(
        project_id=project.id,
        kind_code="job",
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex,
        state_code=SessionState.RUNNING,
        turns=1,
        turn_started_at=now,
    )
    db.add(job)
    db.flush()
    turn = Turn(session_id=job.id, seq=1, message="/pre-rule", started_at=now)
    db.add(turn)
    container.record_service().place_work(
        project,
        job,
        "Pre-ruling docs/2",
        trigger=trigger,
        trigger_item_id=None if trigger_item is None else trigger_item.id,
    )
    return job, turn


def _ask(
    db: DbSession, turn: Turn, item: Item, local_id: str, question: str
) -> WriterQuestion:
    block = db.scalars(
        select(Block).where(Block.document_id == item.id, Block.local_id == local_id)
    ).one()
    asking = WriterQuestion(
        turn_id=turn.id, block_id=block.id, question=question, asked_at=AT
    )
    db.add(asking)
    db.flush()
    return asking


def _block_id(db: DbSession, item: Item, local_id: str) -> int:
    return db.scalars(
        select(Block.id).where(Block.document_id == item.id, Block.local_id == local_id)
    ).one()


def _clarifying(db: DbSession, pass_id: uuid.UUID) -> list[ClarificationRun]:
    return list(
        db.scalars(select(ClarificationRun).where(ClarificationRun.pass_id == pass_id))
    )


class TestAsked:
    def test_a_passs_questions_by_document_in_timeline_order_and_block_in_its(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _run(session, container, project, environment)
        cut_over = _registered(
            session, container, project, run, CUT_OVER, CUT_OVER_TEXT
        )
        drain = _registered(session, container, project, run, DRAIN, DRAIN_TEXT)
        asking, turn = _job(
            session, container, project, WorkTrigger.WORKER_TURN_ENDED, run
        )
        _ask(session, turn, drain, "D2", "Now means before the drain?")
        _ask(session, turn, cut_over, "Q1", "Which broker?")
        _ask(session, turn, drain, "Q1", "Whose queue?")
        _ask(session, turn, cut_over, "D1", "Which Friday?")
        # Another pass's question is not this pass's.
        survey = _registered(session, container, project, run, SURVEY, CUT_OVER_TEXT)
        other, other_turn = _job(
            session, container, project, WorkTrigger.WORKER_TURN_ENDED, run
        )
        _ask(session, other_turn, survey, "D1", "Which Friday?")

        assert asked(session, asking.id) == [
            Asked(
                CUT_OVER,
                cut_over.id,
                _block_id(session, cut_over, "D1"),
                "D1",
                "Which Friday?",
                AT,
            ),
            Asked(
                CUT_OVER,
                cut_over.id,
                _block_id(session, cut_over, "Q1"),
                "Q1",
                "Which broker?",
                AT,
            ),
            Asked(
                DRAIN,
                drain.id,
                _block_id(session, drain, "Q1"),
                "Q1",
                "Whose queue?",
                AT,
            ),
            Asked(
                DRAIN,
                drain.id,
                _block_id(session, drain, "D2"),
                "D2",
                "Now means before the drain?",
                AT,
            ),
        ]
        assert [each.item_id for each in asked(session, other.id)] == [survey.id]

    def test_its_follow_up_turns_questions_are_its_too(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _run(session, container, project, environment)
        cut_over = _registered(
            session, container, project, run, CUT_OVER, CUT_OVER_TEXT
        )
        asking, first = _job(
            session, container, project, WorkTrigger.WORKER_TURN_ENDED, run
        )
        follow_up = Turn(
            session_id=asking.id, seq=2, message="held", started_at=datetime.now(UTC)
        )
        session.add(follow_up)
        session.flush()
        _ask(session, first, cut_over, "D1", "Which Friday?")
        _ask(session, follow_up, cut_over, "Q1", "Which broker?")

        assert [each.local_id for each in asked(session, asking.id)] == ["D1", "Q1"]


def _asked(path: str, local_id: str, block_id: int, question: str = "Which?") -> Asked:
    return Asked(path, uuid.uuid4(), block_id, local_id, question, AT)


class TestHeadings:
    def test_each_block_is_answered_under_its_local_id(self) -> None:
        assert headings(
            [
                _asked(CUT_OVER, "D1", 1),
                _asked(CUT_OVER, "Q1", 2),
                _asked(DRAIN, "D2", 3),
            ]
        ) == {1: "## D1", 2: "## Q1", 3: "## D2"}

    def test_a_local_id_two_asked_documents_share_names_its_document(self) -> None:
        """Where two asked documents share a local id, the asked heading
        still names one block (DB 257)."""
        assert headings(
            [
                _asked(CUT_OVER, "D1", 1),
                _asked(CUT_OVER, "Q1", 2),
                _asked(DRAIN, "Q1", 3),
            ]
        ) == {1: "## D1", 2: f"## {CUT_OVER} Q1", 3: f"## {DRAIN} Q1"}


class TestMessage:
    def test_one_documents_questions_and_how_to_answer_them(self) -> None:
        assert message(
            [
                _asked(CUT_OVER, "D1", 1, "Which Friday?"),
                _asked(CUT_OVER, "Q1", 2, "Which broker?"),
            ]
        ) == (
            f"Pilot asks about {CUT_OVER}:\n"
            "- D1: Which Friday?\n"
            "- Q1: Which broker?\n"
            "\n"
            "Answer each under a heading per block id (`## D1`, `## Q1`); register"
            " nothing, start nothing; then end your turn."
        )

    def test_several_documents_questions_grouped_by_document(self) -> None:
        assert message(
            [
                _asked(CUT_OVER, "Q1", 1, "Which broker?"),
                _asked(DRAIN, "Q1", 2, "Whose queue?"),
                _asked(DRAIN, "D2", 3, "Now means before the drain?"),
            ]
        ) == (
            f"Pilot asks about {CUT_OVER}:\n"
            "- Q1: Which broker?\n"
            "\n"
            f"Pilot asks about {DRAIN}:\n"
            "- Q1: Whose queue?\n"
            "- D2: Now means before the drain?\n"
            "\n"
            f"Answer each under a heading per block id (`## {CUT_OVER} Q1`,"
            f" `## {DRAIN} Q1`, `## D2`); register nothing, start nothing; then"
            " end your turn."
        )


class TestTitle:
    @pytest.mark.parametrize(
        ("paths", "named"),
        [
            ([CUT_OVER, CUT_OVER], "Clarify cut-over.md"),
            ([CUT_OVER, DRAIN], "Clarify cut-over.md and drain.md"),
            ([CUT_OVER, DRAIN, SURVEY], "Clarify cut-over.md, drain.md and survey.md"),
        ],
    )
    def test_it_names_the_asked_documents_files(
        self, paths: list[str], named: str
    ) -> None:
        assert title([_asked(path, "D1", n) for n, path in enumerate(paths)]) == named


@pytest.mark.usefixtures("starts")
class TestPassEnded:
    def test_a_pass_that_asked_places_one_run_with_every_question(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _run(session, container, project, environment)
        cut_over = _registered(
            session, container, project, run, CUT_OVER, CUT_OVER_TEXT
        )
        drain = _registered(session, container, project, run, DRAIN, DRAIN_TEXT)
        asking, turn = _job(
            session, container, project, WorkTrigger.WORKER_TURN_ENDED, run
        )
        _ask(session, turn, cut_over, "D1", "Which Friday?")
        _ask(session, turn, drain, "Q1", "Whose queue?")

        _service(container).pass_ended(asking)

        [clarification] = _clarifying(session, asking.id)
        assert (clarification.reply, clarification.replied_at) == (None, None)
        clarifying = session.get_one(models.Session, clarification.id)
        assert (
            clarifying.kind_code,
            clarifying.environment_id,
            clarifying.conversation_id,
            clarifying.agent,
        ) == ("work", environment.id, "conv-camp", "writer")
        [first] = session.scalars(select(Turn).where(Turn.session_id == clarifying.id))
        assert first.message == message(asked(session, asking.id))
        item = session.get_one(Item, clarifying.id)
        assert item.title == "Clarify cut-over.md and drain.md"
        work = session.get_one(Work, clarifying.id)
        # The pass is its role's (DB decision 63).
        assert (work.trigger_code, work.trigger_item_id) == (None, None)

    @pytest.mark.parametrize(
        "trigger",
        [WorkTrigger.ITEM_DONE, WorkTrigger.SETUP, WorkTrigger.WORKER_TURN_ENDED],
    )
    def test_a_job_that_asked_nothing_or_is_no_pass_places_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        trigger: WorkTrigger,
    ) -> None:
        run = _run(session, container, project, environment)
        cut_over = _registered(
            session, container, project, run, CUT_OVER, CUT_OVER_TEXT
        )
        job, turn = _job(
            session,
            container,
            project,
            trigger,
            run if trigger is WorkTrigger.WORKER_TURN_ENDED else None,
        )
        if trigger is not WorkTrigger.WORKER_TURN_ENDED:
            _ask(session, turn, cut_over, "D1", "Which Friday?")
        placed = session.scalar(select(Item.seq).order_by(Item.seq.desc()).limit(1))

        _service(container).pass_ended(job)

        assert _clarifying(session, job.id) == []
        assert (
            session.scalar(select(Item.seq).order_by(Item.seq.desc()).limit(1))
            == placed
        )


class TestReplied:
    def _clarification(
        self,
        db: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> tuple[models.Session, ClarificationRun]:
        run = _run(db, container, project, environment)
        asking, _ = _job(db, container, project, WorkTrigger.WORKER_TURN_ENDED, run)
        clarifying = _run(db, container, project, environment)
        clarification = ClarificationRun(id=clarifying.id, pass_id=asking.id)
        db.add(clarification)
        db.flush()
        return clarifying, clarification

    def test_a_clarification_runs_reply_is_recorded_with_its_turns_end(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        clarifying, clarification = self._clarification(
            session, container, project, environment
        )

        _service(container).replied(clarifying, "## D1\nFriday the 3rd.", AT)

        assert (clarification.reply, clarification.replied_at) == (
            "## D1\nFriday the 3rd.",
            AT,
        )

    @pytest.mark.parametrize("reply", [None, ""])
    def test_a_turn_that_ended_with_no_text_leaves_none(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        reply: str | None,
    ) -> None:
        clarifying, clarification = self._clarification(
            session, container, project, environment
        )

        _service(container).replied(clarifying, reply, AT)

        assert (clarification.reply, clarification.replied_at) == (None, None)

    def test_another_runs_turn_end_records_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        run = _run(session, container, project, environment)

        _service(container).replied(run, "Done.", AT)

        assert session.scalars(select(ClarificationRun)).all() == []

    def test_the_reply_moves_the_timeline_once_it_commits(
        self,
        session: DbSession,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        project: Project,
        environment: Environment,
    ) -> None:
        clarifying, _ = self._clarification(session, container, project, environment)
        project_id = project.id
        with scoped_session(container):
            pass
        engine_events.clear()

        with scoped_session(container):
            _service(container).replied(clarifying, "## D1\nFriday the 3rd.", AT)

        assert ProjectChanged(project_id) in engine_events


class TestReplyParts:
    """An asked Block's part of the reply: the text under the heading the
    run asked for it, or none where the reply does not keep it (DB 257)."""

    HEADINGS = {1: "## D1", 2: "## Q1"}

    def test_each_part_runs_to_the_next_heading_of_its_level_or_higher(
        self,
    ) -> None:
        reply = (
            "Here are my answers.\n\n"
            "## D1\n\nThe Friday after the freeze.\n\n"
            "### Why\nThe freeze ends Thursday.\n\n"
            "## Q1\nThe v1 broker's.\n\n"
            "# Also\nNothing else."
        )

        assert reply_parts(reply, self.HEADINGS) == {
            1: "The Friday after the freeze.\n\n### Why\nThe freeze ends Thursday.",
            2: "The v1 broker's.",
        }

    def test_a_reply_that_keeps_no_heading_has_no_parts(self) -> None:
        assert reply_parts("Friday, and the v1 broker's.", self.HEADINGS) == {}

    def test_a_heading_kept_with_nothing_under_it_or_at_another_level_is_none(
        self,
    ) -> None:
        reply = "## D1\n\n   \n## Q1 ##\nThe v1 broker's.\n### D1\nFriday."

        assert reply_parts(reply, self.HEADINGS) == {
            2: "The v1 broker's.\n### D1\nFriday."
        }

    def test_a_heading_in_a_fence_is_none_and_one_kept_twice_reads_where_first(
        self,
    ) -> None:
        reply = (
            "```markdown\n## D1\nNot this.\n```\n"
            "##   D1  \nFriday.\n"
            "~~~\n## Q1\n~~~\n"
            "## D1\nMonday."
        )

        assert reply_parts(reply, self.HEADINGS) == {1: "Friday.\n~~~\n## Q1\n~~~"}

    def test_a_heading_naming_its_document_names_its_block(self) -> None:
        reply = f"## {CUT_OVER} Q1\nThe cut-over's.\n## {DRAIN} Q1\nThe drain's."

        assert reply_parts(reply, {1: f"## {CUT_OVER} Q1", 2: f"## {DRAIN} Q1"}) == {
            1: "The cut-over's.",
            2: "The drain's.",
        }


class TestClarifications:
    """A document's clarification, read from the pass that asked about its
    blocks and the run that clarifies it, never stored (DB 257)."""

    def _asked(
        self,
        db: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> tuple[models.Session, Item, Item]:
        """A pass that asked about Q1 and D1 of the cut-over and Q1 of the
        drain: their headings name the documents of the shared Q1."""
        run = _run(db, container, project, environment)
        cut_over = _registered(db, container, project, run, CUT_OVER, CUT_OVER_TEXT)
        drain = _registered(db, container, project, run, DRAIN, DRAIN_TEXT)
        asking, turn = _job(db, container, project, WorkTrigger.WORKER_TURN_ENDED, run)
        _ask(db, turn, drain, "Q1", "Whose broker?")
        _ask(db, turn, cut_over, "Q1", "How long?")
        first = _ask(db, turn, cut_over, "D1", "Which Friday?")
        first.asked_at = datetime(2026, 9, 24, 14, 1, tzinfo=UTC)
        db.flush()
        return asking, cut_over, drain

    def _replied(
        self,
        db: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        asking: models.Session,
        reply: str,
    ) -> None:
        clarifying = _run(db, container, project, environment)
        db.add(
            ClarificationRun(
                id=clarifying.id, pass_id=asking.id, reply=reply, replied_at=AT
            )
        )
        db.flush()

    def test_before_the_reply_each_document_holds_its_questions(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        asking, cut_over, drain = self._asked(session, container, project, environment)

        found = on_documents(session, [cut_over.id, drain.id])

        [on_cut_over] = found[cut_over.id]
        assert [(each.local_id, each.question) for each in on_cut_over.questions] == [
            ("D1", "Which Friday?"),
            ("Q1", "How long?"),
        ]
        assert on_cut_over.asked_at == datetime(2026, 9, 24, 14, 1, tzinfo=UTC)
        assert dict(on_cut_over.headings) == {
            _block_id(session, cut_over, "D1"): "## D1",
            _block_id(session, cut_over, "Q1"): f"## {CUT_OVER} Q1",
        }
        assert (on_cut_over.reply, on_cut_over.replied_at) == (None, None)
        assert (dict(on_cut_over.parts), on_cut_over.split) == ({}, False)
        [on_drain] = found[drain.id]
        assert [each.local_id for each in on_drain.questions] == ["Q1"]
        assert dict(on_drain.headings) == {
            _block_id(session, drain, "Q1"): f"## {DRAIN} Q1"
        }
        assert of_pass(session, asking.id) == [on_cut_over, on_drain]

    def test_a_reply_that_kept_the_headings_splits_per_block(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        asking, cut_over, drain = self._asked(session, container, project, environment)
        reply = (
            f"## D1\nThe Friday after the freeze.\n## {CUT_OVER} Q1\nAn hour.\n"
            f"## {DRAIN} Q1\nThe v1 broker's."
        )
        self._replied(session, container, project, environment, asking, reply)

        found = on_documents(session, [cut_over.id, drain.id])

        [on_cut_over] = found[cut_over.id]
        assert (on_cut_over.reply, on_cut_over.replied_at) == (reply, AT)
        assert dict(on_cut_over.parts) == {
            _block_id(session, cut_over, "D1"): "The Friday after the freeze.",
            _block_id(session, cut_over, "Q1"): "An hour.",
        }
        assert on_cut_over.split
        [on_drain] = found[drain.id]
        assert dict(on_drain.parts) == {
            _block_id(session, drain, "Q1"): "The v1 broker's."
        }
        assert on_drain.split

    def test_a_reply_that_did_not_keep_them_reads_whole(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        """One asked block's heading kept and another's not: the document's
        reply shows whole, the kept part still read; the other document's
        splits."""
        asking, cut_over, drain = self._asked(session, container, project, environment)
        reply = f"## D1\nFriday.\n## {DRAIN} Q1\nThe v1 broker's."
        self._replied(session, container, project, environment, asking, reply)

        found = on_documents(session, [cut_over.id, drain.id])

        [on_cut_over] = found[cut_over.id]
        assert dict(on_cut_over.parts) == {
            _block_id(session, cut_over, "D1"): "Friday."
        }
        assert (on_cut_over.reply, on_cut_over.split) == (reply, False)
        assert found[drain.id][0].split

    def test_one_per_pass_in_the_order_first_asked_and_none_where_none_asked(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        _, _, drain = self._asked(session, container, project, environment)
        other = _run(session, container, project, environment)
        survey = _registered(session, container, project, other, SURVEY, DRAIN_TEXT)
        later, turn = _job(
            session, container, project, WorkTrigger.WORKER_TURN_ENDED, other
        )
        earlier = _ask(session, turn, drain, "D2", "Now or later?")
        earlier.asked_at = datetime(2026, 9, 24, 13, 0, tzinfo=UTC)
        session.flush()

        found = on_documents(session, [drain.id, survey.id])

        assert set(found) == {drain.id}
        assert [
            [each.local_id for each in clarification.questions]
            for clarification in found[drain.id]
        ] == [["D2"], ["Q1"]]
        assert of_pass(session, later.id)[0].headings == {
            _block_id(session, drain, "D2"): "## D2"
        }
        assert of_pass(session, uuid.uuid4()) == []
