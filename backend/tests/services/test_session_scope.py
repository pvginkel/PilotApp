"""What a Session's headless create is handed, derived in one place from its
columns, its kind and its Project (TD §4.2, §4.5; F50, F84; design 3 §12; DB
decision 57, assertion 244; V13, V27)."""

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Project
from app.models.reference import ProjectState, SessionState, Surface
from app.services.controller_client import HeadlessCreateRequest
from app.services.session_scope import ScopedCreate, project_folder, scoped_create

COLUMNS = HeadlessCreateRequest(
    cwd="/work/Example",
    resume="conversation-1",
    agent="worker",
    model="model-1",
    reasoning_effort="high",
)
"""The create `_session`'s columns make."""


def _session(db: DbSession, project: Project, kind: str) -> models.Session:
    run = models.Session(
        project_id=project.id,
        kind_code=kind,
        cwd="/work/Example",
        conversation_id="conversation-1",
        agent="worker",
        model="model-1",
        reasoning_effort="high",
        token_hash="1" * 64,
        state_code=SessionState.STARTING,
    )
    db.add(run)
    db.flush()
    return run


class TestScopedCreate:
    def test_a_work_items_create_is_its_columns_and_pilot_work(
        self, session: DbSession, project: Project
    ) -> None:
        run = _session(session, project, "work")

        assert scoped_create(session, run) == ScopedCreate(COLUMNS, Surface.WORK)

    @pytest.mark.parametrize("kind", ["chat", "job"])
    def test_a_brain_sessions_create_is_boxed_to_its_projects_folder(
        self, session: DbSession, project: Project, kind: str
    ) -> None:
        project.state_code, project.slug = ProjectState.OPEN, "soup-club"
        run = _session(session, project, kind)

        assert scoped_create(session, run) == ScopedCreate(
            COLUMNS.model_copy(
                update={
                    "sandbox_read_only_cwd": True,
                    "sandbox_writable_dirs": ["/work/Projects/soup-club"],
                    "env": ["PILOT_PROJECT=/work/Projects/soup-club"],
                }
            ),
            Surface.STORE,
        )

    def test_a_drafts_brain_session_writes_its_drafts_folder(
        self, session: DbSession, project: Project
    ) -> None:
        run = _session(session, project, "chat")

        request = scoped_create(session, run).request

        folder = f"/work/Projects/draft-{project.number}"
        assert request.sandbox_writable_dirs == [folder]
        assert request.env == [f"PILOT_PROJECT={folder}"]


class TestProjectFolder:
    def test_it_is_the_folder_under_the_stores_tree(
        self, session: DbSession, project: Project
    ) -> None:
        assert project_folder(project) == f"/work/Projects/draft-{project.number}"
        project.slug = "soup-club"
        assert project_folder(project) == "/work/Projects/soup-club"
