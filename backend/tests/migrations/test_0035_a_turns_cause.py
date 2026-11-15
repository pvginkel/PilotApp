"""Revision 0035: a Turn's cause (DB 351, 352), over Turns as revision 0034
leaves them, each placed from its rows: the revision's downgrade builds
0034's schema in the test's transaction."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Turn, User
from app.models.reference import SessionState, TurnCause, WorkTrigger
from app.services.brief_service import FOLLOW_UP_END, RESTARTED
from app.services.container import ServiceContainer
from app.services.relay_service import CONTINUE
from app.services.session_start_service import (
    NUDGE,
    NUDGE_AFTER_A_PAUSE,
    NUDGE_AFTER_A_STOP,
)
from tests.support.revisions import run_revision
from tests.support.working_on import Camp

AT = datetime(2026, 11, 15, 9, 30, tzinfo=UTC)
BRIEF = "Build the camp."
FOLLOW_UP = f"Your save of `notes.md` is held: `notes.md: x`.\n{FOLLOW_UP_END}"


def _run(db: DbSession, step: str) -> None:
    """Revision 0035's `step`, `upgrade` or `downgrade`."""
    run_revision(db, "0035", step)


def _columns(db: DbSession) -> set[str]:
    return {column["name"] for column in inspect(db.connection()).get_columns("turns")}


class _Before:
    """A project's Turns as they stood before the revision, which reads
    nothing of the cause they are written with here."""

    def __init__(self, container: ServiceContainer, db: DbSession, ada: User) -> None:
        self.db = db
        self.camp = Camp(container, db)
        self.ada = ada

    def chat(self) -> models.Session:
        return self.camp._session("chat", SessionState.IDLE, "chat-conversation")

    def continuation(self, run: models.Session) -> models.Session:
        """A new run on the run's conversation, its trigger Item the run's
        own, as `SessionStartService.continue_run` places one."""
        continuing = self.camp._session("work", SessionState.IDLE, run.conversation_id)
        self.camp.container.record_service().place_work(
            self.camp.project,
            continuing,
            "Building the camp",
            repo="example/Camp",
            trigger_item_id=run.id,
        )
        return continuing

    def turn(
        self, run: models.Session, message: str, *, author: User | None = None
    ) -> int:
        """The Session's next Turn; the id."""
        run.turns += 1
        turn = Turn(
            session_id=run.id,
            seq=run.turns,
            author_user_id=None if author is None else author.id,
            message=message,
            words=None if author is None else message,
            started_at=AT,
            cause_code=TurnCause.BRIEF if author is None else TurnCause.PERSON,
        )
        self.db.add(turn)
        self.db.flush()
        return turn.id

    def placed(self) -> dict[int, str]:
        """Every Turn's cause after the revision's downgrade and upgrade."""
        _run(self.db, "downgrade")
        assert "cause_code" not in _columns(self.db)
        _run(self.db, "upgrade")
        return {
            row[0]: row[1]
            for row in self.db.execute(text("SELECT id, cause_code FROM turns"))
        }


@pytest.fixture
def before(container: ServiceContainer, session: DbSession, person: User) -> _Before:
    return _Before(container, session, person)


class TestAFirstTurn:
    def test_a_work_items_and_a_jobs_is_the_brief(self, before: _Before) -> None:
        worker = before.camp.worker()
        work = before.turn(worker, BRIEF)
        job = before.turn(before.camp.job_after(worker), "/pre-rule")
        setup = before.turn(before.camp.job_on(None, WorkTrigger.SETUP), "/setup")

        placed = before.placed()

        assert (placed[work], placed[job], placed[setup]) == ("brief",) * 3

    def test_a_waits_runs_is_the_wait_run(self, before: _Before) -> None:
        worker = before.camp.worker()
        run = before.camp.job_on(before.camp.wait(worker), WorkTrigger.WAIT_FIRED)
        first = before.turn(run, "The wait fired.")

        assert before.placed()[first] == "wait_run"

    def test_a_continuations_is_the_continuation(self, before: _Before) -> None:
        worker = before.camp.worker(conversation="camp-conversation")
        first = before.turn(before.continuation(worker), "Your documents are closed.")

        assert before.placed()[first] == "continuation"

    def test_a_clarification_runs_is_the_clarification(self, before: _Before) -> None:
        worker = before.camp.worker(conversation="camp-conversation")
        asking = before.camp.job_after(worker)
        first = before.turn(before.camp.clarification(asking, worker), "Which lake?")

        assert before.placed()[first] == "clarification"

    def test_a_chats_with_its_author_is_the_persons(self, before: _Before) -> None:
        """The chat's brief goes before a person's words, and the Turn is
        theirs."""
        chat = before.chat()
        first = before.turn(chat, "What next?", author=before.ada)
        later = before.turn(chat, "And then?", author=before.ada)

        placed = before.placed()

        assert (placed[first], placed[later]) == ("person", "person")


class TestALaterTurnOfTheServers:
    def test_the_follow_up_is_known_by_its_last_line(self, before: _Before) -> None:
        chat, job = before.chat(), before.camp.job_on(None, WorkTrigger.SETUP)
        before.turn(chat, "What next?", author=before.ada)
        before.turn(job, "/setup")
        on_a_chat = before.turn(chat, FOLLOW_UP)
        on_a_job = before.turn(job, FOLLOW_UP)

        placed = before.placed()

        assert (placed[on_a_chat], placed[on_a_job]) == ("follow_up", "follow_up")

    @pytest.mark.parametrize("words", [NUDGE, NUDGE_AFTER_A_STOP, NUDGE_AFTER_A_PAUSE])
    def test_a_nudge_is_known_by_its_last_sentence(
        self, before: _Before, words: str
    ) -> None:
        worker, job = before.camp.worker(), before.camp.job_on(None, WorkTrigger.SETUP)
        before.turn(worker, BRIEF)
        before.turn(job, "/setup")
        to_a_work_item = before.turn(worker, words)
        to_a_job = before.turn(job, words)

        placed = before.placed()

        assert (placed[to_a_work_item], placed[to_a_job]) == ("nudge", "nudge")

    def test_a_work_items_re_create_is_known_by_the_restarts_line(
        self, before: _Before
    ) -> None:
        worker = before.camp.worker()
        before.turn(worker, BRIEF)
        restarted = before.turn(
            worker,
            f"{RESTARTED} You registered no documents."
            f" Your brief again, whole:\n\n{BRIEF}",
        )

        assert before.placed()[restarted] == "carry_on"

    def test_continue_is_a_resume_on_a_work_item_and_the_re_create_elsewhere(
        self, before: _Before
    ) -> None:
        """Only a work item is resumed; one that the relay re-created before
        the restart's line was written carried "continue" too, and reads as
        a Resume."""
        worker, chat = before.camp.worker(), before.chat()
        job = before.camp.job_after(worker)
        before.turn(worker, BRIEF)
        before.turn(chat, "What next?", author=before.ada)
        before.turn(job, "/pre-rule")
        on_a_work_item = before.turn(worker, CONTINUE)
        on_a_chat = before.turn(chat, CONTINUE)
        on_a_job = before.turn(job, CONTINUE)

        placed = before.placed()

        assert (placed[on_a_work_item], placed[on_a_chat], placed[on_a_job]) == (
            "resume",
            "carry_on",
            "carry_on",
        )

    def test_a_first_turns_role_does_not_place_a_later_one(
        self, before: _Before
    ) -> None:
        worker = before.camp.worker(conversation="camp-conversation")
        clarifying = before.camp.clarification(before.camp.job_after(worker), worker)
        wait_run = before.camp.job_on(before.camp.wait(worker), WorkTrigger.WAIT_FIRED)
        before.turn(clarifying, "Which lake?")
        before.turn(wait_run, "The wait fired.")
        resumed = before.turn(clarifying, CONTINUE)
        carried = before.turn(wait_run, CONTINUE)

        placed = before.placed()

        assert (placed[resumed], placed[carried]) == ("resume", "carry_on")


class TestATurnItsRowsCannotPlace:
    """A message sent again where no Turn of the Session had gone out, which
    a Resume, a nudge and the relay's re-create each write: it takes the
    cause of its usual writer."""

    def test_a_work_items_brief_sent_again_is_a_resume(self, before: _Before) -> None:
        """A failed start's Resume, the usual one; a nudge to a work item
        stopped before its conversation began reads as a Resume too."""
        worker = before.camp.worker()
        before.turn(worker, BRIEF)
        again = before.turn(worker, BRIEF)

        assert before.placed()[again] == "resume"

    def test_a_chats_or_a_jobs_message_sent_again_is_the_re_create(
        self, before: _Before
    ) -> None:
        """The relay's re-create sends a person's message again with no
        author; a job's nudge that sent its brief again reads as the
        re-create too."""
        chat, job = before.chat(), before.camp.job_on(None, WorkTrigger.SETUP)
        before.turn(chat, "What next?", author=before.ada)
        before.turn(job, "/setup")
        to_a_chat = before.turn(chat, "What next?")
        to_a_job = before.turn(job, "/setup")

        placed = before.placed()

        assert (placed[to_a_chat], placed[to_a_job]) == ("carry_on", "carry_on")


class TestTheColumn:
    def test_a_turn_written_after_it_needs_its_cause(self, before: _Before) -> None:
        worker = before.camp.worker()
        _run(before.db, "downgrade")
        _run(before.db, "upgrade")

        with pytest.raises(IntegrityError) as raised:
            before.db.execute(
                text(
                    "INSERT INTO turns (session_id, seq, message, started_at)"
                    " VALUES (:session, 1, 'Go.', now())"
                ),
                {"session": worker.id},
            )
        assert raised.value.orig.diag.column_name == "cause_code"

    def test_the_downgrade_drops_the_cause_and_its_type(self, before: _Before) -> None:
        _run(before.db, "downgrade")

        assert "cause_code" not in _columns(before.db)
        assert (
            before.db.execute(
                text("SELECT count(*) FROM pg_type WHERE typname = 'turn_cause'")
            ).scalar_one()
            == 0
        )
