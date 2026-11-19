"""The collector's routes (F152.2, F152.3, F152.14):
`GET /api/collector/inventory`, `POST /api/collector/publications` and
`POST /api/collector/walks` under the collector's bearer, outside the
sign-in gate, each answer pinned beside the protocol's version."""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from queue import Empty
from typing import Any

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from werkzeug.test import TestResponse

from app import models
from app.models import Call, Project, ToolCall, Transcript, User, Walk
from app.models.reference import ProjectState
from app.schemas.publication import PublicationSchema
from app.services.container import ServiceContainer
from app.services.publication_service import (
    COLLECTOR_PROTOCOL_MAX,
    COLLECTOR_PROTOCOL_MIN,
)
from app.services.sse_connection_manager import SSEConnection
from app.services.walk_service import EVENT_NAME
from tests.support.adoption import FIRST_MENUS
from tests.support.database import writes
from tests.support.publications import (
    COLLECTOR_TOKEN,
    appended,
    builds_on,
    call,
    collector_headers,
    group,
    launch,
    prompt,
    sub_agent,
    tool_call,
    whole,
)
from tests.support.transcripts import CAMP, OTHER, SUB_AGENT

URL = "/api/collector/publications"
INVENTORY = "/api/collector/inventory"
WALKS = "/api/collector/walks"
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


def _configure_walks(
    container: ServiceContainer, interval: float, settling: float
) -> None:
    """The app settings with those two as the walk's, for this test."""
    settings = container.app_config().model_copy(
        update={
            "collector_walk_interval_seconds": interval,
            "collector_settling_seconds": settling,
        }
    )
    container.app_config.override(providers.Object(settings))


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


class TestInventory:
    def test_a_record_with_no_transcript_answers_the_walks_settings_alone(
        self, client: FlaskClient
    ) -> None:
        response = client.get(INVENTORY, headers=collector_headers())

        assert response.status_code == 200
        assert response.json == {
            "walk_interval_seconds": 30.0,
            "settling_seconds": 600.0,
            "transcripts": [],
        }

    def test_each_transcript_pilot_holds_is_named_as_its_last_publication_left_it(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        """A main thread grown since its whole publication, its sub-agent's
        thread, and another main thread read under another version."""
        another = whole(
            session_id=OTHER,
            file_size=912,
            file_modified_at="2026-11-12T11:02:03.456789+01:00",
            collector={"version": "1.1.0"},
        )
        grown = appended(
            call=2,
            launch=2,
            prompt=2,
            calls=[call(2, predecessor="msg_0001"), call(3, predecessor="msg_0002")],
        )
        for publication in (another, _camp(), sub_agent(), grown):
            assert _post(client, _body(publication)).status_code == 204

        response = client.get(INVENTORY, headers=collector_headers())

        assert response.status_code == 200
        assert response.json["transcripts"] == [
            {
                "session_id": CAMP,
                "agent_id": None,
                "file_size": 61_000,
                "file_modified_at": "2026-11-12T10:00:00Z",
                "replayed_size": 48_112,
                "collector": "1.0.0",
            },
            {
                "session_id": CAMP,
                "agent_id": SUB_AGENT,
                "file_size": 48_112,
                "file_modified_at": "2026-11-12T09:42:00Z",
                "replayed_size": 48_112,
                "collector": "1.0.0",
            },
            {
                "session_id": OTHER,
                "agent_id": None,
                "file_size": 912,
                "file_modified_at": "2026-11-12T10:02:03.456789Z",
                "replayed_size": 912,
                "collector": "1.1.0",
            },
        ]

    def test_the_walks_settings_are_the_servers(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        _configure_walks(container, interval=300.0, settling=0.0)

        response = client.get(INVENTORY, headers=collector_headers())

        assert response.json == {
            "walk_interval_seconds": 300.0,
            "settling_seconds": 0.0,
            "transcripts": [],
        }

    def test_the_inventory_writes_nothing(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        assert _post(client, _body(_camp())).status_code == 204

        with writes(session) as wrote:
            assert client.get(INVENTORY, headers=collector_headers()).status_code == 200

        assert wrote == {}

    def test_a_call_without_the_bearer_is_401(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        assert _post(client, _body(_camp())).status_code == 204
        headers = {**collector_headers(), "Authorization": "Bearer another-token"}

        response = client.get(INVENTORY, headers=headers)

        assert response.status_code == 401
        assert response.json["code"] == "AUTHENTICATION_REQUIRED"
        assert "transcripts" not in response.json

    def test_every_call_is_401_while_the_token_is_empty(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        _configure(container, "")

        for bearer in (f"Bearer {COLLECTOR_TOKEN}", "Bearer ", "Bearer"):
            headers = {**collector_headers(), "Authorization": bearer}
            assert client.get(INVENTORY, headers=headers).status_code == 401

    @pytest.mark.parametrize("version", ["0", "2", None])
    def test_a_version_outside_the_range_is_426_with_the_range(
        self, client: FlaskClient, version: str | None
    ) -> None:
        headers = collector_headers()
        if version is None:
            del headers["X-Pilot-Collector-Protocol"]
        else:
            headers["X-Pilot-Collector-Protocol"] = version

        response = client.get(INVENTORY, headers=headers)

        assert response.status_code == 426
        assert response.json == {
            "min": COLLECTOR_PROTOCOL_MIN,
            "max": COLLECTOR_PROTOCOL_MAX,
        }

    def test_the_route_is_outside_the_oidc_gate(
        self, oidc_app: Flask, oidc_client: FlaskClient
    ) -> None:
        assert oidc_app.container.config().oidc_enabled

        response = oidc_client.get(INVENTORY, headers=collector_headers())

        assert response.status_code == 200
        assert response.json["transcripts"] == []

    def test_no_other_method_is_served(self, client: FlaskClient) -> None:
        for method in ("POST", "PUT", "DELETE"):
            response = client.open(
                INVENTORY, method=method, headers=collector_headers()
            )
            assert response.status_code == 405


@pytest.fixture
def ada(container: ServiceContainer, person: User) -> Iterator[SSEConnection]:
    """A connection of the person's."""
    manager = container.sse_connection_manager()
    connection = manager.on_connect("ada-1", person.subject)
    yield connection
    manager.on_disconnect(connection)


def _events(connection: SSEConnection) -> list[dict[str, Any]]:
    """The events queued on the connection, in order."""
    queued = []
    while True:
        try:
            frame = connection.next_frame(timeout=0)
        except Empty:
            return queued
        assert frame is not None
        queued.append(json.loads(frame.removeprefix("data: ")))


class TestEndWalk:
    def test_a_walks_end_is_204_and_the_walk_is_stamped(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        before = datetime.now(UTC)

        response = client.post(WALKS, headers=collector_headers())

        assert (response.status_code, response.data) == (204, b"")
        [ended_at] = session.scalars(select(Walk.ended_at)).all()
        assert before <= ended_at <= datetime.now(UTC)

    def test_a_walk_that_published_raises_one_event_once_the_call_committed(
        self, client: FlaskClient, session: DbSession, ada: SSEConnection
    ) -> None:
        """F152.14, F154.8: one per walk, whatever it published."""
        assert _post(client, _body(_camp())).status_code == 204
        assert _post(client, _body(sub_agent())).status_code == 204
        assert _events(ada) == []

        assert client.post(WALKS, headers=collector_headers()).status_code == 204

        [ended_at] = session.scalars(select(Walk.ended_at)).all()
        assert _events(ada) == [
            {
                "type": EVENT_NAME,
                "payload": {"as_of": ended_at.isoformat().replace("+00:00", "Z")},
            }
        ]

    def test_a_walk_that_published_nothing_raises_none(
        self, client: FlaskClient, session: DbSession, ada: SSEConnection
    ) -> None:
        assert _post(client, _body(_camp())).status_code == 204
        assert client.post(WALKS, headers=collector_headers()).status_code == 204
        _events(ada)

        assert client.post(WALKS, headers=collector_headers()).status_code == 204

        assert _events(ada) == []
        assert len(session.scalars(select(Walk.id)).all()) == 2

    def test_a_call_without_the_bearer_is_401_and_stamps_no_walk(
        self, session: DbSession, client: FlaskClient, ada: SSEConnection
    ) -> None:
        assert _post(client, _body(_camp())).status_code == 204
        headers = {**collector_headers(), "Authorization": "Bearer another-token"}

        with writes(session) as wrote:
            response = client.post(WALKS, headers=headers)

        assert response.status_code == 401
        assert response.json["code"] == "AUTHENTICATION_REQUIRED"
        assert wrote == {}
        assert _events(ada) == []

    def test_every_call_is_401_while_the_token_is_empty(
        self, container: ServiceContainer, client: FlaskClient
    ) -> None:
        _configure(container, "")

        for bearer in (f"Bearer {COLLECTOR_TOKEN}", "Bearer ", "Bearer"):
            headers = {**collector_headers(), "Authorization": bearer}
            assert client.post(WALKS, headers=headers).status_code == 401

    @pytest.mark.parametrize("version", ["0", "2", None])
    def test_a_version_outside_the_range_is_426_with_the_range(
        self, session: DbSession, client: FlaskClient, version: str | None
    ) -> None:
        headers = collector_headers()
        if version is None:
            del headers["X-Pilot-Collector-Protocol"]
        else:
            headers["X-Pilot-Collector-Protocol"] = version

        with writes(session) as wrote:
            response = client.post(WALKS, headers=headers)

        assert response.status_code == 426
        assert response.json == {
            "min": COLLECTOR_PROTOCOL_MIN,
            "max": COLLECTOR_PROTOCOL_MAX,
        }
        assert wrote == {}

    def test_the_route_is_outside_the_oidc_gate(
        self, oidc_app: Flask, oidc_client: FlaskClient
    ) -> None:
        assert oidc_app.container.config().oidc_enabled

        response = oidc_client.post(WALKS, headers=collector_headers())

        assert response.status_code == 204

    def test_no_other_method_is_served(self, client: FlaskClient) -> None:
        for method in ("GET", "PUT", "DELETE"):
            response = client.open(WALKS, method=method, headers=collector_headers())
            assert response.status_code == 405


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

    def test_an_appended_publication_is_204_and_pilot_holds_what_it_carries(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        assert _post(client, _body(_camp())).status_code == 204
        held = _held(session)
        grown = appended(
            call=2,
            launch=2,
            prompt=2,
            calls=[call(2, predecessor="msg_0001"), call(3, predecessor="msg_0002")],
        )

        with writes(session) as wrote:
            response = _post(client, _body(grown))

        assert response.status_code == 204
        assert response.data == b""
        assert set(wrote) == {"transcripts", "calls"}
        assert wrote["calls"].inserted == 1
        after = _held(session)
        assert after["calls"][:2] == held["calls"]
        assert after | {"calls": held["calls"]} == held
        [thread] = session.scalars(select(Transcript)).all()
        session.refresh(thread)
        assert (thread.file_size, thread.replayed_size) == (61_000, 48_112)
        assert session.scalars(
            select(Call.message_id).order_by(Call.position)
        ).all() == ["msg_0001", "msg_0002", "msg_0003"]

    def test_an_appended_call_that_does_not_continue_what_pilot_holds_is_409(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        """The code tells the collector to publish the transcript whole, which
        Pilot then takes."""
        assert _post(client, _body(_camp())).status_code == 204
        held = _held(session)
        grown = [call(2, predecessor="msg_0001"), call(3, predecessor="msg_0002")]
        stale = appended(
            call=2,
            launch=2,
            prompt=2,
            builds_on=builds_on(file_size=40_000),
            calls=grown,
        )

        with writes(session) as wrote:
            response = _post(client, _body(stale))

        assert response.status_code == 409
        assert response.json["code"] == "PUBLICATION_NOT_APPENDABLE"
        assert response.json["error"] == (
            f"Cannot append to transcript {CAMP} because Pilot holds it at another"
            " size, time or collector's version than the call builds on"
        )
        assert wrote == {}
        assert _held(session) == held

        whole_again = _body(_camp(calls=3)) | {"file_size": 61_000}
        assert _post(client, whole_again).status_code == 204
        assert len(_held(session)["calls"]) == 3

    def test_an_appended_call_whose_first_launch_is_not_the_one_held_there_is_409(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        """A boundary one Launch short: the file's second Launch, named at
        the place of the first, which Pilot holds."""
        assert _post(client, _body(_camp())).status_code == 204
        held = _held(session)
        second = launch(started_at="2026-11-12T09:45:00+00:00")
        short = appended(call=3, prompt=2, launches=[second], calls=[call(3)])

        with writes(session) as wrote:
            response = _post(client, _body(short))

        assert response.status_code == 409
        assert response.json["code"] == "PUBLICATION_NOT_APPENDABLE"
        assert response.json["error"] == (
            f"Cannot append to transcript {CAMP} because the boundary's `launch` is"
            " 1, where Pilot holds a launch begun at 2026-11-12T09:30:00+00:00, and"
            " the call's first was begun at 2026-11-12T09:45:00+00:00"
        )
        assert wrote == {}
        assert _held(session) == held

    def test_an_appended_call_for_a_transcript_pilot_does_not_hold_is_409(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        with writes(session) as wrote:
            response = _post(client, _body(appended(calls=[call(1)])))

        assert response.status_code == 409
        assert response.json["code"] == "PUBLICATION_NOT_APPENDABLE"
        assert wrote == {}

    def test_a_call_naming_a_group_has_its_project_made_and_the_transcript_adopted(
        self, session: DbSession, client: FlaskClient, service_user: User
    ) -> None:
        """F152.8."""
        response = _post(client, _body(_camp()) | {"group": group()})

        assert response.status_code == 204
        project = session.scalars(select(Project)).one()
        assert (project.state_code, project.adopted_group, project.name) == (
            ProjectState.ADOPTED,
            FIRST_MENUS,
            "Recipe box: the first menus",
        )
        assert session.scalars(select(Transcript.adopted_project_id)).all() == [
            project.id
        ]

    def test_a_group_first_named_on_a_stage_with_no_service_user_is_409(
        self, session: DbSession, client: FlaskClient
    ) -> None:
        with writes(session) as wrote:
            response = _post(client, _body(_camp()) | {"group": group()})

        assert response.status_code == 409
        assert response.json["code"] == "NO_SERVICE_USER"
        assert response.json["error"] == (
            "Cannot make the adopted project of the group 'recipe-box-first-menus'"
            " because the stage has no service user to make it"
        )
        assert wrote == {}

    def test_a_group_named_for_a_transcript_a_session_of_pilots_ran_is_409(
        self,
        session: DbSession,
        client: FlaskClient,
        project_session: models.Session,
        service_user: User,
    ) -> None:
        """DB 539. The call without its group is then taken."""
        project_session.conversation_id = CAMP
        session.flush()

        with writes(session) as wrote:
            response = _post(client, _body(_camp()) | {"group": group()})

        assert response.status_code == 409
        assert response.json["code"] == "TRANSCRIPT_NOT_ADOPTABLE"
        assert response.json["error"] == (
            f"Cannot adopt transcript {CAMP} into the group 'recipe-box-first-menus'"
            " because a session of Pilot's ran it"
        )
        assert wrote == {}
        assert _post(client, _body(_camp())).status_code == 204

    def test_a_group_that_makes_no_project_document_is_400(
        self, session: DbSession, client: FlaskClient, service_user: User
    ) -> None:
        body = _body(_camp()) | {"group": group(name="The first menus ")}

        with writes(session) as wrote:
            response = _post(client, body)

        assert response.status_code == 400
        assert response.json["code"] == "VALIDATION_FAILED"
        assert response.json["error"] == (
            f"Cannot take the publication of transcript {CAMP} because the group's"
            " `name` is not one line of words with no space around them"
        )
        assert wrote == {}

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
