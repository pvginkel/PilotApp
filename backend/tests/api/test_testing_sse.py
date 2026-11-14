"""/api/testing/sse/outage: the browser's stream taken down, for the specs of
a dropped connection (F149). While the outage holds, every stream connect
answers 503; with `silent`, the open streams send nothing either, heartbeat
included, until it ends."""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from flask import Flask
from flask.testing import FlaskClient

OUTAGE = "/api/testing/sse/outage"
HEARTBEAT = "event: heartbeat\ndata:\n\n"


@pytest.fixture(autouse=True)
def _no_outage(client: FlaskClient) -> Iterator[None]:
    """The outage is class-level state: none after each test."""
    yield
    assert client.delete(OUTAGE).status_code == 204


def _stream_url(request_id: str) -> str:
    return f"/api/sse/stream?request_id={request_id}"


@contextmanager
def _open(app: Flask, request_id: str) -> Iterator[Iterator[str]]:
    """An editor's stream, read a frame at a time; closing it is the browser going."""
    client = app.test_client()
    token = app.container.testing_service().create_session("outage-user", roles=["editor"])
    client.set_cookie("access_token", str(token))
    response = client.get(_stream_url(request_id), buffered=False)
    assert response.status_code == 200
    try:
        yield (chunk.decode() for chunk in response.response)
    finally:
        response.close()


class TestSseOutage:
    def test_a_connect_during_the_outage_answers_503(self, app: Flask, client: FlaskClient) -> None:
        assert client.post(OUTAGE).status_code == 204

        assert client.get(_stream_url("req-down")).status_code == 503

    def test_a_connect_after_the_outage_is_accepted(self, app: Flask, client: FlaskClient) -> None:
        assert client.post(OUTAGE).status_code == 204
        assert client.delete(OUTAGE).status_code == 204

        with _open(app, "req-up") as frames:
            assert next(frames).startswith("event: ready\n")

    def test_an_open_stream_speaks_through_an_outage_that_is_not_silent(self, app: Flask, client: FlaskClient) -> None:
        with _open(app, "req-speaks") as frames:
            next(frames)
            assert client.post(OUTAGE).status_code == 204

            assert next(frames) == HEARTBEAT

    def test_a_silent_outage_keeps_an_open_stream_from_sending_until_it_ends(
        self, app: Flask, client: FlaskClient
    ) -> None:
        beat = app.container.config().sse_heartbeat_interval
        with _open(app, "req-silent") as frames:
            next(frames)
            assert client.post(f"{OUTAGE}?silent=true").status_code == 204
            started = time.perf_counter()
            # Three beats of silence, then the outage ends from another client.
            ender = threading.Timer(3 * beat, lambda: app.test_client().delete(OUTAGE))
            ender.start()

            assert next(frames) == HEARTBEAT
            assert time.perf_counter() - started >= 3 * beat
            ender.join()

    def test_a_silent_outage_fails_connects_too(self, app: Flask, client: FlaskClient) -> None:
        assert client.post(f"{OUTAGE}?silent=true").status_code == 204

        assert client.get(_stream_url("req-silent-down")).status_code == 503

    def test_silent_must_be_a_boolean(self, client: FlaskClient) -> None:
        assert client.post(f"{OUTAGE}?silent=sometimes").status_code == 400

    def test_ending_with_no_outage_answers_204(self, client: FlaskClient) -> None:
        assert client.delete(OUTAGE).status_code == 204
