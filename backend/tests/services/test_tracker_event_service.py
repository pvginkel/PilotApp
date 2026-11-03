"""Card transitions from the tracker (F136): a delivery admitted under the
tracker's token and read by its adapter, the card waits it matches fired, and
each counted in Prometheus (F136.2)."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from dependency_injector import providers
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.datastructures import Headers

from app import models
from app.exceptions import (
    AuthenticationException,
    RecordNotFoundException,
    ValidationException,
)
from app.models import CardTransition, Project, WaitFiring
from app.models.reference import ProjectState
from app.services.container import ServiceContainer
from app.services.tracker_event_service import (
    FIRED_TOTAL,
    RECEIVED_TOTAL,
    REFUSED_TOTAL,
    YOUTRACK,
    TrackerEventService,
    YouTrackAdapter,
)
from app.services.wait_service import ReportedTransition
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.supervisor import metric_value
from tests.support.youtrack import TOKEN, youtrack_delivery


def _body(delivery: dict[str, Any]) -> bytes:
    return json.dumps(delivery).encode()


def _service(container: ServiceContainer, token: str = TOKEN) -> TrackerEventService:
    settings = container.app_config().model_copy(
        update={"youtrack_webhook_token": token}
    )
    container.app_config.override(providers.Object(settings))
    service: TrackerEventService = container.tracker_event_service()
    return service


def _counts() -> tuple[float, float, float, float]:
    return (
        metric_value(RECEIVED_TOTAL, tracker=YOUTRACK),
        metric_value(REFUSED_TOTAL, tracker=YOUTRACK, reason="token"),
        metric_value(REFUSED_TOTAL, tracker=YOUTRACK, reason="body"),
        metric_value(FIRED_TOTAL, tracker=YOUTRACK),
    )


def _moved(counts: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(now - then for now, then in zip(_counts(), counts, strict=True))


class TestYouTrackAdapter:
    def test_it_reads_the_state_change_by_the_apps_fields(self) -> None:
        read = YouTrackAdapter(TOKEN).read(_body(youtrack_delivery()))

        assert read == ReportedTransition(
            card="ANS-312",
            from_state="In Progress",
            to_state="Done",
            at=datetime(2026, 10, 24, 9, 10, tzinfo=UTC),
            by="pieter",
        )

    def test_a_state_left_empty_and_an_updater_unnamed_are_none(self) -> None:
        read = YouTrackAdapter(TOKEN).read(
            _body(youtrack_delivery(from_state=None, updatedBy=None))
        )

        assert read is not None
        assert (read.from_state, read.to_state, read.by) == (None, "Done", None)

    @pytest.mark.parametrize(
        "delivery",
        [
            youtrack_delivery(changedFields=[{"name": "Priority", "value": "Major"}]),
            youtrack_delivery(changedFields=[]),
            {"event": "issueUpdated", "id": "ANS-312"},
            youtrack_delivery(to_state=None),
            youtrack_delivery(event="issueCreated"),
        ],
        ids=[
            "another-field",
            "no-field",
            "no-changed-fields",
            "state-emptied",
            "another-event",
        ],
    )
    def test_a_delivery_with_no_state_entered_reports_none(
        self, delivery: dict[str, Any]
    ) -> None:
        assert YouTrackAdapter(TOKEN).read(_body(delivery)) is None

    @pytest.mark.parametrize(
        ("body", "fault"),
        [
            (b"not json", "Invalid JSON"),
            (b"[]", "Input should be an object"),
            (_body({"changedFields": []}), "its `event` is wrong: Field required"),
            (
                _body({k: v for k, v in youtrack_delivery().items() if k != "id"}),
                "its `id` is wrong: Field required",
            ),
            (
                _body(youtrack_delivery(updated="yesterday")),
                "its `updated` is wrong: Input should be a valid integer",
            ),
            (
                _body(youtrack_delivery(updated=-1)),
                "its `updated` is wrong: Input should be greater than or equal to 0",
            ),
            (
                _body(
                    youtrack_delivery(
                        changedFields=[{"name": "State", "value": "Done"}]
                    )
                ),
                "the State entry's `value` is no state",
            ),
            (
                _body(
                    youtrack_delivery(
                        changedFields=[
                            {
                                "name": "State",
                                "oldValue": [1],
                                "value": {"name": "Done"},
                            }
                        ]
                    )
                ),
                "the State entry's `oldValue` is no state",
            ),
        ],
        ids=[
            "no-json",
            "no-object",
            "no-event",
            "no-id",
            "updated-no-number",
            "updated-negative",
            "value-no-state",
            "old-value-no-state",
        ],
    )
    def test_a_delivery_it_cannot_read_is_refused(
        self, body: bytes, fault: str
    ) -> None:
        with pytest.raises(ValueError, match=f"^{fault}"):
            YouTrackAdapter(TOKEN).read(body)

    def test_it_admits_the_token_alone(self) -> None:
        adapter = YouTrackAdapter(TOKEN)

        assert adapter.admits(Headers({"X-YouTrack-Token": TOKEN}))
        assert adapter.admits(Headers({"x-youtrack-token": TOKEN}))
        assert not adapter.admits(Headers({"X-YouTrack-Token": TOKEN[:-1]}))
        assert not adapter.admits(Headers({"Authorization": f"Bearer {TOKEN}"}))
        assert not adapter.admits(Headers())

    def test_with_no_token_it_admits_nothing(self) -> None:
        assert not YouTrackAdapter("").admits(Headers({"X-YouTrack-Token": ""}))


class TestTrackerEventServiceAdmit:
    def test_a_delivery_with_the_token_is_counted_received(
        self, container: ServiceContainer
    ) -> None:
        counts = _counts()

        _service(container).admit(YOUTRACK, Headers({"X-YouTrack-Token": TOKEN}))

        assert _moved(counts) == (1, 0, 0, 0)

    @pytest.mark.parametrize(
        ("token", "header"),
        [(TOKEN, "a-wrong-token"), (TOKEN, None), ("", "")],
        ids=["wrong", "missing", "unset"],
    )
    def test_a_delivery_without_the_token_is_refused_and_counted(
        self, container: ServiceContainer, token: str, header: str | None
    ) -> None:
        counts = _counts()
        headers = Headers({} if header is None else {"X-YouTrack-Token": header})

        with pytest.raises(AuthenticationException) as refused:
            _service(container, token).admit(YOUTRACK, headers)

        assert refused.value.message == (
            "Cannot take the youtrack delivery because it does not carry the"
            " tracker's token"
        )
        assert _moved(counts) == (1, 1, 0, 0)

    def test_a_tracker_there_is_not_is_not_found_and_not_counted(
        self, container: ServiceContainer
    ) -> None:
        counts = _counts()

        with pytest.raises(RecordNotFoundException):
            _service(container).admit("jira", Headers({"X-YouTrack-Token": TOKEN}))

        assert _moved(counts) == (0, 0, 0, 0)
        assert metric_value(RECEIVED_TOTAL, tracker="jira") == 0


class TestTrackerEventServiceTake:
    def test_a_state_change_fires_the_card_waits_it_matches_and_counts_them(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = "camp"
        waits = container.wait_service()
        added = [
            waits.add_card_wait(
                project, project_session, title, ["ANS-312"], states, None
            )
            for title, states in (
                ("Slice 058 completes", ["Done"]),
                ("Slice 058 is dropped", ["Won't fix", "done"]),
            )
        ]
        clear_after_commit_callbacks()
        counts = _counts()

        fired = _service(container).take(YOUTRACK, _body(youtrack_delivery()))
        clear_after_commit_callbacks()

        assert fired == 2
        assert _moved(counts) == (0, 0, 0, 2)
        [transition] = session.scalars(select(CardTransition)).all()
        assert (transition.card, transition.to_state, transition.by) == (
            "ANS-312",
            "Done",
            "pieter",
        )
        assert sorted(
            session.scalars(select(WaitFiring.wait_id)).all(), key=str
        ) == sorted((each.id for each in added), key=str)

    @pytest.mark.parametrize(
        "delivery",
        [
            youtrack_delivery(changedFields=[{"name": "Priority", "value": "Major"}]),
            youtrack_delivery(card="ANS-313"),
        ],
        ids=["no-state-change", "no-wait-matches"],
    )
    def test_a_delivery_that_fires_nothing_is_dropped(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
        delivery: dict[str, Any],
    ) -> None:
        project.state_code = ProjectState.OPEN
        project.slug = "camp"
        container.wait_service().add_card_wait(
            project, project_session, "Slice 058 completes", ["ANS-312"], ["Done"], None
        )
        clear_after_commit_callbacks()
        counts = _counts()

        assert _service(container).take(YOUTRACK, _body(delivery)) == 0

        assert _moved(counts) == (0, 0, 0, 0)
        assert session.scalars(select(CardTransition)).all() == []

    def test_a_body_it_cannot_read_is_refused_and_counted(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        counts = _counts()

        with pytest.raises(ValidationException) as refused:
            _service(container).take(YOUTRACK, b"not json")

        assert refused.value.message.startswith(
            "Cannot read the youtrack delivery because Invalid JSON"
        )
        assert _moved(counts) == (0, 0, 1, 0)

    def test_a_tracker_there_is_not_is_not_found(
        self, container: ServiceContainer
    ) -> None:
        with pytest.raises(RecordNotFoundException):
            _service(container).take("jira", _body(youtrack_delivery()))
