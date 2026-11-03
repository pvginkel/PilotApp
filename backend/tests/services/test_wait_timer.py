"""The waits' timer (design 2 §8.2): its tick fires what is due. That it runs
from STARTUP with no controller is the container's wiring test."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.database import scoped_session
from app.models import Project, Wait, WaitFiring
from app.models.reference import FiringCause, ProjectState
from app.services.container import ServiceContainer
from app.services.wait_timer import WaitTimer
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.supervisor import Supervise


def _timer(container: ServiceContainer, supervise: Supervise) -> WaitTimer:
    supervisor, _ = supervise(container, controller_configured=False)
    return WaitTimer(container, supervisor)


def _timer_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.services.wait_timer"
    ]


class TestWaitTimer:
    def test_a_tick_fires_due_what_has_come_due(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        project: Project,
        project_session: models.Session,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = "camp"
        added = container.wait_service().add_timed_wait(
            project,
            project_session,
            "ESO refreshes",
            datetime.now(UTC) + timedelta(hours=1),
            None,
        )
        session.get_one(Wait, added.id).due_at = datetime.now(UTC) - timedelta(
            minutes=1
        )
        session.flush()
        clear_after_commit_callbacks()
        timer = _timer(container, supervise)

        with caplog.at_level(logging.INFO, "app.services.wait_timer"):
            with scoped_session(container) as db:
                timer.run(db)

        assert session.scalars(
            select(WaitFiring.cause_code).where(WaitFiring.wait_id == added.id)
        ).all() == [FiringCause.DUE]
        assert _timer_lines(caplog) == ["1 timed waits fired due"]

    def test_a_tick_with_nothing_due_fires_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        supervise: Supervise,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        timer = _timer(container, supervise)

        with caplog.at_level(logging.INFO, "app.services.wait_timer"):
            with scoped_session(container) as db:
                timer.run(db)

        assert session.scalars(select(WaitFiring)).all() == []
        assert _timer_lines(caplog) == []
