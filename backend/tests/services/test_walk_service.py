"""The collector's walks as Pilot keeps them (F152.14, F154.8): a walk's
end stamped, the one event of a walk that wrote a row, read off test
connections' queues, and the readiness check `collector`."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from queue import Empty
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import User, Walk
from app.models.reference import UserKind
from app.services.container import ServiceContainer
from app.services.health_service import CheckResult, CheckStatus, HealthService
from app.services.sse_connection_manager import SSEConnection, SSEConnectionManager
from app.services.walk_service import (
    COLLECTOR_CHECK,
    EVENT_NAME,
    WALKS_KEPT,
    WalkService,
    collector_readiness,
    latest_walk_end,
    register_collector_check,
)
from app.utils.after_commit import (
    clear_after_commit_callbacks,
    run_after_commit_callbacks,
)
from tests.support.publications import whole
from tests.support.transcripts import OTHER


@pytest.fixture
def manager(container: ServiceContainer) -> SSEConnectionManager:
    return container.sse_connection_manager()


@pytest.fixture
def walks(container: ServiceContainer) -> Iterator[WalkService]:
    clear_after_commit_callbacks()
    yield container.walk_service()
    clear_after_commit_callbacks()


@pytest.fixture
def ada(manager: SSEConnectionManager, person: User) -> Iterator[SSEConnection]:
    """A connection of the person's."""
    connection = manager.on_connect("ada-1", person.subject)
    yield connection
    manager.on_disconnect(connection)


def _commit() -> None:
    """What the transaction's commit runs: its after-commit callbacks."""
    run_after_commit_callbacks()
    clear_after_commit_callbacks()


def _frames(connection: SSEConnection) -> list[dict[str, Any]]:
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        queued.append(json.loads(frame.removeprefix("data: ")))


def _publish(container: ServiceContainer, **overrides: Any) -> None:
    """A publication of a transcript, taken as a collector's is."""
    container.publication_service().publish(whole(**overrides))


def _walked(session: DbSession, ago: timedelta) -> datetime:
    """A Walk that ended `ago`."""
    ended_at = datetime.now(UTC) - ago
    session.add(Walk(ended_at=ended_at))
    session.flush()
    return ended_at


class TestEnd:
    def test_a_walks_end_is_stamped_now(
        self, walks: WalkService, session: DbSession
    ) -> None:
        before = datetime.now(UTC)

        ended = walks.end()

        assert before <= ended.ended_at <= datetime.now(UTC)
        assert session.scalars(select(Walk.ended_at)).all() == [ended.ended_at]

    def test_a_walk_that_wrote_nothing_raises_no_event(
        self, walks: WalkService, session: DbSession, ada: SSEConnection
    ) -> None:
        """F152.14: "a walk that wrote nothing raises none"."""
        ended = walks.end()
        _commit()

        assert ended.announced is False
        assert _frames(ada) == []
        assert session.scalar(select(func.count()).select_from(Walk)) == 1

    def test_a_walk_that_published_a_transcript_raises_one_event_at_its_commit(
        self, walks: WalkService, container: ServiceContainer, ada: SSEConnection
    ) -> None:
        walks.end()
        _commit()
        _publish(container)

        ended = walks.end()

        assert ended.announced is True
        assert _frames(ada) == []
        _commit()
        assert _frames(ada) == [
            {
                "type": EVENT_NAME,
                "payload": {"as_of": ended.ended_at.isoformat().replace("+00:00", "Z")},
            }
        ]

    def test_the_event_is_named_collection_changed(self) -> None:
        """What the screen listens for: slice 054 redraws on it."""
        assert EVENT_NAME == "collection_changed"

    def test_a_walk_raises_one_event_whatever_it_published(
        self, walks: WalkService, container: ServiceContainer, ada: SSEConnection
    ) -> None:
        """F154.8, one per walk and not per call."""
        _publish(container)
        _publish(container, session_id=OTHER)

        walks.end()
        _commit()

        assert len(_frames(ada)) == 1

    def test_the_first_walk_of_a_record_that_holds_a_transcript_raises_it(
        self, walks: WalkService, container: ServiceContainer, ada: SSEConnection
    ) -> None:
        """No walk ended before it: what the record holds was collected
        since."""
        _publish(container)

        assert walks.end().announced is True

    def test_the_walk_after_one_that_published_raises_none(
        self, walks: WalkService, container: ServiceContainer, ada: SSEConnection
    ) -> None:
        _publish(container)
        walks.end()
        _commit()
        _frames(ada)

        ended = walks.end()
        _commit()

        assert ended.announced is False
        assert _frames(ada) == []

    def test_a_publication_that_changed_its_transcripts_row_alone_counts(
        self, walks: WalkService, container: ServiceContainer, ada: SSEConnection
    ) -> None:
        """Every publication Pilot takes writes its Transcript's row."""
        _publish(container)
        walks.end()
        _commit()
        _frames(ada)
        _publish(container)

        assert walks.end().announced is True

    def test_every_persons_connections_hear_it_and_no_service_users(
        self,
        walks: WalkService,
        container: ServiceContainer,
        manager: SSEConnectionManager,
        session: DbSession,
        ada: SSEConnection,
        service_user: User,
    ) -> None:
        bea = User(
            kind_code=UserKind.PERSON,
            subject="subject-bea",
            handle="bea",
            name="Bea Example",
            avatar_slot=2,
        )
        session.add(bea)
        session.flush()
        assert service_user.subject is not None
        others = [
            manager.on_connect("ada-2", ada.subject),
            manager.on_connect("bea-1", bea.subject),
            manager.on_connect("fleet-1", service_user.subject),
        ]
        try:
            _publish(container)

            walks.end()
            _commit()

            assert [len(_frames(connection)) for connection in (ada, *others)] == [
                1,
                1,
                1,
                0,
            ]
        finally:
            for connection in others:
                manager.on_disconnect(connection)

    def test_the_latest_walks_are_kept_and_no_more(
        self, walks: WalkService, session: DbSession
    ) -> None:
        """DB decision 79.19: nothing reads a Walk before the latest."""
        old = [_walked(session, timedelta(minutes=minute)) for minute in (3, 2, 1)]
        ends = [walks.end().ended_at for _ in range(WALKS_KEPT - 1)]

        kept = session.scalars(select(Walk.ended_at).order_by(Walk.ended_at)).all()

        assert kept == [old[2], *ends]


class TestLatestWalkEnd:
    def test_none_before_a_first_walk(self, session: DbSession) -> None:
        assert latest_walk_end(session) is None

    def test_the_latest_of_the_walks_kept(self, session: DbSession) -> None:
        _walked(session, timedelta(seconds=30))
        latest = _walked(session, timedelta(seconds=1))
        _walked(session, timedelta(seconds=60))

        assert latest_walk_end(session) == latest


def _configure(
    container: ServiceContainer, *, token: str | None = None, interval: float = 30.0
) -> None:
    """The app settings with that bearer and walk's interval, for this test."""
    update: dict[str, Any] = {"collector_walk_interval_seconds": interval}
    if token is not None:
        update["collector_token"] = token
    settings = container.app_config().model_copy(update=update)
    container.app_config.override(providers.Object(settings))


class TestCollectorReadiness:
    def test_disabled_while_the_collectors_token_is_empty(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        _configure(container, token="")
        _walked(session, timedelta(seconds=1))

        assert collector_readiness(container) == CheckResult(
            CheckStatus.DISABLED, "COLLECTOR_TOKEN is empty"
        )

    def test_an_error_before_a_first_walk(self, container: ServiceContainer) -> None:
        _configure(container)

        assert collector_readiness(container) == CheckResult(
            CheckStatus.ERROR, "no walk of the collector's has ended"
        )

    def test_ok_naming_the_latest_walks_end(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        _configure(container)
        _walked(session, timedelta(seconds=58))
        latest = _walked(session, timedelta(seconds=31))

        assert collector_readiness(container) == CheckResult(
            CheckStatus.OK,
            f"the collector's latest walk ended at {latest.isoformat()}",
        )

    def test_an_error_once_the_latest_walk_is_older_than_two_intervals(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        _configure(container)
        latest = _walked(session, timedelta(seconds=61))

        assert collector_readiness(container) == CheckResult(
            CheckStatus.ERROR,
            f"the collector's latest walk ended at {latest.isoformat()}, more"
            " than 60 s before this check",
        )

    def test_the_interval_is_the_servers_setting(
        self, container: ServiceContainer, session: DbSession
    ) -> None:
        """`COLLECTOR_WALK_INTERVAL_SECONDS`, which the inventory hands the
        collector."""
        _configure(container, interval=300)
        _walked(session, timedelta(seconds=590))

        assert collector_readiness(container).status is CheckStatus.OK

        _configure(container, interval=10)

        assert collector_readiness(container).status is CheckStatus.ERROR

    def test_readyz_names_it_and_a_failing_one_leaves_the_backend_ready(
        self, app: Flask, container: ServiceContainer
    ) -> None:
        """Not critical (READY-2): a 503 takes the backend out of the Service
        the collector's own calls come through."""
        _configure(container)
        health = HealthService(container.lifecycle_coordinator(), container.config())
        container.health_service.override(providers.Object(health))
        try:
            register_collector_check(container)

            with app.app_context():
                body, status = health.check_readyz()
        finally:
            container.health_service.reset_last_overriding()

        assert status == 200
        assert (body["ready"], body["status"]) == (True, "degraded")
        assert body["checks"] == {
            COLLECTOR_CHECK: {
                "status": "error",
                "critical": False,
                "detail": "no walk of the collector's has ended",
            }
        }
