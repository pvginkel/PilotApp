"""Pilot's MCP server as a headless create hands it to a session (TD §4.5;
F84, F84.1, V02): the token minted for the create, its hash, the `mcpConfig`
entry that names the server at its surface's endpoint, and the endpoint beside
the token in the `env`; a bearer resolved to its Session, and whether its
turn runs, read past a send under way (P-226)."""

import hashlib
import json
from urllib.parse import urlparse

import pytest
from flask import Flask
from sqlalchemy import text as sql
from sqlalchemy.orm import Session as DbSession

from app import extensions, models
from app.database import scoped_session
from app.exceptions import AuthenticationException
from app.models import Project, User
from app.models.reference import SessionState, Surface, UserKind
from app.services.advisory_turn import turn_key
from app.services.controller_client import HeadlessCreateRequest
from app.services.pilot_server import (
    SEND_LOCK,
    PilotServer,
    bearer_session,
    hold_send,
    token_hash,
    turn_running,
)
from app.services.session_scope import ScopedCreate
from pilot_mcp.server import STORE_PATH as SERVED_STORE_PATH
from pilot_mcp.server import WORK_PATH as SERVED_WORK_PATH
from tests.support.locks import in_thread, lock_waits
from tests.support.supervisor import wait_until

URL = "https://pilot-mcp.example.com/mcp"


def _work(request: HeadlessCreateRequest) -> ScopedCreate:
    return ScopedCreate(request, Surface.WORK)


def _token(request: HeadlessCreateRequest) -> str:
    """The plaintext the create's `env` carries as `PILOT_TOKEN`."""
    assert request.env is not None
    (token,) = [
        entry.removeprefix("PILOT_TOKEN=")
        for entry in request.env
        if entry.startswith("PILOT_TOKEN=")
    ]
    return token


class TestTokenHash:
    def test_it_is_the_tokens_sha256_in_lowercase_hex(self) -> None:
        assert token_hash("an-example-token") == (
            hashlib.sha256(b"an-example-token").hexdigest()
        )


class TestInject:
    def test_the_create_carries_the_token_and_the_endpoint_in_its_env_and_the_server_in_its_mcp_config(
        self,
    ) -> None:
        injected = PilotServer(URL).inject(
            _work(HeadlessCreateRequest(cwd="/work/Example", resume="conversation-1"))
        )

        token = _token(injected.request)
        assert injected.request.env == [f"PILOT_TOKEN={token}", f"PILOT_MCP_URL={URL}"]
        assert injected.request.mcp_config is not None
        (entry,) = injected.request.mcp_config
        # The shape of KubeCoder's own fleet registration: `claude` expands the
        # bearer from the spawned process's environment.
        assert json.loads(entry) == {
            "mcpServers": {
                "pilot": {
                    "type": "http",
                    "url": URL,
                    "headers": {"Authorization": "Bearer ${PILOT_TOKEN}"},
                }
            }
        }
        assert token not in entry
        assert injected.token_hash == token_hash(token)

    def test_the_rest_of_the_create_is_kept_and_strict_mcp_config_left_unset(
        self,
    ) -> None:
        request = HeadlessCreateRequest(
            cwd="/work/Example",
            resume="conversation-1",
            agent="worker",
            model="model-1",
            reasoning_effort="high",
        )

        injected = PilotServer(URL).inject(_work(request))

        assert injected.request.model_dump(
            by_alias=True, exclude_none=True, exclude={"env", "mcp_config"}
        ) == {
            "cwd": "/work/Example",
            "resume": "conversation-1",
            "agent": "worker",
            "model": "model-1",
            "reasoningEffort": "high",
        }
        assert injected.request.strict_mcp_config is None
        assert request.env is None and request.mcp_config is None

    def test_an_env_and_mcp_config_the_create_had_are_kept_ahead_of_the_servers(
        self,
    ) -> None:
        injected = PilotServer(URL).inject(
            _work(
                HeadlessCreateRequest(env=["EXAMPLE=1"], mcp_config=["/work/mcp.json"])
            )
        )

        token = _token(injected.request)
        assert injected.request.env == [
            "EXAMPLE=1",
            f"PILOT_TOKEN={token}",
            f"PILOT_MCP_URL={URL}",
        ]
        assert injected.request.mcp_config is not None
        assert injected.request.mcp_config[0] == "/work/mcp.json"
        assert len(injected.request.mcp_config) == 2

    def test_each_create_gets_a_token_of_its_own(self) -> None:
        server = PilotServer(URL)

        first = server.inject(_work(HeadlessCreateRequest()))
        second = server.inject(_work(HeadlessCreateRequest()))

        assert _token(first.request) != _token(second.request)
        assert first.token_hash != second.token_hash

    def test_with_no_server_the_create_carries_neither_and_a_token_is_still_minted(
        self,
    ) -> None:
        request = HeadlessCreateRequest(cwd="/work/Example")
        server = PilotServer(None)

        first = server.inject(_work(request))
        second = server.inject(_work(request))

        assert first.request == request
        assert len(first.token_hash) == 64
        assert first.token_hash != second.token_hash

    def test_a_create_with_no_surface_carries_neither_and_a_token_is_still_minted(
        self,
    ) -> None:
        """A finished project's brain session (F5.5): no bearer it holds
        reaches either surface."""
        request = HeadlessCreateRequest(
            cwd="/work/PilotProjects",
            sandbox_read_only_cwd=True,
            env=["PILOT_PROJECT=/work/Projects/soup-club"],
        )

        injected = PilotServer(URL).inject(ScopedCreate(request, None))

        assert injected.request == request
        assert len(injected.token_hash) == 64

    @pytest.mark.parametrize(
        ("url", "surface", "endpoint"),
        [
            (URL, Surface.WORK, URL),
            (URL, Surface.STORE, f"{URL}/store"),
            (f"{URL}/", Surface.STORE, f"{URL}/store"),
        ],
        ids=["pilot-work", "pilot-store", "pilot-store-under-a-slash"],
    )
    def test_the_server_is_named_at_its_surfaces_endpoint_and_the_env_carries_it(
        self, url: str, surface: Surface, endpoint: str
    ) -> None:
        injected = PilotServer(url).inject(
            ScopedCreate(HeadlessCreateRequest(cwd="/work/PilotProjects"), surface)
        )

        assert injected.request.mcp_config is not None
        (entry,) = injected.request.mcp_config
        assert json.loads(entry)["mcpServers"] == {
            "pilot": {
                "type": "http",
                "url": endpoint,
                "headers": {"Authorization": "Bearer ${PILOT_TOKEN}"},
            }
        }
        assert injected.request.env == [
            f"PILOT_TOKEN={_token(injected.request)}",
            f"PILOT_MCP_URL={endpoint}",
        ]

    def test_each_surfaces_endpoint_is_the_path_the_mcp_process_serves_it_at(
        self,
    ) -> None:
        server = PilotServer(f"https://pilot-mcp.example.com{SERVED_WORK_PATH}")

        served = {}
        for surface in Surface:
            injected = server.inject(ScopedCreate(HeadlessCreateRequest(), surface))
            assert injected.request.mcp_config is not None
            (entry,) = injected.request.mcp_config
            served[surface] = urlparse(json.loads(entry)["mcpServers"]["pilot"]["url"])

        assert {surface: url.path for surface, url in served.items()} == {
            Surface.WORK: SERVED_WORK_PATH,
            Surface.STORE: SERVED_STORE_PATH,
        }


def _session(db: DbSession, project: Project, kind: str) -> models.Session:
    run = models.Session(
        project_id=project.id,
        kind_code=kind,
        cwd="/work/Example",
        token_hash=token_hash(f"{kind}-token"),
        state_code=SessionState.RUNNING,
    )
    db.add(run)
    db.flush()
    return run


class TestBearerSession:
    @pytest.mark.parametrize(
        ("kind", "surface"),
        [("work", Surface.WORK), ("chat", Surface.STORE), ("job", Surface.STORE)],
    )
    def test_a_bearer_names_its_session_and_its_kinds_surface(
        self, session: DbSession, project: Project, kind: str, surface: Surface
    ) -> None:
        run = _session(session, project, kind)

        assert bearer_session(session, f"Bearer {kind}-token", Surface.STORE) == (
            run,
            surface,
        )

    @pytest.mark.parametrize(
        ("authorization", "message"),
        [
            (None, "Cannot call pilot-store because the request carries no bearer"),
            (
                "Basic chat-token",
                "Cannot call pilot-store because the request carries no bearer",
            ),
            (
                "Bearer another-token",
                "Cannot call pilot-store because no session has the request's bearer",
            ),
        ],
    )
    def test_no_bearer_or_one_no_session_has_is_refused(
        self,
        session: DbSession,
        project: Project,
        authorization: str | None,
        message: str,
    ) -> None:
        _session(session, project, "chat")

        with pytest.raises(AuthenticationException) as refused:
            bearer_session(session, authorization, Surface.STORE)

        assert refused.value.message == message


def _committed_session(committed_app: Flask, state: SessionState) -> models.Session:
    """A chat's Session in `state` and its project, committed, detached."""
    with scoped_session(committed_app.container) as db:
        person = User(
            kind_code=UserKind.PERSON,
            subject="subject-ada",
            handle="ada",
            name="Ada Example",
            avatar_slot=1,
        )
        db.add(person)
        db.flush()
        project = Project(created_by_user_id=person.id)
        db.add(project)
        db.flush()
        run = _session(db, project, "chat")
        run.state_code = state
        db.flush()
        db.expunge(run)
        return run


class TestTurnRunning:
    def test_a_session_read_with_its_turn_running_is_admitted(
        self, session: DbSession, project: Project
    ) -> None:
        assert turn_running(session, _session(session, project, "chat"))

    @pytest.mark.parametrize(
        "state",
        [
            SessionState.HELD,
            SessionState.STARTING,
            SessionState.IDLE,
            SessionState.STOPPED,
        ],
    )
    def test_one_with_no_turn_running_is_read_again_and_refused(
        self, session: DbSession, project: Project, state: SessionState
    ) -> None:
        run = _session(session, project, "chat")
        run.state_code = state
        session.flush()

        assert not turn_running(session, run)

    @pytest.mark.parametrize("send", ["a chat's send", "the start loop's send"])
    @pytest.mark.parametrize(
        ("outcome", "running"), [("commits", True), ("rolls back", False)]
    )
    def test_one_read_while_a_send_is_under_way_is_read_as_the_send_ends(
        self, committed_app: Flask, send: str, outcome: str, running: bool
    ) -> None:
        """P-226: a call made once the controller answered the send's `202`,
        before the send's transaction ends, waits on what the send holds, a
        chat's its project's row shared, the start loop's the Session's send
        lock, and reads the Session as that end left it."""
        container = committed_app.container
        run = _committed_session(committed_app, SessionState.STARTING)

        def read() -> bool:
            with scoped_session(container) as db:
                return turn_running(db, db.get_one(models.Session, run.id))

        with container.session_maker()() as sending:
            if send == "a chat's send":
                sending.execute(
                    sql("SELECT id FROM projects WHERE id = :id FOR KEY SHARE"),
                    {"id": run.project_id},
                )
            else:
                hold_send(sending, run.id)
            sending.execute(
                sql("UPDATE sessions SET state_code = 'running' WHERE id = :id"),
                {"id": run.id},
            )
            reading = in_thread(read)
            wait_until(lambda: lock_waits(container) == 1, "the read waiting")
            if outcome == "commits":
                sending.commit()
            else:
                sending.rollback()

            assert reading.result() is running

    def test_its_locks_are_let_go_once_read(self, committed_app: Flask) -> None:
        run = _committed_session(committed_app, SessionState.IDLE)
        with committed_app.app_context():
            engine = extensions.db.engine

        with scoped_session(committed_app.container) as db:
            assert not turn_running(db, db.get_one(models.Session, run.id))
            with engine.connect() as other:
                other.execute(
                    sql("SELECT id FROM projects WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": run.project_id},
                )
                assert other.scalar(
                    sql("SELECT pg_try_advisory_xact_lock(:first, :second)"),
                    {"first": SEND_LOCK, "second": turn_key(run.id.bytes)},
                )
                other.rollback()
