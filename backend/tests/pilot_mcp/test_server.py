"""Pilot's MCP server (F83): its tool surface pinned, as a contract the
sessions it is handed to are written against, the bearer it requires, and the
probes that answer without one."""

import pytest
from starlette.applications import Starlette

from tests.support.pilot_mcp import BEARER, ApiRoutes, http_client, mcp_session

_PATH = {
    "description": "The document's absolute path in this environment, under `/work`",
    "minLength": 1,
    "title": "Path",
    "type": "string",
}

_MATERIAL = {
    "description": (
        "The file's or the folder's absolute path in this environment, under"
        " `/work`: a folder's every file under it"
    ),
    "minLength": 1,
    "title": "Path",
    "type": "string",
}

_TO = {
    "anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}],
    "default": None,
    "description": (
        "The id of the item the material backs, an item of your project: usually"
        " the id `register_document` answered. Without it, this session's own work"
        " item"
    ),
    "title": "To",
}

_UUID = {"format": "uuid", "type": "string"}

# Each tool: its parameters, its result and its description, the words as the
# worker reads them (FM §5 step 1, F65.3, F85).
SURFACE = {
    "register_document": (
        {
            "properties": {"path": _PATH},
            "required": ["path"],
            "title": "register_documentArguments",
            "type": "object",
        },
        {
            "description": "The registered document.",
            "properties": {
                "id": {
                    **_UUID,
                    "description": (
                        "Its item's id on the project's timeline, `attach_file`'s `to`"
                    ),
                    "title": "Id",
                }
            },
            "required": ["id"],
            "title": "RegisteredDocument",
            "type": "object",
        },
        "Register a decision document you wrote, by its file's absolute path under"
        " `/work` in this environment, to put it to the operator on your project's"
        " timeline. The file is read and parsed at once: a path outside `/work`, no"
        " file there, a file over 16 MiB, or a text whose front matter or blocks do"
        " not parse is refused with the reason, each fault with its line, and"
        " nothing is registered; fix the file and register it again. Answers `{id}`,"
        " the document's item id, which `attach_file` takes as `to`. Registering"
        " the same path again in this work item answers the same id. What the"
        " operator reads is the file as your turn leaves it: Pilot reads it again"
        " when your turn ends. Once you have registered your documents and attached"
        " what backs them, end your turn; never wait for the answers. When every"
        " document you registered is answered, Pilot writes each back in place, the"
        " answers in it, and continues this conversation as a new work item with a"
        " message naming the files; registering a revised file then makes a new"
        " document.",
    ),
    "attach_file": (
        {
            "properties": {"path": _MATERIAL, "to": _TO},
            "required": ["path"],
            "title": "attach_fileArguments",
            "type": "object",
        },
        {
            "description": "The attachments the material was copied into.",
            "properties": {
                "ids": {
                    "description": (
                        "Their ids, one per file, a folder's in its files' path order"
                    ),
                    "items": _UUID,
                    "title": "Ids",
                    "type": "array",
                }
            },
            "required": ["ids"],
            "title": "AttachedFiles",
            "type": "object",
        },
        "Copy material that backs a document into Pilot's record, by its absolute"
        " path under `/work` in this environment: a file, or a folder and every file"
        " under it, one attachment per file. Each is copied now, with this"
        " environment and its path as its source; what you change in it later is not"
        " seen. `to` is the id of the item the material backs, usually the one"
        " `register_document` just answered; without it, the material hangs on this"
        " session's own work item. A call that cannot copy every file it names — a"
        " path outside `/work`, no file there, a file over 16 MiB, a folder over the"
        " cap of one call, a `to` that is not an item of your project — attaches"
        " nothing and answers the reason. Answers `{ids}`, the attachments' ids, a"
        " folder's in its files' path order. Once you have registered your"
        " documents and attached what backs them, end your turn; never wait for the"
        " answers.",
    ),
}

INSTRUCTIONS = (
    "Pilot, the project manager that started this session to do a work item of its"
    " project. Write each decision document your work produces as a file under"
    " `/work`, register it with `register_document` and attach what backs it with"
    " `attach_file`, then end your turn: never wait for the answers. Pilot reads"
    " each registered document again when your turn ends and puts it to the"
    " operator; once every one is answered, Pilot writes the answered files back in"
    " place and continues this conversation with a message naming them."
)

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}

_ACCEPT = {"Accept": "application/json, text/event-stream"}


def _words(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.anyio
class TestTheSurface:
    async def test_the_tools_are_pinned(
        self, mcp_app: Starlette, routes: ApiRoutes
    ) -> None:
        async with mcp_session(mcp_app) as (session, _):
            tools = (await session.list_tools()).tools

        surface = {
            tool.name: (
                tool.inputSchema,
                tool.outputSchema,
                _words(tool.description or ""),
            )
            for tool in tools
        }
        assert surface == SURFACE
        assert routes.calls == []

    async def test_the_server_is_pilot_with_its_instructions(
        self, mcp_app: Starlette
    ) -> None:
        async with mcp_session(mcp_app) as (_, initialized):
            pass

        assert initialized.serverInfo.name == "pilot"
        assert initialized.instructions == INSTRUCTIONS


@pytest.mark.anyio
class TestTheBearer:
    @pytest.mark.parametrize(
        "authorization",
        [None, "Bearer ", "Bearer   ", "bearer worker-token", "Basic worker-token"],
    )
    async def test_a_request_with_no_bearer_is_refused(
        self, mcp_app: Starlette, routes: ApiRoutes, authorization: str | None
    ) -> None:
        headers = {} if authorization is None else {"Authorization": authorization}
        async with http_client(mcp_app, headers) as http:
            response = await http.post("/mcp", json=_INITIALIZE, headers=_ACCEPT)

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {
            "error": (
                "Cannot call Pilot's MCP server because the request carries no bearer"
            ),
            "details": {
                "message": (
                    "Send the session's PILOT_TOKEN as `Authorization: Bearer <token>`"
                )
            },
            "code": "AUTHENTICATION_REQUIRED",
        }
        assert routes.calls == []

    async def test_a_bearer_is_admitted_without_its_check(
        self, mcp_app: Starlette, routes: ApiRoutes
    ) -> None:
        headers = {"Authorization": "Bearer a-token-no-session-has"}
        async with mcp_session(mcp_app, headers) as (session, _):
            tools = (await session.list_tools()).tools

        assert {tool.name for tool in tools} == set(SURFACE)
        assert routes.calls == []

    @pytest.mark.parametrize("path", ["/health/healthz", "/health/readyz"])
    async def test_the_probes_answer_without_a_bearer(
        self, mcp_app: Starlette, routes: ApiRoutes, path: str
    ) -> None:
        async with http_client(mcp_app) as http:
            response = await http.get(path)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert routes.calls == []

    async def test_any_other_path_needs_a_bearer(self, mcp_app: Starlette) -> None:
        async with http_client(mcp_app) as http:
            assert (await http.get("/")).status_code == 401
        async with http_client(mcp_app, BEARER) as http:
            assert (await http.get("/")).status_code == 404
