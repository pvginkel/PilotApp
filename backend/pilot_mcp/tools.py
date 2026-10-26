"""`pilot-work`'s tools (F85, FM §5 step 1), each one call to its route.

A tool's docstring is the description the worker reads, and each parameter's
is in its annotation: they are the surface, not commentary
(`tests/pilot_mcp/test_server.py` pins them). The bearer a call carries is the
API's to resolve; a tool passes it on as it came, with the tool-use id Claude
Code sends in the call's `_meta`, which the call's effect names.
"""

import uuid
from typing import Annotated

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import Field
from starlette.requests import Request

from pilot_mcp.api import AttachedFiles, PilotWorkApi, RegisteredDocument

Call = Context[ServerSession, object, Request]

TOOL_USE_ID_META = "claudecode/toolUseId"
"""The `_meta` key of the tool-use id Claude Code sends with every
`tools/call`."""


def _authorization(ctx: Call) -> str:
    request = ctx.request_context.request
    # Streamable HTTP hands every call its request, and the bearer gate
    # (`server.py`) admitted it only with an `Authorization` header.
    assert request is not None
    return request.headers["authorization"]


def _tool_use_id(ctx: Call) -> str | None:
    """The tool-use id the call's `_meta` carries; None from a client that
    sends none."""
    meta = ctx.request_context.meta
    value = None if meta is None else (meta.model_extra or {}).get(TOOL_USE_ID_META)
    return value if isinstance(value, str) else None


def register_tools(mcp: FastMCP, api: PilotWorkApi) -> None:
    @mcp.tool()
    async def register_document(
        path: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The document's absolute path in this environment, under `/work`"
                ),
            ),
        ],
        ctx: Call,
    ) -> RegisteredDocument:
        """Register a decision document you wrote, by its file's absolute path
        under `/work` in this environment, to put it to the operator on your
        project's timeline. The file is read and parsed at once: a path outside
        `/work`, no file there, a file over 16 MiB, or a text whose front
        matter or blocks do not parse is refused with the reason, each fault
        with its line, and nothing is registered; fix the file and register it
        again. Answers `{id}`, the document's item id, which `attach_file`
        takes as `to`. Registering the same path again in this work item
        answers the same id. What the operator reads is the file as your turn
        leaves it: Pilot reads it again when your turn ends. Once you have
        registered your documents and attached what backs them, end your turn;
        never wait for the answers. When every document you registered is
        answered, Pilot writes each back in place, the answers in it, and
        continues this conversation as a new work item with a message naming
        the files; registering a revised file then makes a new document."""
        return await api.register_document(_authorization(ctx), _tool_use_id(ctx), path)

    @mcp.tool()
    async def attach_file(
        path: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The file's or the folder's absolute path in this environment,"
                    " under `/work`: a folder's every file under it"
                ),
            ),
        ],
        ctx: Call,
        to: Annotated[
            uuid.UUID | None,
            Field(
                description=(
                    "The id of the item the material backs, an item of your"
                    " project: usually the id `register_document` answered."
                    " Without it, this session's own work item"
                ),
            ),
        ] = None,
    ) -> AttachedFiles:
        """Copy material that backs a document into Pilot's record, by its
        absolute path under `/work` in this environment: a file, or a folder
        and every file under it, one attachment per file. Each is copied now,
        with this environment and its path as its source; what you change in it
        later is not seen. `to` is the id of the item the material backs,
        usually the one `register_document` just answered; without it, the
        material hangs on this session's own work item. A call that cannot copy
        every file it names — a path outside `/work`, no file there, a file
        over 16 MiB, a folder over the cap of one call, a `to` that is not an
        item of your project — attaches nothing and answers the reason. Answers
        `{ids}`, the attachments' ids, a folder's in its files' path order.
        Once you have registered your documents and attached what backs them,
        end your turn; never wait for the answers."""
        return await api.attach_file(_authorization(ctx), _tool_use_id(ctx), path, to)
