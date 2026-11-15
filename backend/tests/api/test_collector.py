"""The collector's routes (F152.3): `POST /api/collector/publications` under
the collector's bearer, outside the sign-in gate, each answer pinned beside
the protocol's version."""

import logging
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.test import TestResponse

from app.models import Call, ToolCall, Transcript
from app.schemas.publication import PublicationSchema
from app.services.container import ServiceContainer
from app.services.publication_service import (
    COLLECTOR_PROTOCOL_MAX,
    COLLECTOR_PROTOCOL_MIN,
)
from tests.support.database import writes
from tests.support.publications import (
    COLLECTOR_TOKEN,
    call,
    collector_headers,
    launch,
    prompt,
    sub_agent,
    tool_call,
    whole,
)
from tests.support.transcripts import CAMP, SUB_AGENT

URL = "/api/collector/publications"
LOGGER = "app.services.publication_service"


def _configure(container: ServiceContainer, token: str) -> None:
    """The app settings with `token` as the collector's bearer, for this
    test."""
    settings = container.app_config().model_copy(update={"collector_token": token})
    container.app_config.override(providers.Object(settings))


def _body(publication: PublicationSchema) -> dict[str, Any]:
    return publication.model_dump(mode="json")


def _camp(calls: int = 2) -> PublicationSchema:
    """The main thread's publication: a Launch with its Prompt, and `calls`
    Calls on one chain, the first with a Tool Call."""
    return whole(
        launches=[launch(prompts=[prompt()])],
        calls=[
            call(1, prompt=1, tool_calls=[tool_call(1)]),
            *(
                call(place, predecessor=f"msg_{place - 1:04}")
                for place in range(2, calls + 1)
            ),
        ],
    )


def _post(
    client: FlaskClient,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> TestResponse:
    return client.post(
        URL, json=body, headers=collector_headers() if headers is None else headers
    )


def _held(session: DbSession) -> dict[str, list[int]]:
    """The id of every Transcript, Call and Tool Call Pilot holds, by table."""
    return {
        entity.__tablename__: list(
            session.scalars(select(entity.id).order_by(entity.id))
        )
        for entity in (Transcript, Call, ToolCall)
    }


class TestCollectorProtocolVersion:
    def test_the_shapes_pinned_here_are_the_accepted_range(self) -> None:
        # A change to a shape these tests or `tests/schemas/test_publication.py`
        # pin bumps COLLECTOR_PROTOCOL_MAX and the collector's own version in
        # one commit, and COLLECTOR_PROTOCOL_MIN with it when the server
        # cannot serve the old collector.
        assert (COLLECTOR_PROTOCOL_MIN, COLLECTOR_PROTOCOL_MAX) == (1, 1)


class TestCollectorGate:
    """The gate every call of a collector's passes."""

    def test_a_call_without_the_bearer_is_401(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        headers = collector_headers()
        del headers["Authorization"]

        with writes(session) as wrote:
            response = _post(client, _body(_camp()), headers)

        assert response.status_code == 401
        assert response.json["code"] == "AUTHENTICATION_REQUIRED"
        assert wrote == {}

    @pytest.mark.parametrize(
        "authorization",
        ["Bearer another-token", COLLECTOR_TOKEN, f"bearer {COLLECTOR_TOKEN}"],
    )
    def test_a_call_with_another_bearer_is_401(
        self, session: DbSession, client: FlaskClient, authorization: str
    ) -> None:
        headers = {**collector_headers(), "Authorization": authorization}

        with writes(session) as wrote:
            response = _post(client, _body(_camp()), headers)

        assert response.status_code == 401
        assert wrote == {}

    def test_every_call_is_401_while_the_token_is_empty(
        self, session: DbSession, container: ServiceContainer, client: FlaskClient
    ) -> None:
        _configure(container, "")

        with writes(session) as wrote:
            for bearer in (f"Bearer {COLLECTOR_TOKEN}", "Bearer ", "Bearer"):
                headers = {**collector_headers(), "Authorization": bearer}
                assert _post(client, _body(_camp()), headers).status_code == 401

        assert wrote == {}

    @pytest.mark.parametrize("version", ["0", "2", "one", "+1", "1.0", ""])
    def test_a_version_outside_the_range_is_426_with_the_range(
        self,
        session: DbSession,
        client: FlaskClient,
        caplog: pytest.LogCaptureFixture,
        version: str,
    ) -> None:
        headers = {**collector_headers(), "X-Pilot-Collector-Protocol": version}

        with writes(session) as wrote, caplog.at_level(logging.WARNING):
            response = _post(client, _body(_camp()), headers)

        assert response.status_code == 426
        assert response.json == {
            "min": COLLECTOR_PROTOCOL_MIN,
            "max": COLLECTOR_PROTOCOL_MAX,
        }
        assert repr(version) in caplog.text
        assert wrote == {}

    def test_a_call_naming_no_version_is_426(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        headers = collector_headers()
        del headers["X-Pilot-Collector-Protocol"]

        with writes(session) as wrote:
            response = _post(client, _body(_camp()), headers)

        assert response.status_code == 426
        assert response.json == {"min": 1, "max": 1}
        assert wrote == {}

    def test_the_bearer_is_asked_for_before_the_version(
        self, client: FlaskClient
    ) -> None:
        headers = {"X-Pilot-Collector-Protocol": "2"}

        assert _post(client, _body(_camp()), headers).status_code == 401

    def test_a_refused_call_is_refused_before_its_body_is_read(
        self, client: FlaskClient
    ) -> None:
        headers = {**collector_headers(), "Authorization": "Bearer another-token"}

        response = client.post(URL, data=b"no publication", headers=headers)

        assert response.status_code == 401

    def test_the_route_is_outside_the_oidc_gate(
        self, session: DbSession, oidc_app: Flask, oidc_client: FlaskClient
    ) -> None:
        assert oidc_app.container.config().oidc_enabled

        response = _post(oidc_client, _body(_camp()))

        assert response.status_code == 204
        assert session.scalars(select(Transcript.session_id)).all() == [CAMP]


class TestPublish:
    def test_a_publication_is_204_and_pilot_holds_the_transcript(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        response = _post(client, _body(_camp()))

        assert response.status_code == 204
        assert response.data == b""
        [thread] = session.scalars(select(Transcript)).all()
        assert (thread.session_id, thread.agent_id) == (CAMP, None)
        assert (thread.file_size, thread.replayed_size) == (48_112, 48_112)
        assert session.scalars(
            select(Call.message_id).order_by(Call.position)
        ).all() == ["msg_0001", "msg_0002"]
        assert session.scalars(select(ToolCall.tool_use_id)).all() == ["toolu_0001"]

    def test_a_sub_agents_thread_is_held_under_its_main_thread(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        assert _post(client, _body(_camp())).status_code == 204

        response = _post(client, _body(sub_agent(spawned_by="toolu_0001")))

        assert response.status_code == 204
        main = session.scalars(
            select(Transcript).where(Transcript.agent_id.is_(None))
        ).one()
        thread = session.scalars(
            select(Transcript).where(Transcript.agent_id == SUB_AGENT)
        ).one()
        assert thread.main_id == main.id
        assert thread.spawned_by_id == session.scalars(select(ToolCall.id)).one()

    def test_a_publication_of_an_unchanged_transcript_is_204_and_writes_its_row_alone(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        assert _post(client, _body(_camp())).status_code == 204
        held = _held(session)

        with writes(session) as wrote:
            response = _post(client, _body(_camp()))

        assert response.status_code == 204
        assert set(wrote) <= {"transcripts"}
        assert _held(session) == held

    def test_a_publication_that_loses_calls_is_204_and_the_count_is_logged(
        self,
        session: DbSession,
        client: FlaskClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        assert _post(client, _body(_camp(calls=4))).status_code == 204

        with caplog.at_level(logging.WARNING, logger=LOGGER):
            response = _post(client, _body(_camp(calls=1)))

        assert response.status_code == 204
        assert response.data == b""
        assert session.scalars(select(Call.message_id)).all() == ["msg_0001"]
        assert f"Transcript {CAMP} no longer has 3 of the calls Pilot held" in (
            caplog.text
        )

    def test_a_body_that_is_not_a_publication_is_400_with_every_field_named(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        body = _body(_camp()) | {"mode": "whole"}
        del body["file_size"]
        body["calls"][1]["tokens"] = {"cache_write": 12}

        with writes(session) as wrote:
            response = _post(client, body)

        assert response.status_code == 400
        assert {tuple(fault["loc"]) for fault in response.json} == {
            ("file_size",),
            ("mode",),
            ("calls", 1, "tokens", "cache_write", "[key]"),
        }
        assert wrote == {}

    def test_a_body_that_is_not_json_is_400(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        with writes(session) as wrote:
            response = client.post(
                URL, data=b"no publication", headers=collector_headers()
            )

        assert response.status_code == 400
        assert wrote == {}

    def test_a_call_that_contradicts_itself_is_400_with_every_fault_named(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        assert _post(client, _body(_camp())).status_code == 204
        held = _held(session)
        contradicting = whole(
            description="Find where the recipes are scaled",
            calls=[
                call(1, tool_calls=[tool_call(1, exit_code=0)]),
                call(2, predecessor="msg_0009"),
            ],
        )

        with writes(session) as wrote:
            response = _post(client, _body(contradicting))

        assert response.status_code == 400
        assert response.json["code"] == "VALIDATION_FAILED"
        assert response.json["error"] == (
            f"Cannot take the publication of transcript {CAMP} because"
            " a main thread has no `description`;"
            " call `msg_0001`: tool call `toolu_0001`: `exit_code` is 0;"
            " call `msg_0002`: `predecessor` `msg_0009` is no earlier call"
        )
        assert wrote == {}
        assert _held(session) == held

    def test_a_body_over_the_cap_is_413(
        self,
        session: DbSession,
        app: Flask,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 256)

        with writes(session) as wrote:
            response = _post(client, _body(_camp()))

        assert response.status_code == 413
        assert wrote == {}

    def test_no_other_method_is_served(self, client: FlaskClient) -> None:
        for method in ("GET", "PUT", "DELETE"):
            response = client.open(URL, method=method, headers=collector_headers())
            assert response.status_code == 405
