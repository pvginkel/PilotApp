"""What Pilot's inventory hands the labeller (F152.2; `labeller.md` § What
Pilot hands with a conversation): each Transcript's labeller version and
stamp, and each conversation a Session of Pilot's ran, collected or not,
with its Sessions, their Holds and Turns, and the Documents they put."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Hold, Turn, User
from app.models.reference import HoldKind, SessionState, TurnCause
from app.services.container import ServiceContainer
from app.services.labeller_context import BRIEF_LENGTH
from app.services.publication_service import PublicationService
from tests.support.publications import STAMP, labelling, whole
from tests.support.statements import sent
from tests.support.transcripts import CAMP, OTHER
from tests.support.vocabularies import VERSION, vocabularies
from tests.support.working_on import Camp

AT = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
THIRD = "7c1e4b90-2d5f-4a83-9e06-b4f8d2a6c517"


@pytest.fixture
def publications(container: ServiceContainer) -> PublicationService:
    container.vocabulary_service().declare(vocabularies())
    return container.publication_service()


@pytest.fixture
def camp(container: ServiceContainer, session: DbSession, person: User) -> Camp:
    """The project of Ada, who has signed in."""
    camp = Camp(container, session)
    camp.project.repo = "example/CampSpecs"
    session.flush()
    return camp


def _made(session: DbSession, run: models.Session, minutes: int) -> models.Session:
    run.created_at = AT + timedelta(minutes=minutes)
    session.flush()
    return run


def _turn(
    session: DbSession,
    run: models.Session,
    seq: int,
    message: str,
    *,
    by: User | None = None,
    cause: TurnCause = TurnCause.BRIEF,
) -> None:
    session.add(
        Turn(
            session_id=run.id,
            seq=seq,
            author_user_id=None if by is None else by.id,
            message=message,
            words=None if by is None else message,
            started_at=AT + timedelta(minutes=seq),
            cause_code=TurnCause.PERSON if by is not None else cause,
        )
    )
    session.flush()


def _chat(session: DbSession, camp: Camp, conversation: str) -> models.Session:
    """A chat of the project's on `conversation`."""
    chat = models.Session(
        project_id=camp.project.id,
        environment_id=camp.environment.id,
        kind_code="chat",
        cwd="/work/PilotProjects",
        conversation_id=conversation,
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.RUNNING,
    )
    session.add(chat)
    session.flush()
    return chat


def _conversation(publications: PublicationService, session_id: str) -> Any:
    [handed] = [
        each
        for each in publications.inventory().conversations
        if each.session_id == session_id
    ]
    return handed


class TestTheTranscriptsLabels:
    """Each Transcript is held under the labeller's version and stamp its
    labels were written under (P-326)."""

    def test_a_labelled_transcript_is_held_under_its_labellers_version_and_stamp(
        self, publications: PublicationService
    ) -> None:
        publications.publish(whole(labelling=labelling()))
        publications.publish(whole(session_id=OTHER))

        held = {
            each.session_id: (each.labeller, each.stamp)
            for each in publications.inventory().transcripts
        }

        assert held == {CAMP: (VERSION, STAMP), OTHER: (None, None)}

    def test_one_published_since_with_no_labelling_keeps_its_version_and_no_stamp(
        self, publications: PublicationService
    ) -> None:
        """A labeller that did not answer keeps the labels Pilot holds and
        leaves no stamp, so the next labeller to answer relabels it."""
        publications.publish(whole(labelling=labelling()))
        publications.publish(whole(file_size=50_000))

        [held] = publications.inventory().transcripts

        assert (held.labeller, held.stamp) == (VERSION, None)


class TestTheConversations:
    """Every conversation a Session of Pilot's ran, collected or not."""

    def test_each_conversation_a_session_ran_is_handed_by_its_id_collected_or_not(
        self,
        session: DbSession,
        publications: PublicationService,
        camp: Camp,
    ) -> None:
        camp.worker(conversation=OTHER)
        camp.worker(conversation=CAMP)
        camp.worker()
        publications.publish(whole())

        handed = publications.inventory().conversations

        assert [each.session_id for each in handed] == sorted([CAMP, OTHER])

    def test_a_record_with_no_conversation_hands_none(
        self, publications: PublicationService, camp: Camp
    ) -> None:
        camp.worker()

        assert publications.inventory().conversations == []

    def test_its_sessions_come_in_the_order_pilot_made_them_with_their_facts(
        self,
        session: DbSession,
        publications: PublicationService,
        camp: Camp,
    ) -> None:
        """A worker's run, its clarification run on its conversation, and a
        job on it, which runs in no repository but its Project's."""
        worker = _made(session, camp.worker(conversation=CAMP), 0)
        job = _made(session, camp.job_after(worker), 5)
        job.conversation_id = CAMP
        clarification = _made(session, camp.clarification(job, worker), 2)

        handed = _conversation(publications, CAMP)

        assert [
            (run.id, run.kind, run.created_at, run.repo, run.clarification)
            for run in handed.sessions
        ] == [
            (worker.id, "work", AT, "example/Camp", False),
            (clarification.id, "work", AT + timedelta(minutes=2), "example/Camp", True),
            (job.id, "job", AT + timedelta(minutes=5), "example/CampSpecs", False),
        ]

    def test_a_sessions_brief_is_its_first_turn_no_person_wrote_cut_short(
        self,
        session: DbSession,
        person: User,
        publications: PublicationService,
        camp: Camp,
    ) -> None:
        worker = _made(session, camp.worker(conversation=CAMP), 0)
        _turn(session, worker, 1, "Where is the lake?", by=person)
        _turn(session, worker, 2, "Survey the lake. " * 40, cause=TurnCause.RESUME)
        _turn(session, worker, 3, "Go on.", cause=TurnCause.NUDGE)
        asked = _made(session, camp.worker(conversation=CAMP), 1)
        _turn(session, asked, 1, "Is the lake open?", by=person)
        quiet = _made(session, camp.worker(conversation=CAMP), 2)

        handed = _conversation(publications, CAMP)

        assert [run.brief for run in handed.sessions] == [
            ("Survey the lake. " * 40)[:BRIEF_LENGTH],
            None,
            None,
        ]
        assert BRIEF_LENGTH == 400
        assert [run.id for run in handed.sessions] == [worker.id, asked.id, quiet.id]

    def test_a_sessions_holds_and_turns_come_in_their_order(
        self,
        session: DbSession,
        person: User,
        publications: PublicationService,
        camp: Camp,
    ) -> None:
        worker = camp.worker(state=SessionState.HELD, conversation=CAMP)
        session.add_all(
            [
                Hold(
                    session_id=worker.id,
                    kind_code=HoldKind.SLOT,
                    started_at=AT + timedelta(minutes=40),
                ),
                Hold(
                    session_id=worker.id,
                    kind_code=HoldKind.WEEK_HALT,
                    started_at=AT,
                    ended_at=AT + timedelta(minutes=30),
                ),
            ]
        )
        session.flush()
        _turn(session, worker, 2, "Go on.", cause=TurnCause.NUDGE)
        _turn(session, worker, 1, "Survey the lake.")
        _turn(session, worker, 3, "And the river?", by=person)

        [run] = _conversation(publications, CAMP).sessions

        assert [hold.model_dump() for hold in run.holds] == [
            {
                "kind": "week_halt",
                "started_at": AT,
                "ended_at": AT + timedelta(minutes=30),
            },
            {
                "kind": "slot",
                "started_at": AT + timedelta(minutes=40),
                "ended_at": None,
            },
        ]
        assert [turn.model_dump() for turn in run.turns] == [
            {"started_at": AT + timedelta(minutes=1), "cause": "brief"},
            {"started_at": AT + timedelta(minutes=2), "cause": "nudge"},
            {"started_at": AT + timedelta(minutes=3), "cause": "person"},
        ]

    def test_a_session_with_no_hold_or_turn_is_handed_both_lists_empty(
        self, publications: PublicationService, camp: Camp
    ) -> None:
        """The stamp tells a list handed empty from one left out, so each is
        handed in one form at every walk."""
        worker = camp.worker(conversation=CAMP)

        handed = _conversation(publications, CAMP)

        assert handed.model_dump(mode="json") == {
            "session_id": CAMP,
            "sessions": [
                {
                    "id": str(worker.id),
                    "kind": "work",
                    "created_at": worker.created_at.isoformat().replace("+00:00", "Z"),
                    "brief": None,
                    "repo": "example/Camp",
                    "clarification": False,
                    "holds": [],
                    "turns": [],
                }
            ],
            "documents": [],
        }

    def test_its_documents_are_those_its_sessions_put_in_the_order_made(
        self,
        session: DbSession,
        container: ServiceContainer,
        publications: PublicationService,
        camp: Camp,
    ) -> None:
        """One the worker registered, one of Pilot's own a chat on the
        conversation added; and none a Session of another conversation or
        of none put."""
        worker = camp.worker(conversation=CAMP)
        chat = _chat(session, camp, CAMP)
        registered = camp.registered(worker, read=False)
        own = container.document_service().bear_item(
            camp.project, "action", "The cut-over", chat
        )
        camp.registered(camp.worker(conversation=OTHER), read=False)
        camp.registered(camp.worker(), read=False)
        for document, minutes in ((own, 1), (registered, 2)):
            session.get_one(models.Document, document.id).created_at = AT + timedelta(
                minutes=minutes
            )
        session.flush()
        source_path = session.get_one(models.Document, registered.id).source_path

        handed = _conversation(publications, CAMP)

        assert source_path is not None
        assert [document.model_dump() for document in handed.documents] == [
            {"id": own.id, "session": chat.id, "source_path": None},
            {"id": registered.id, "session": worker.id, "source_path": source_path},
        ]

    def test_an_unchanged_record_is_handed_alike_at_every_walk(
        self,
        session: DbSession,
        publications: PublicationService,
        camp: Camp,
    ) -> None:
        worker = camp.worker(state=SessionState.HELD, conversation=CAMP)
        session.add(Hold(session_id=worker.id, kind_code=HoldKind.SLOT, started_at=AT))
        _turn(session, worker, 1, "Survey the lake.")
        camp.registered(worker, read=False)
        camp.worker(conversation=CAMP)

        walks = [publications.inventory().model_dump_json() for _ in range(2)]

        assert walks[0] == walks[1]


class TestTheRead:
    def test_the_inventory_reads_five_statements_however_much_it_holds(
        self,
        session: DbSession,
        publications: PublicationService,
        camp: Camp,
    ) -> None:
        """The Transcripts with their versions in one; the Sessions with
        their briefs, the Holds, the Turns and the Documents in one each."""

        def counted() -> int:
            with sent(session) as each:
                publications.inventory()
            return len(each.texts)

        empty = counted()
        for conversation in (CAMP, OTHER, THIRD):
            worker = camp.worker(state=SessionState.HELD, conversation=conversation)
            session.add(
                Hold(session_id=worker.id, kind_code=HoldKind.SLOT, started_at=AT)
            )
            _turn(session, worker, 1, "Survey the lake.")
            _turn(session, worker, 2, "Go on.", cause=TurnCause.NUDGE)
            camp.registered(worker, read=False)
            publications.publish(whole(session_id=conversation, labelling=labelling()))
        publications.publish(whole(session_id=str(uuid.uuid4())))

        assert (empty, counted()) == (5, 5)
