"""The scenarios' load (F122.2, F122.6): an invented scenario put into the
record as it stands now, its conversations through the service a
collector's publication writes through; and the dev seed's history, days of
the fleet's work drawn from a seed, written the same way at their own
times.

A scenario's package knows nothing of the record, so what Pilot holds of a
conversation before a collector reads its transcript is written here (its
`script.Ran`): for each session Pilot ran, a Session of the project given
for the scenario's, over, whose `conversation_id` is the conversation's id,
with its Turns, each sent by Pilot or by the scenario's person of that
handle; one run under a work item or a job placed as a Work with its Item,
done at its last Turn's end, one under a chat with its Chat, closed then.
It is written before the conversation is published, so that the publication
places each Launch its Turn started (DB 538). A scenario the route loads, as
the load built it, is handed to the collector's fake, which serves its
conversations' readings where it is the backend's collector (F122.5).

A load's conversations' ids are drawn from the scenario's name and the
projects it is loaded on, so a second load on the same projects is a whole
publication of the same transcripts and replaces the first, the record
holding the scenario once however often it is loaded there, and a load on
other projects is a scenario of its own beside it: what Pilot holds of a run
stays on its project. Each publication carries the labels the stub labeller
gives its file (F122.5), whose vocabularies the write declares first, as a
collector does before it publishes a label of them; the conversation the
stub adopts for a scenario's group is adopted by the group's adopted
Project, which the first load makes and a later one finds by the group's key
(F152.8).
"""

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta

from pilot_collection.publication import PublicationSchema
from pilot_collection.vocabularies import VocabulariesSchema
from pilot_scenario import SCENARIO, TALLY, Builder, Scenario, SentRun
from pilot_scenario.history import ZONE, History, Place
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.engine.record import RecordService
from app.exceptions import RecordNotFoundException, ValidationException
from app.models import Chat, Environment, Item, Project, Transcript, Turn, User
from app.models import Session as AgentSession
from app.models.reference import (
    ChatKind,
    CloseCause,
    SessionState,
    TurnCause,
    UserKind,
    WorkTrigger,
)
from app.services.fake_collector import FakeCollector
from app.services.launch_placement import conversation_turn
from app.services.publication_service import PublicationService
from app.services.vocabulary_service import VocabularyService

SCENARIOS = {scenario.name: scenario for scenario in (SCENARIO, TALLY)}
"""The scenarios a spec loads, by name."""

HISTORY = History(
    name="seed",
    seed=54,
    calls_a_day=15,
    longest=40,
    places=(
        Place("seed-swap", "Seed swap", "SeedSwap", 5, ("packets", "swaps", "beans")),
        Place("tide-table", "Tide table", "TideTable", 3, ("tides", "moon", "harbour")),
        Place("kite-shop", "Kite shop", "KiteShop", 2, ("kites", "spars", "lines")),
    ),
)
"""The dev seed's history: some fifteen Calls a weekday on three projects
of its own, a conversation's main thread forty Calls at most."""

HISTORY_DAYS = 63
"""The days the dev seed's history holds, the day of its load the last:
nine weeks, which the last eight quota weeks and the running one fall in."""


class ScenarioService:
    def __init__(
        self,
        db: Session,
        publication_service: PublicationService,
        vocabulary_service: VocabularyService,
        fake_collector: FakeCollector,
        record_service: RecordService,
    ) -> None:
        self.db = db
        self.publication_service = publication_service
        self.vocabulary_service = vocabulary_service
        self.fake_collector = fake_collector
        self.record_service = record_service

    def load(
        self, scenario: Scenario, projects: Mapping[str, uuid.UUID]
    ) -> list[Transcript]:
        """Load `scenario` in the caller's transaction, its last moment now,
        hand it to the collector's fake, and return its Transcripts (`write`).

        Raises:
            ValidationException: `projects` names another set of the
                scenario's projects than those Pilot ran a session on.
            RecordNotFoundException: no Project has an id given, or no
                person the handle a Turn's author is.
            NoServiceUserException: the record holds no adopted Project of
                a group the scenario names, and the stage has no service
                user to make it.
        """
        now = self.db.scalar(select(func.now()))
        assert now is not None
        builder = Builder(_on(scenario, projects), now)
        transcripts = self.write(builder, projects)
        self.fake_collector.scenario(builder)
        return transcripts

    def write(
        self, builder: Builder, projects: Mapping[str, uuid.UUID]
    ) -> list[Transcript]:
        """The scenario as `builder` built it, in the caller's transaction:
        what Pilot holds of each session it ran, then the stub's
        vocabularies declared and each thread published, and its Transcripts in the publications' order, each session's main
        thread, then its sub-agents'. Where the record holds the scenario,
        it then holds it as this build has it: its times the build's, and
        its Sessions of Pilot's on the projects given.

        `projects` gives, for each of the scenario's projects Pilot ran a
        session on, by the scenario's name of it, the Project that stands
        for it.

        Raises:
            As `load`.
        """
        runs = builder.runs()
        on = sorted({run.project for run in runs})
        if sorted(projects) != on:
            raise ValidationException(
                "Cannot load the scenario because `projects` gives a project for "
                f"{_listed(sorted(projects))}, and the scenario's Sessions of "
                f"Pilot's are on {_listed(on)}"
            )
        standing: dict[str, Project] = {}
        for name, project_id in projects.items():
            project = self.db.get(Project, project_id)
            if project is None:
                raise RecordNotFoundException("Project", str(project_id))
            standing[name] = project
        for run in runs:
            self._session(standing[run.project], run)
        self.vocabulary_service.declare(
            VocabulariesSchema.model_validate(builder.vocabularies())
        )
        return [
            self.publication_service.publish(
                PublicationSchema.model_validate(publication)
            )
            for publication in builder.publications()
        ]

    def history(self, projects: Mapping[str, uuid.UUID]) -> int:
        """The dev seed's history (`HISTORY`) written in the caller's
        transaction: its `HISTORY_DAYS` days, the last today's, each at its
        own times, today's with only the conversations over by now; and the
        Calls it holds. `projects` gives the Project that stands for each of
        its places, by the place's slug.

        Raises:
            As `load`.
        """
        now = self.db.scalar(select(func.now()))
        assert now is not None
        today = now.astimezone(ZONE).date()
        calls = 0
        for back in reversed(range(HISTORY_DAYS)):
            day = HISTORY.draw(today - timedelta(days=back)).before(now)
            if not day.scenario.sessions:
                # Today's, drawn early in the day: nothing is over yet.
                continue
            builder = day.builder()
            self.write(
                builder,
                {run.project: projects[run.project] for run in builder.runs()},
            )
            calls += day.calls
        return calls

    def adopting(self, transcripts: list[Transcript]) -> dict[uuid.UUID, Project]:
        """The adopted Projects that adopted `transcripts`, by id."""
        adopted = {transcript.adopted_project_id for transcript in transcripts}
        return {
            project.id: project
            for project in self.db.scalars(
                select(Project).where(Project.id.in_(adopted - {None}))
            )
        }

    def _session(self, project: Project, run: SentRun) -> None:
        """The Session that ran the conversation, of `project`, over since
        its last Turn's end, with its Turns, its Work and Item or its Chat:
        written where Pilot holds none of the conversation, else the one it
        holds, as the run now has it. Its environment is written where
        Pilot has none, as a publication writes one the fleet stream has not
        given."""
        conversation_turn(self.db, run.conversation)
        if run.environment is not None:
            self.db.execute(
                pg_insert(Environment)
                .values(id=run.environment, name=run.environment, exempt=False)
                .on_conflict_do_nothing(index_elements=["id"])
            )
        session = self.db.scalars(
            select(AgentSession).where(AgentSession.conversation_id == run.conversation)
        ).one_or_none()
        if session is None:
            session = AgentSession(
                environment_id=run.environment,
                kind_code=run.kind,
                cwd=run.directory,
                conversation_id=run.conversation,
                token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                state_code=SessionState.ENDED,
            )
            self.db.add(session)
        started, ended = run.turns[0].sent_at, run.turns[-1].ended_at
        session.project_id = project.id
        session.turns = len(run.turns)
        session.started_at = started
        session.turn_started_at = run.turns[-1].sent_at
        session.turn_ended_at = session.ended_at = ended
        self.db.flush()
        held = {
            turn.seq: turn
            for turn in self.db.scalars(
                select(Turn).where(Turn.session_id == session.id)
            )
        }
        for seq, sent in enumerate(run.turns, start=1):
            turn = held.get(seq) or Turn(session_id=session.id, seq=seq)
            author = None if sent.author is None else self._person(sent.author)
            turn.message = sent.message
            turn.cause_code = TurnCause(sent.cause)
            turn.author_user_id = None if author is None else author.id
            turn.words = None if author is None else sent.message
            turn.started_at, turn.ended_at = sent.sent_at, sent.ended_at
            self.db.add(turn)
        if run.title is not None:
            self._work(project, session, run, started, ended)
        elif run.chat is not None:
            self._chat(project, session, run, ended)
        self.db.flush()

    def _work(
        self,
        project: Project,
        session: AgentSession,
        run: SentRun,
        started: datetime,
        ended: datetime,
    ) -> None:
        """The run's Work and its Item, created as the Session started and
        done at its end, placed where the record holds none."""
        item = self.db.get(Item, session.id)
        if item is None:
            assert run.title is not None
            self.record_service.place_work(
                project,
                session,
                run.title,
                trigger=None if run.trigger is None else WorkTrigger(run.trigger),
            )
            self.record_service.work_done(session.id, ended)
            item = self.db.get_one(Item, session.id)
        item.created_at = started
        item.done_at = ended

    def _chat(
        self, project: Project, session: AgentSession, run: SentRun, ended: datetime
    ) -> None:
        """The run's Chat, closed at its end, written where the record holds
        none."""
        chat = self.db.get(Chat, session.id)
        if chat is None:
            assert run.chat is not None
            chat = Chat(
                id=session.id,
                project_id=project.id,
                session_kind_code="chat",
                kind_code=ChatKind(run.chat),
                close_cause_code=CloseCause.FINISHED,
            )
            self.db.add(chat)
        chat.closed_at = ended

    def _person(self, handle: str) -> User:
        person = self.db.scalars(
            select(User).where(User.handle == handle, User.kind_code == UserKind.PERSON)
        ).one_or_none()
        if person is None:
            raise RecordNotFoundException("Person", handle)
        return person


def _on(scenario: Scenario, projects: Mapping[str, uuid.UUID]) -> Scenario:
    """The scenario as it is loaded on `projects`, its conversations' ids
    drawn from its name and theirs."""
    named = (str(projects[name]) for name in sorted(projects))
    return replace(scenario, name="/".join((scenario.name, *named)))


def _listed(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names) if names else "none"
