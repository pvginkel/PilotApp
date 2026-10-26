"""What a Session's headless create is handed (TD §4.2, §4.5; F50, F84; design
3 §12; DB decision 57, assertion 244), derived in one place from the Session's
columns, its kind and its Project, for every create of it alike: the start
loop's from the Session's rows and the relay's re-create of a gone controller
session. No column holds it."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.engine.paths import folder
from app.models import Project, SessionKind
from app.models import Session as AgentSession
from app.models.reference import Surface
from app.services.controller_client import HeadlessCreateRequest

STORE_REPO = "/work/PilotProjects"
"""The store repo's root: every brain session's cwd (design 3 §12)."""

PROJECTS = "/work/Projects"
"""The store's tree, `pilot-sync`'s root, a folder per project under it."""

PROJECT_VARIABLE = "PILOT_PROJECT"
"""The `env` entry naming a brain session's project folder, which `pilot.py`
reads (design 3 §12)."""


@dataclass(frozen=True)
class ScopedCreate:
    """A Session's headless create, and the surface Pilot's server hands it."""

    request: HeadlessCreateRequest
    surface: Surface
    """Its kind's: a work item's `pilot-work`, a chat's and a job's
    `pilot-store`, never both (F84)."""


def project_folder(project: Project) -> str:
    """The project's folder in the store, absolute."""
    return f"{PROJECTS}/{folder(project)}"


def scoped_create(db: Session, session: AgentSession) -> ScopedCreate:
    """The Session's create as its rows have it: its cwd, the conversation it
    resumes, its agent, model and effort, and its kind's surface. A brain
    session's, a chat's or a job's, is boxed (F50): its cwd read-only, its
    project's folder the one folder it writes, and that folder its
    `PILOT_PROJECT`."""
    surface = Surface(db.get_one(SessionKind, session.kind_code).surface)
    request = HeadlessCreateRequest(
        cwd=session.cwd,
        resume=session.conversation_id,
        agent=session.agent,
        model=session.model,
        reasoning_effort=session.reasoning_effort,
    )
    if surface is Surface.STORE:
        writable = project_folder(db.get_one(Project, session.project_id))
        request = request.model_copy(
            update={
                "sandbox_read_only_cwd": True,
                "sandbox_writable_dirs": [writable],
                "env": [f"{PROJECT_VARIABLE}={writable}"],
            }
        )
    return ScopedCreate(request, surface)
