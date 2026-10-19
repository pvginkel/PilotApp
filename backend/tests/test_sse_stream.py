"""The browser's SSE stream, GET /api/sse/stream, admits only Pilot's `editor`.

The stream itself (401 for a missing or invalid token, the request id, the
testing hook, heartbeats, disconnects, the local admin) is the template's and
tested there. These are Pilot's role cases: the app reads and writes as
`editor` alone, so a caller without it is refused 403 before the connection is
registered, and a refused stream never receives an event. Every answer is a
`200` stream: an accepted one starts with `ready`, a refused one carries one
`rejected` event and ends. The token is the access-token cookie, as an
`EventSource` sends it, and Flask's test client reads the stream a frame at a
time (`buffered=False`).
"""

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.services.sse_connection_manager import SSEConnectionManager

READY = "event: ready\ndata:\n\n"
REJECTED_403 = 'event: rejected\ndata: {"status":403,"message":"FORBIDDEN"}\n\n'


class _Streams:
    """The app under test, its connection manager and a spy on `on_connect`."""

    def __init__(self, app: Flask, on_connect: MagicMock) -> None:
        self.app = app
        self.client = app.test_client()
        self.on_connect = on_connect
        self.manager: SSEConnectionManager = app.container.sse_connection_manager()

    @contextmanager
    def open(self, request_id: str, token: str) -> Iterator[Iterator[str]]:
        """Open a stream as the token; closing it on exit is the browser going."""
        self.client.set_cookie("theme", "dark")
        self.client.set_cookie("access_token", token)
        response = self.client.get(
            f"/api/sse/stream?request_id={request_id}", buffered=False
        )
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        try:
            yield (chunk.decode() for chunk in response.response)
        finally:
            response.close()

    def session_token(self, roles: list[str], subject: str = "session-user") -> str:
        return str(
            self.app.container.testing_service().create_session(subject, roles=roles)
        )

    def subject_of(self, request_id: str, token: str) -> str | None:
        """Connect as the token: the subject the connection is bound to."""
        with self.open(request_id, token) as frames:
            assert next(frames) == READY
            info = self.manager.get_connection_info(request_id)
            assert info is not None
            return info.subject

    def assert_refused(self, request_id: str, token: str) -> None:
        """Refused 403 in-stream, and never registered."""
        with self.open(request_id, token) as frames:
            assert next(frames) == REJECTED_403
            assert next(frames, None) is None
        self.on_connect.assert_not_called()
        assert not self.manager.has_connection(request_id)


def _streams(app: Flask) -> Generator[_Streams]:
    testing_service = app.container.testing_service()
    manager = app.container.sse_connection_manager()
    # The forced-error hook is class-level state: drain it around each test.
    testing_service.consume_forced_sse_connect_error()
    with patch.object(manager, "on_connect", wraps=manager.on_connect) as on_connect:
        yield _Streams(app, on_connect)
    testing_service.consume_forced_sse_connect_error()


@pytest.fixture
def oidc(oidc_app: Flask) -> Generator[_Streams]:
    yield from _streams(oidc_app)


@pytest.fixture
def local(app: Flask) -> Generator[_Streams]:
    yield from _streams(app)


class TestWithOidc:
    @pytest.mark.parametrize("roles", [[], ["admin"], ["reader"]])
    def test_token_without_editor_is_refused_403(
        self, oidc: _Streams, generate_test_jwt: Any, roles: list[str]
    ) -> None:
        oidc.assert_refused("req-role", generate_test_jwt(roles=roles))

    def test_editor_token_is_accepted_and_bound(
        self, oidc: _Streams, generate_test_jwt: Any
    ) -> None:
        token = generate_test_jwt(subject="editor-user", roles=["editor"])

        assert oidc.subject_of("req-ok", token) == "editor-user"
        oidc.on_connect.assert_called_once()

    def test_test_session_without_editor_is_refused_403(self, oidc: _Streams) -> None:
        oidc.assert_refused("req-ts", oidc.session_token(roles=["admin"]))

    def test_test_session_with_editor_is_accepted_and_bound(
        self, oidc: _Streams
    ) -> None:
        token = oidc.session_token(roles=["editor"], subject="session-editor")

        assert oidc.subject_of("req-ts-ok", token) == "session-editor"


class TestWithoutOidc:
    def test_test_session_without_editor_is_refused_403(self, local: _Streams) -> None:
        local.assert_refused("req-ts", local.session_token(roles=["admin"]))

    def test_test_session_with_editor_is_accepted_and_bound(
        self, local: _Streams
    ) -> None:
        token = local.session_token(roles=["editor"], subject="session-editor")

        assert local.subject_of("req-ts-ok", token) == "session-editor"
