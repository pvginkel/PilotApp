"""Pilot's MCP server as a headless create hands it to a session (TD §4.5;
F84, V02): the token minted for the create, its hash, and the `mcpConfig`
entry that names the server."""

import hashlib
import json

from app.services.controller_client import HeadlessCreateRequest
from app.services.pilot_server import PilotServer, token_hash

URL = "https://pilot-mcp.example.com/mcp"


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
    def test_the_create_carries_the_token_in_its_env_and_the_server_in_its_mcp_config(
        self,
    ) -> None:
        injected = PilotServer(URL).inject(
            HeadlessCreateRequest(cwd="/work/Example", resume="conversation-1")
        )

        token = _token(injected.request)
        assert injected.request.env == [f"PILOT_TOKEN={token}"]
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

        injected = PilotServer(URL).inject(request)

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
            HeadlessCreateRequest(env=["EXAMPLE=1"], mcp_config=["/work/mcp.json"])
        )

        token = _token(injected.request)
        assert injected.request.env == ["EXAMPLE=1", f"PILOT_TOKEN={token}"]
        assert injected.request.mcp_config is not None
        assert injected.request.mcp_config[0] == "/work/mcp.json"
        assert len(injected.request.mcp_config) == 2

    def test_each_create_gets_a_token_of_its_own(self) -> None:
        server = PilotServer(URL)

        first = server.inject(HeadlessCreateRequest())
        second = server.inject(HeadlessCreateRequest())

        assert _token(first.request) != _token(second.request)
        assert first.token_hash != second.token_hash

    def test_with_no_server_the_create_carries_neither_and_a_token_is_still_minted(
        self,
    ) -> None:
        request = HeadlessCreateRequest(cwd="/work/Example")
        server = PilotServer(None)

        first = server.inject(request)
        second = server.inject(request)

        assert first.request == request
        assert len(first.token_hash) == 64
        assert first.token_hash != second.token_hash
