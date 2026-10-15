"""The SSE Gateway connect callback admits only the identity the API serves.

A refused connect answers 401 (no or invalid token) or 403 (no `editor`) before
the connection is registered, so a refused stream never receives an event. The
gateway forwards the browser's headers in the callback payload, so the tests
put the token there, not in the test client's cookie jar.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.services.sse_connection_manager import SSEConnectionManager


def _connect_payload(
    request_id: str, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "action": "connect",
        "token": f"gw-{request_id}",
        "request": {
            "url": f"http://localhost:3502/api/sse/stream?request_id={request_id}",
            "headers": headers or {},
        },
    }


def _connect(
    client: FlaskClient, request_id: str, headers: dict[str, str] | None = None
) -> Any:
    return client.post("/api/sse/callback", json=_connect_payload(request_id, headers))


def _cookie(token: str) -> dict[str, str]:
    return {"cookie": f"theme=dark; access_token={token}"}


class _Callback:
    """The app under test, its connection manager and a spy on `on_connect`."""

    def __init__(self, app: Flask, client: FlaskClient, on_connect: MagicMock) -> None:
        self.app = app
        self.client = client
        self.on_connect = on_connect
        self.manager: SSEConnectionManager = app.container.sse_connection_manager()

    def connect(self, request_id: str, headers: dict[str, str] | None = None) -> Any:
        return _connect(self.client, request_id, headers)

    def session_token(self, roles: list[str], subject: str = "session-user") -> str:
        return str(
            self.app.container.testing_service().create_session(subject, roles=roles)
        )

    def subject_of(self, request_id: str) -> str | None:
        info = self.manager.get_connection_info(request_id)
        assert info is not None
        return info.subject

    def assert_refused(self, response: Any, status: int, request_id: str) -> None:
        assert response.status_code == status
        error = "Unauthorized" if status == 401 else "Forbidden"
        assert response.get_json() == {"error": error}
        self.on_connect.assert_not_called()
        assert not self.manager.has_connection(request_id)


def _callback(app: Flask) -> Generator[_Callback]:
    testing_service = app.container.testing_service()
    manager = app.container.sse_connection_manager()
    # The forced-error hook is class-level state: drain it around each test.
    testing_service.consume_forced_sse_callback_error()
    with patch.object(manager, "on_connect", wraps=manager.on_connect) as on_connect:
        yield _Callback(app, app.test_client(), on_connect)
    testing_service.consume_forced_sse_callback_error()


@pytest.fixture
def oidc(oidc_app: Flask) -> Generator[_Callback]:
    yield from _callback(oidc_app)


@pytest.fixture
def local(app: Flask) -> Generator[_Callback]:
    yield from _callback(app)


class TestWithOidc:
    def test_no_token_is_refused_401(self, oidc: _Callback) -> None:
        oidc.assert_refused(oidc.connect("req-none"), 401, "req-none")

    @pytest.mark.parametrize(
        "flaw", ["expired", "invalid_signature", "invalid_issuer", "invalid_audience"]
    )
    def test_invalid_token_is_refused_401(
        self, oidc: _Callback, generate_test_jwt: Any, flaw: str
    ) -> None:
        token = generate_test_jwt(roles=["editor"], **{flaw: True})

        oidc.assert_refused(oidc.connect("req-bad", _cookie(token)), 401, "req-bad")

    @pytest.mark.parametrize("roles", [[], ["admin"], ["reader"]])
    def test_token_without_editor_is_refused_403(
        self, oidc: _Callback, generate_test_jwt: Any, roles: list[str]
    ) -> None:
        token = generate_test_jwt(roles=roles)

        oidc.assert_refused(oidc.connect("req-role", _cookie(token)), 403, "req-role")

    @pytest.mark.parametrize("carrier", ["cookie", "bearer"])
    def test_editor_token_is_accepted_and_bound(
        self, oidc: _Callback, generate_test_jwt: Any, carrier: str
    ) -> None:
        token = generate_test_jwt(subject="editor-user", roles=["editor"])
        headers = (
            _cookie(token)
            if carrier == "cookie"
            else {"Authorization": f"Bearer {token}"}
        )

        response = oidc.connect("req-ok", headers)

        assert response.status_code == 200
        assert response.get_json() == {}
        oidc.on_connect.assert_called_once()
        assert oidc.subject_of("req-ok") == "editor-user"

    def test_test_session_without_editor_is_refused_403(self, oidc: _Callback) -> None:
        token = oidc.session_token(roles=["admin"])

        oidc.assert_refused(oidc.connect("req-ts", _cookie(token)), 403, "req-ts")

    def test_test_session_with_editor_is_accepted_and_bound(
        self, oidc: _Callback
    ) -> None:
        token = oidc.session_token(roles=["editor"], subject="session-editor")

        response = oidc.connect("req-ts-ok", _cookie(token))

        assert response.status_code == 200
        assert oidc.subject_of("req-ts-ok") == "session-editor"


class TestWithoutOidc:
    def test_no_session_is_accepted_as_local_user(self, local: _Callback) -> None:
        response = local.connect("req-local")

        assert response.status_code == 200
        assert response.get_json() == {}
        assert local.subject_of("req-local") == "local-user"

    def test_test_session_without_editor_is_refused_403(self, local: _Callback) -> None:
        token = local.session_token(roles=[])

        local.assert_refused(local.connect("req-ts", _cookie(token)), 403, "req-ts")

    def test_test_session_with_editor_is_accepted_and_bound(
        self, local: _Callback
    ) -> None:
        token = local.session_token(roles=["editor"], subject="session-editor")

        response = local.connect("req-ts-ok", _cookie(token))

        assert response.status_code == 200
        assert local.subject_of("req-ts-ok") == "session-editor"

    def test_unknown_session_token_is_accepted_as_local_user(
        self, local: _Callback
    ) -> None:
        response = local.connect("req-stale", _cookie("test-session-gone"))

        assert response.status_code == 200
        assert local.subject_of("req-stale") == "local-user"


class TestForcedRejectionHook:
    """The testing-only single-shot hook refuses the next connect, whoever it is."""

    @pytest.mark.parametrize("status", [401, 403])
    def test_armed_hook_refuses_an_editor(
        self, oidc: _Callback, generate_test_jwt: Any, status: int
    ) -> None:
        oidc.app.container.testing_service().set_forced_sse_callback_error(status)
        token = generate_test_jwt(roles=["editor"])

        oidc.assert_refused(
            oidc.connect("req-forced", _cookie(token)), status, "req-forced"
        )

    def test_hook_is_consumed_once(
        self, oidc: _Callback, generate_test_jwt: Any
    ) -> None:
        oidc.app.container.testing_service().set_forced_sse_callback_error(401)
        token = generate_test_jwt(subject="editor-user", roles=["editor"])

        assert oidc.connect("req-once-1", _cookie(token)).status_code == 401
        assert oidc.connect("req-once-2", _cookie(token)).status_code == 200
        assert oidc.subject_of("req-once-2") == "editor-user"

    def test_endpoint_arms_the_hook(self, local: _Callback) -> None:
        armed = local.client.post("/api/testing/sse/force-callback-error?status=403")
        assert armed.status_code == 204

        local.assert_refused(local.connect("req-armed"), 403, "req-armed")

    def test_endpoint_rejects_other_statuses(self, local: _Callback) -> None:
        armed = local.client.post("/api/testing/sse/force-callback-error?status=500")
        assert armed.status_code == 400

        assert local.connect("req-unarmed").status_code == 200


def test_disconnect_unregisters_the_connection(local: _Callback) -> None:
    assert local.connect("req-gone").status_code == 200

    response = local.client.post(
        "/api/sse/callback",
        json={
            "action": "disconnect",
            "reason": "client_closed",
            "token": "gw-req-gone",
            "request": _connect_payload("req-gone")["request"],
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {}
    assert not local.manager.has_connection("req-gone")
