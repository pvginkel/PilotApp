"""`POST /api/tracker-events/<tracker>` (F136.1): YouTrack's deliveries under
its webhook token, outside the sign-in gate, answered with how many card
waits fired."""

import json
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.bus import EngineEvent, ProjectChanged
from app.models import CardTransition, Item, Project, WaitFiring
from app.models.reference import FiringCause, ProjectState
from app.services.container import ServiceContainer
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.youtrack import TOKEN, youtrack_delivery

URL = "/api/tracker-events/youtrack"


def _configure(container: ServiceContainer, token: str = TOKEN) -> None:
    settings = container.app_config().model_copy(
        update={"youtrack_webhook_token": token}
    )
    container.app_config.override(providers.Object(settings))


def _post(
    client: FlaskClient,
    delivery: dict[str, Any] | bytes,
    token: str | None = TOKEN,
    url: str = URL,
) -> Any:
    body = delivery if isinstance(delivery, bytes) else json.dumps(delivery).encode()
    headers = {} if token is None else {"X-YouTrack-Token": token}
    return client.post(url, data=body, headers=headers, content_type="application/json")


@pytest.fixture
def card_wait(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
) -> Item:
    """An open project's card wait on `ANS-312` entering Done."""
    project.state_code = ProjectState.OPEN
    project.slug = "camp"
    added = container.wait_service().add_card_wait(
        project, project_session, "Slice 058 completes", ["ANS-312"], ["Done"], None
    )
    clear_after_commit_callbacks()
    return added


class TestPostTrackerEvent:
    def test_a_state_change_a_card_wait_watches_fires_it(
        self,
        session: DbSession,
        client: FlaskClient,
        container: ServiceContainer,
        engine_events: list[EngineEvent],
        card_wait: Item,
    ) -> None:
        _configure(container)

        response = _post(client, youtrack_delivery(to_state="DONE"))

        assert response.status_code == 200
        assert response.get_json() == {"fired": 1}
        [firing] = session.scalars(select(WaitFiring)).all()
        assert (firing.wait_id, firing.cause_code) == (
            card_wait.id,
            FiringCause.TRANSITION,
        )
        assert ProjectChanged(card_wait.project_id) in engine_events

    @pytest.mark.parametrize(
        "delivery",
        [
            youtrack_delivery(changedFields=[{"name": "Priority", "value": "Major"}]),
            youtrack_delivery(to_state="In Review"),
            youtrack_delivery(card="SR-1"),
        ],
        ids=["no-state-change", "a-state-not-watched", "a-card-not-watched"],
    )
    def test_a_delivery_that_fires_nothing_is_answered_and_dropped(
        self,
        session: DbSession,
        client: FlaskClient,
        container: ServiceContainer,
        card_wait: Item,
        delivery: dict[str, Any],
    ) -> None:
        _configure(container)

        response = _post(client, delivery)

        assert response.status_code == 200
        assert response.get_json() == {"fired": 0}
        assert session.scalars(select(CardTransition)).all() == []

    @pytest.mark.parametrize(
        ("setting", "header"),
        [(TOKEN, "a-wrong-token"), (TOKEN, None), ("", "")],
        ids=["wrong", "missing", "unset"],
    )
    def test_a_delivery_without_the_token_is_refused(
        self,
        session: DbSession,
        client: FlaskClient,
        container: ServiceContainer,
        card_wait: Item,
        setting: str,
        header: str | None,
    ) -> None:
        _configure(container, setting)

        response = _post(client, youtrack_delivery(), token=header)

        assert response.status_code == 401
        assert response.get_json()["error"] == (
            "Cannot take the youtrack delivery because it does not carry the"
            " tracker's token"
        )
        assert session.scalars(select(WaitFiring)).all() == []

    def test_a_body_the_adapter_cannot_read_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        _configure(container)

        response = _post(
            client,
            b'{"event": "issueUpdated", "changedFields": [{"name": "State", "value": {"name": "Done"}}]}',
        )

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "Cannot read the youtrack delivery because its `id` is wrong:"
            " Field required"
        )

    def test_a_tracker_there_is_not_is_not_found(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        _configure(container)

        response = _post(client, youtrack_delivery(), url="/api/tracker-events/jira")

        assert response.status_code == 404

    def test_the_endpoint_is_outside_the_oidc_gate(
        self, oidc_app: Flask, oidc_client: FlaskClient
    ) -> None:
        assert oidc_app.container.config().oidc_enabled
        _configure(oidc_app.container)

        response = _post(oidc_client, youtrack_delivery())

        assert response.status_code == 200
        assert response.get_json() == {"fired": 0}
