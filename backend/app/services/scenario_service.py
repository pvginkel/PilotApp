"""The scenario's load (F122.2, F122.6): the invented scenario put into the
record as it stands now, its conversations through the service a collector's
publication writes through.

The scenario's package knows nothing of the record, so what Pilot holds of a
conversation before a collector reads its transcript is written here: for
each session a Turn of Pilot's ran, a Session of the project given for the
scenario's, over, whose `conversation_id` is the conversation's id and whose
one Turn is that Turn. It is written before the conversation is published,
so that the publication places the Launch the Turn started (DB 538).

The conversations' ids are the scenario's own, so a second load is a whole
publication of the same transcripts and replaces the first: the record holds
the scenario once, however often it is loaded.
"""

import hashlib
import uuid
from collections.abc import Mapping

from pilot_scenario import SCENARIO, Builder, SentTurn
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.exceptions import RecordNotFoundException, ValidationException
from app.models import Environment, Project, Transcript, Turn
from app.models import Session as AgentSession
from app.models.reference import SessionState
from app.schemas.publication import PublicationSchema
from app.services.launch_placement import conversation_turn
from app.services.publication_service import PublicationService


class ScenarioService:
    def __init__(self, db: Session, publication_service: PublicationService) -> None:
        self.db = db
        self.publication_service = publication_service

    def load(self, projects: Mapping[str, uuid.UUID]) -> list[Transcript]:
        """Load the scenario in the caller's transaction, its last moment
        now, and return its Transcripts: each session's main thread, then
        its sub-agents'. Where the record holds the scenario, it then holds
        it as this load has it: its times laid back from now, and its
        Sessions of Pilot's on the projects given.

        `projects` gives, for each of the scenario's projects a Turn of
        Pilot's is on, by the scenario's name of it, the Project that stands
        for it.

        Raises:
            ValidationException: `projects` names another set of the
                scenario's projects than those a Turn of Pilot's is on.
            RecordNotFoundException: no Project has an id given.
        """
        now = self.db.scalar(select(func.now()))
        assert now is not None
        builder = Builder(SCENARIO, now)
        turns = builder.turns()
        on = sorted({turn.project for turn in turns})
        if sorted(projects) != on:
            raise ValidationException(
                "Cannot load the scenario because `projects` gives a project for "
                f"{_listed(sorted(projects))}, and the scenario's Turns of Pilot's "
                f"are on {_listed(on)}"
            )
        standing: dict[str, Project] = {}
        for name, project_id in projects.items():
            project = self.db.get(Project, project_id)
            if project is None:
                raise RecordNotFoundException("Project", str(project_id))
            standing[name] = project
        for turn in turns:
            self._session(standing[turn.project], turn)
        return [
            self.publication_service.publish(
                PublicationSchema.model_validate(publication)
            )
            for publication in builder.publications()
        ]

    def _session(self, project: Project, turn: SentTurn) -> None:
        """The Session that ran the Turn's conversation, of `project`, over
        since the Turn's end, with that Turn its one: written where Pilot
        holds none of the conversation, else the one it holds, as the Turn
        now has it. Its environment is written where Pilot has none, as a
        publication writes one."""
        conversation_turn(self.db, turn.conversation)
        if turn.environment is not None:
            self.db.execute(
                pg_insert(Environment)
                .values(id=turn.environment, name=turn.environment, exempt=False)
                .on_conflict_do_nothing(index_elements=["id"])
            )
        session = self.db.scalars(
            select(AgentSession).where(
                AgentSession.conversation_id == turn.conversation
            )
        ).one_or_none()
        if session is None:
            session = AgentSession(
                environment_id=turn.environment,
                kind_code="work",
                cwd=turn.directory,
                conversation_id=turn.conversation,
                token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                state_code=SessionState.ENDED,
                turns=1,
            )
            sent = Turn(seq=1, message=turn.message)
            self.db.add(session)
        else:
            sent = self.db.scalars(
                select(Turn).where(Turn.session_id == session.id)
            ).one()
        session.project_id = project.id
        session.started_at = session.turn_started_at = turn.sent_at
        session.turn_ended_at = session.ended_at = turn.ended_at
        self.db.flush()
        sent.session_id = session.id
        sent.started_at, sent.ended_at = turn.sent_at, turn.ended_at
        self.db.add(sent)
        self.db.flush()


def _listed(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names) if names else "none"
