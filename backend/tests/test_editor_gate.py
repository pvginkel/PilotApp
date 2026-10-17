"""Pilot's one role: every call, reads included, requires the `editor` role.

The read and the write are the task endpoints on a task that runs until it is
cancelled, so a request the gate lets through answers 200 and one it refuses
answers 403 with the task untouched. A task answers only the subject that
started it, so the task runs under the caller's subject: what decides the
outcome is the caller's role, not the task's owner.

``/api/auth/self`` reads the access token from the cookie only, as the browser
sends it, never from an Authorization header, so the token tests send it there.
"""

import time
from collections.abc import Generator
from typing import Any

import jwt
import pytest
from flask import Flask
from flask.testing import FlaskClient
from pydantic import BaseModel
from werkzeug.test import TestResponse

from app.config import Settings
from app.schemas.task_schema import TaskStatus
from app.services.base_task import BaseTask, ProgressHandle

SUBJECT = "someone"


class _Result(BaseModel):
    cancelled: bool


class _RunsUntilCancelled(BaseTask):
    def execute(self, progress_handle: ProgressHandle, **kwargs: Any) -> BaseModel:
        self._cancelled.wait(timeout=30)
        return _Result(cancelled=self.is_cancelled)


def _running_task(app: Flask) -> Generator[str]:
    task = _RunsUntilCancelled()
    started = app.container.task_service().start_task(task, caller_subject=SUBJECT)
    try:
        yield started.task_id
    finally:
        # The app fixture's shutdown waits for running tasks.
        task.cancel()


@pytest.fixture
def task_id(app: Flask) -> Generator[str]:
    yield from _running_task(app)


@pytest.fixture
def oidc_task_id(oidc_app: Flask) -> Generator[str]:
    yield from _running_task(oidc_app)


def _read(client: FlaskClient, task_id: str, **kwargs: Any) -> TestResponse:
    return client.get(f"/api/tasks/{task_id}/status", **kwargs)


def _write(client: FlaskClient, task_id: str, **kwargs: Any) -> TestResponse:
    return client.post(f"/api/tasks/{task_id}/cancel", **kwargs)


def _task_status(app: Flask, task_id: str) -> TaskStatus:
    task_info = app.container.task_service().get_task_status(task_id)
    assert task_info is not None
    return task_info.status


class TestTestingSessions:
    """The suites' testing-auth sessions carry the roles their test gives them."""

    def _sign_in(self, client: FlaskClient, roles: list[str]) -> None:
        response = client.post(
            "/api/testing/auth/session", json={"subject": SUBJECT, "roles": roles}
        )
        assert response.status_code == 201

    @pytest.mark.parametrize("roles", [[], ["admin"], ["reader"]])
    def test_session_without_editor_is_refused(
        self, app: Flask, client: FlaskClient, task_id: str, roles: list[str]
    ) -> None:
        self._sign_in(client, roles)

        assert _read(client, task_id).status_code == 403
        assert _write(client, task_id).status_code == 403
        assert _task_status(app, task_id) != TaskStatus.CANCELLED
        assert client.get("/api/auth/self").status_code == 403

    def test_session_with_editor_is_served(
        self, app: Flask, client: FlaskClient, task_id: str
    ) -> None:
        self._sign_in(client, ["editor"])

        read = _read(client, task_id)
        assert read.status_code == 200
        assert read.get_json()["task_id"] == task_id

        assert _write(client, task_id).status_code == 200
        assert _task_status(app, task_id) == TaskStatus.CANCELLED

        me = client.get("/api/auth/self")
        assert me.status_code == 200
        assert me.get_json()["roles"] == ["editor"]


class TestOidcTokens:
    """A real token's role is the client role of the app's own audience."""

    @pytest.fixture
    def token(self, test_settings: Settings, generate_test_jwt: Any) -> Any:
        def _token(claims: dict[str, Any]) -> str:
            now = int(time.time())
            payload = {
                "sub": SUBJECT,
                "iss": test_settings.oidc_issuer_url,
                "aud": test_settings.oidc_audience,
                "iat": now,
                "exp": now + 3600,
                **claims,
            }
            return jwt.encode(
                payload,
                generate_test_jwt.private_key,
                algorithm="RS256",
                headers={"kid": "test-key-id"},
            )

        return _token

    @staticmethod
    def _bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _self(client: FlaskClient, token: str, settings: Settings) -> TestResponse:
        client.set_cookie(settings.oidc_cookie_name, token)
        return client.get("/api/auth/self")

    @pytest.mark.parametrize(
        "claims",
        [
            pytest.param({}, id="no-roles"),
            pytest.param(
                {"resource_access": {"test-backend": {"roles": []}}},
                id="no-client-role",
            ),
            pytest.param(
                {"resource_access": {"another-client": {"roles": ["editor"]}}},
                id="another-clients-editor",
            ),
            pytest.param({"realm_access": {"roles": ["admin"]}}, id="realm-admin"),
        ],
    )
    def test_token_without_editor_is_refused(
        self,
        oidc_app: Flask,
        oidc_client: FlaskClient,
        oidc_task_id: str,
        token: Any,
        test_settings: Settings,
        claims: dict[str, Any],
    ) -> None:
        jwt_token = token(claims)
        headers = self._bearer(jwt_token)

        assert _read(oidc_client, oidc_task_id, headers=headers).status_code == 403
        assert _write(oidc_client, oidc_task_id, headers=headers).status_code == 403
        assert _task_status(oidc_app, oidc_task_id) != TaskStatus.CANCELLED
        assert self._self(oidc_client, jwt_token, test_settings).status_code == 403

    def test_token_with_the_clients_editor_role_is_served(
        self,
        oidc_app: Flask,
        oidc_client: FlaskClient,
        oidc_task_id: str,
        token: Any,
        test_settings: Settings,
    ) -> None:
        jwt_token = token(
            {"resource_access": {test_settings.oidc_audience: {"roles": ["editor"]}}}
        )
        headers = self._bearer(jwt_token)

        assert _read(oidc_client, oidc_task_id, headers=headers).status_code == 200
        assert _write(oidc_client, oidc_task_id, headers=headers).status_code == 200
        assert _task_status(oidc_app, oidc_task_id) == TaskStatus.CANCELLED

        me = self._self(oidc_client, jwt_token, test_settings)
        assert me.status_code == 200
        assert me.get_json()["roles"] == ["editor"]

    def test_no_token_is_unauthenticated(
        self, oidc_client: FlaskClient, oidc_task_id: str
    ) -> None:
        assert _read(oidc_client, oidc_task_id).status_code == 401
        assert oidc_client.get("/api/auth/self").status_code == 401


def test_without_oidc_every_call_is_served(
    app: Flask, client: FlaskClient, task_id: str
) -> None:
    """The dev stack runs with OIDC off and no session: nothing is gated."""
    assert _read(client, task_id).status_code == 200
    assert _write(client, task_id).status_code == 200
    assert client.get("/api/auth/self").status_code == 200
