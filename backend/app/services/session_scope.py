"""What a Session's headless create is handed (TD §4.2, §4.5; F50, F84, F5.5;
design 3 §12; DB decision 57, assertion 244), derived in one place from the
Session's columns, its kind, its job's trigger and its Project, for every
create of it alike: the start loop's from the Session's rows and the relay's
re-create of a gone controller session. No column holds it: a Chat closes when
its Project finishes or reopens, so the Project's state at a create is the
state its chat was opened under."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.engine.paths import folder
from app.models import Project, SessionKind, Work
from app.models import Session as AgentSession
from app.models.reference import ProjectState, Surface, WorkTrigger
from app.services.controller_client import HeadlessCreateRequest
from app.services.start_gate import JOB_KIND

STORE_REPO = "/work/PilotProjects"
"""The store repo's root: every brain session's cwd (design 3 §12)."""

PROJECTS = "/work/Projects"
"""The store's tree, `pilot-sync`'s root, a folder per project under it."""

PROJECT_VARIABLE = "PILOT_PROJECT"
"""The `env` entry naming a brain session's project folder, which `pilot.py`
reads (design 3 §12)."""

SESSION_VARIABLE = "PILOT_SESSION"
"""The `env` entry naming a brain session's Session, which the store's hooks
take the write lock of its project folder with, so that its saves are
credited to it."""

PROMPT_CACHE_VARIABLE = "CLAUDE_CODE_PROMPT_CACHE_TTL"
"""The `env` entry Claude Code takes its main conversation's prompt cache TTL
from, `5m` or `1h`; unset, the hour of a Claude subscription within its usage
limits."""

FIVE_MINUTE_JOBS = frozenset(
    {WorkTrigger.SETUP, WorkTrigger.WORKER_TURN_ENDED, WorkTrigger.ITEM_DONE}
)
"""The triggers of the jobs whose sessions run on the 5-minute prompt cache. A
wait's run, a chat and a work item's run leave Claude Code's own."""


@dataclass(frozen=True)
class ScopedCreate:
    """A Session's headless create, and the surface Pilot's server hands it."""

    request: HeadlessCreateRequest
    surface: Surface | None
    """Its kind's: a work item's `pilot-work`, a chat's and a job's
    `pilot-store`, never both (F84); none for a brain session of a finished
    project, which reads only (F5.5)."""


def project_folder(project: Project) -> str:
    """The project's folder in the store, absolute."""
    return f"{PROJECTS}/{folder(project)}"


def scoped_create(db: Session, session: AgentSession) -> ScopedCreate:
    """The Session's create as its rows have it: its cwd, the conversation it
    resumes, its agent, model and effort, and its kind's surface. A brain
    session's, a chat's or a job's, is boxed (F50), its cwd read-only, its
    project's folder its `PILOT_PROJECT` and its own id its `PILOT_SESSION`:
    that folder the one it writes, or, while its Project is finished, none,
    with no surface (F5.5). A job of a trigger of `FIVE_MINUTE_JOBS` runs on
    the 5-minute prompt cache."""
    surface = Surface(db.get_one(SessionKind, session.kind_code).surface)
    request = HeadlessCreateRequest(
        cwd=session.cwd,
        resume=session.conversation_id,
        agent=session.agent,
        model=session.model,
        reasoning_effort=session.reasoning_effort,
    )
    if surface is not Surface.STORE:
        return ScopedCreate(request, surface)
    project = db.get_one(Project, session.project_id, populate_existing=True)
    env = [
        f"{PROJECT_VARIABLE}={project_folder(project)}",
        f"{SESSION_VARIABLE}={session.id}",
    ]
    if (
        session.kind_code == JOB_KIND
        and db.get_one(Work, session.id).trigger_code in FIVE_MINUTE_JOBS
    ):
        env.append(f"{PROMPT_CACHE_VARIABLE}=5m")
    box = {"sandbox_read_only_cwd": True, "env": env}
    if project.state_code is ProjectState.FINISHED:
        return ScopedCreate(request.model_copy(update=box), None)
    box["sandbox_writable_dirs"] = [project_folder(project)]
    return ScopedCreate(request.model_copy(update=box), surface)
