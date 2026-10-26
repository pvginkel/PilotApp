"""What a Session's headless create is handed, derived in one place from its
columns and its kind (TD §4.5; F84; DB decision 57, assertion 244)."""

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Project
from app.models.reference import SessionState, Surface
from app.services.controller_client import HeadlessCreateRequest
from app.services.session_scope import ScopedCreate, scoped_create


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
    @pytest.mark.parametrize(
        ("kind", "surface"),
        [("work", Surface.WORK), ("chat", Surface.STORE), ("job", Surface.STORE)],
    )
    def test_the_create_is_the_sessions_columns_and_its_kinds_surface(
        self, session: DbSession, project: Project, kind: str, surface: Surface
    ) -> None:
        run = _session(session, project, kind)

        assert scoped_create(session, run) == ScopedCreate(
            HeadlessCreateRequest(
                cwd="/work/Example",
                resume="conversation-1",
                agent="worker",
                model="model-1",
                reasoning_effort="high",
            ),
            surface,
        )
