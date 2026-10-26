"""What a Session's headless create is handed (TD §4.5; F84; DB decision 57,
assertion 244), derived in one place from the Session's columns and its kind,
for every create of it alike: the start loop's from the Session's rows and the
relay's re-create of a gone controller session. No column holds it."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Session as AgentSession
from app.models import SessionKind
from app.models.reference import Surface
from app.services.controller_client import HeadlessCreateRequest


@dataclass(frozen=True)
class ScopedCreate:
    """A Session's headless create, and the surface Pilot's server hands it."""

    request: HeadlessCreateRequest
    surface: Surface
    """Its kind's: a work item's `pilot-work`, a chat's and a job's
    `pilot-store`, never both (F84)."""


def scoped_create(db: Session, session: AgentSession) -> ScopedCreate:
    """The Session's create as its rows have it: its cwd, the conversation it
    resumes, its agent, model and effort, and its kind's surface."""
    return ScopedCreate(
        HeadlessCreateRequest(
            cwd=session.cwd,
            resume=session.conversation_id,
            agent=session.agent,
            model=session.model,
            reasoning_effort=session.reasoning_effort,
        ),
        Surface(db.get_one(SessionKind, session.kind_code).surface),
    )
