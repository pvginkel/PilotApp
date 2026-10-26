"""`pilot-work`'s tools (F85, FM §5 step 1), a worker's, and `pilot-store`'s
(F86, TD §4.5), the brain's, each one call to its route.

A tool's docstring is the description the session reads, and each parameter's
is in its annotation: they are the surface, not commentary
(`tests/pilot_mcp/test_server.py` pins them). The bearer a call carries is the
API's to resolve; a tool passes it on as it came, with the tool-use id Claude
Code sends in the call's `_meta`, which the call's effect names.
"""

import functools
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import Field
from starlette.requests import Request

from pilot_mcp.api import (
    Asked,
    AttachedFiles,
    Mark,
    PilotStoreApi,
    PilotWorkApi,
    Recorded,
    RegisteredDocument,
)

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


BLOCK_ID = r"^[0-9A-Fa-f-]{36}/\S+$"
"""A block's id (TD §4.9), `<item id>/<local id>`."""

_FOR = "for"


def _taking_for[**P, R](tool: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """`tool`, whose parameter `for_` the session names `for`: FastMCP calls a
    tool by its parameters' aliases, and `for` names no Python parameter."""

    @functools.wraps(tool)
    async def call(*args: Any, **arguments: Any) -> R:
        arguments["for_"] = arguments.pop(_FOR)
        return await tool(*args, **arguments)

    return call


def register_work_tools(mcp: FastMCP, api: PilotWorkApi) -> None:
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


def register_store_tools(mcp: FastMCP, api: PilotStoreApi) -> None:
    @mcp.tool()
    @_taking_for
    async def answer(
        block: Annotated[
            str,
            Field(
                pattern=BLOCK_ID,
                description="The block's id, `<item id>/<local id>`",
            ),
        ],
        value: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The answer: an option's label, `Agree`, `Yes`, `No`, the"
                    " person's own words, or `deferred` with `to`"
                ),
            ),
        ],
        for_: Annotated[
            str,
            Field(
                alias=_FOR,
                min_length=1,
                description="The handle of the person whose answer it is",
            ),
        ],
        ctx: Call,
        note: Annotated[
            str | None,
            Field(description="Their words, as they gave them"),
        ] = None,
        to: Annotated[
            str | None,
            Field(
                description=(
                    "With `deferred`: the id of the plan's task the block returns"
                    " at, or `plan`, the project's end"
                ),
            ),
        ] = None,
    ) -> Recorded:
        """Record a person's answer to a block, given in the chat, on their
        behalf: `for` names them by handle, `value` is the answer and `note`
        their words. A deferral they ask for is `deferred` with `to`. It is
        their answer, through the chat, which they can undo; it replaces the
        block's answer, yours included, while the item is open, and the answer
        to an item's one block is its Done. A block not of your project, a
        `for` that names no person, an answer the block does not take, an
        item that is done, or a registered document whose file has not been
        read yet is refused with the reason, and nothing is recorded. Answers
        `{effect}`, the call's effect line."""
        return await api.answer(
            _authorization(ctx),
            _tool_use_id(ctx),
            block=block,
            value=value,
            person=for_,
            note=note,
            to=to,
        )

    @mcp.tool()
    @_taking_for
    async def mark(
        item: Annotated[uuid.UUID, Field(description="The item's id")],
        mark: Annotated[
            Mark,
            Field(
                description=(
                    "`done` on a document, `read` on a notice, `reviewed` on a review"
                )
            ),
        ],
        ctx: Call,
        for_: Annotated[
            str | None,
            Field(
                alias=_FOR,
                min_length=1,
                description=(
                    "The handle of the person the mark is for; without it, your"
                    " own `done`"
                ),
            ),
        ] = None,
    ) -> Recorded:
        """Mark an item on behalf of the person `for` names: `done` on a
        document, its unanswered blocks answered with their recommendations as
        Done answers them; `read` on a notice; `reviewed` on a review. Without
        `for`, the mark is your own, and only `done`, on a document you settled
        whole, every block of it answered. An item not of your project, a
        `for` that names no person, a mark its kind does not take, an item
        that is done, a document with a block neither answered nor
        recommended, or, without `for`, one with a block unanswered is refused
        with the reason, and nothing is marked. Answers `{effect}`, the call's
        effect line."""
        return await api.mark(
            _authorization(ctx), _tool_use_id(ctx), item=item, mark=mark, person=for_
        )

    @mcp.tool()
    async def stop_work(
        item: Annotated[uuid.UUID, Field(description="The work item's id")],
        ctx: Call,
    ) -> Recorded:
        """Stop a work item's session that runs, is starting or is held at the
        gate: a runaway session, or one a correction makes moot. A turn in
        flight is interrupted and the conversation kept; the item shows it
        stopped by Pilot, and a person can resume it. An item not of your
        project, one that is no work item, or one whose session is not
        running, starting or held is refused with the reason. Answers
        `{effect}`, the call's effect line."""
        return await api.stop_work(_authorization(ctx), _tool_use_id(ctx), item=item)

    @mcp.tool()
    async def finish(ctx: Call) -> Recorded:
        """Finish the project, as the project menu's Finish does: only on the
        operator's Yes to the decision you asked once the plan's last task was
        done. Every open item is closed unanswered, auto pilot is switched off
        and a pause lifted, and every session of the project that runs, is
        starting or is held is stopped, this one's turn among them once the
        call is recorded. A project that is a draft, finished or archived is
        refused with the reason. Answers `{effect}`, the call's effect line."""
        return await api.finish(_authorization(ctx), _tool_use_id(ctx))

    @mcp.tool()
    async def ask_writer(
        document: Annotated[
            uuid.UUID, Field(description="The registered document's item id")
        ],
        block: Annotated[
            str,
            Field(
                pattern=BLOCK_ID,
                description=(
                    "The block's id, `<item id>/<local id>`, a block of `document`"
                ),
            ),
        ],
        question: Annotated[
            str,
            Field(
                min_length=1,
                description="The question, in the words the writer is to read",
            ),
        ],
        ctx: Call,
    ) -> Asked:
        """Ask the writer of a registered document about one of its blocks
        that you cannot read and the record does not answer: what it asks,
        which option the writer means, what a thing it names is. Only the
        pre-ruling pass asks, once a block. The question is recorded on the
        document with your turn, and the document's line says that Pilot asked
        its writer. A document that is no registered document of your project
        or is done, a block not of it, answered or asked about already, or a
        call from the chat is refused with the reason, and nothing is
        recorded. Answers `{blocks}`, the document's blocks its writer is
        asked about."""
        return await api.ask_writer(
            _authorization(ctx),
            _tool_use_id(ctx),
            document=document,
            block=block,
            question=question,
        )
