"""The clarification run (design 3 §6.4; F52.2, D059; DB decision 63, 252 to
257): the questions a pass asked, their headings, the run's first turn and
its title; its placement when the pass's job ends; the writer's reply."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from dependency_injector import providers
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
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
            ([CUT_OVER, CUT_OVER], f"Clarify {CUT_OVER}"),
            ([CUT_OVER, DRAIN], f"Clarify {CUT_OVER} and {DRAIN}"),
            ([CUT_OVER, DRAIN, SURVEY], f"Clarify {CUT_OVER}, {DRAIN} and {SURVEY}"),
        ],
    )
    def test_it_names_the_asked_documents_paths(
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
        assert item.title == f"Clarify {CUT_OVER} and {DRAIN}"
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
