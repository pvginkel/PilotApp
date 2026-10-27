"""Pilot's MCP server (F83): its two surfaces pinned, `pilot-work`'s and
`pilot-store`'s, as a contract the sessions they are handed to are written
against, the bearer it requires, and the probes that answer without one."""

from typing import Any

import pytest
from starlette.applications import Starlette

from pilot_mcp.server import STORE_PATH, WORK_PATH
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
WORK_SURFACE = {
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

WORK_INSTRUCTIONS = (
    "Pilot, the project manager that started this session to do a work item of its"
    " project. Write each decision document your work produces as a file under"
    " `/work`, register it with `register_document` and attach what backs it with"
    " `attach_file`, then end your turn: never wait for the answers. Pilot reads"
    " each registered document again when your turn ends and puts it to the"
    " operator; once every one is answered, Pilot writes the answered files back in"
    " place and continues this conversation with a message naming them."
)

_BLOCK = {
    "description": "The block's id, `<item id>/<local id>`",
    "pattern": r"^[0-9A-Fa-f-]{36}/\S+$",
    "title": "Block",
    "type": "string",
}

_ITEM = {"format": "uuid", "title": "Item", "type": "string"}

_RECORDED = {
    "description": "What the call changed.",
    "properties": {
        "effect": {
            "description": (
                "Its effect line, `<verb> · <what>`, as it shows where the call ran"
            ),
            "title": "Effect",
            "type": "string",
        }
    },
    "required": ["effect"],
    "title": "Recorded",
    "type": "object",
}


def _optional(title: str, description: str, **string: Any) -> dict[str, Any]:
    return {
        "anyOf": [{**string, "type": "string"}, {"type": "null"}],
        "default": None,
        "description": description,
        "title": title,
    }


def _text_field(title: str, description: str) -> dict[str, Any]:
    return _optional(title, description, minLength=1)


_EFFECT = {
    "description": "Its effect line, `<verb> · <what>`, as it shows where the call ran",
    "title": "Effect",
    "type": "string",
}

_NEW_ITEM = {
    "additionalProperties": False,
    "description": "An item to add, in `timeline.json`'s shape.",
    "properties": {
        "kind": {
            "description": (
                "`decision`, `question`, `action`, `notice`, `document` or `review`"
                " for a prose item, `work` for a work item; a wait, `card_wait` or"
                " `timed_wait`, is refused: Pilot takes none yet"
            ),
            "enum": [
                "decision",
                "question",
                "action",
                "notice",
                "document",
                "review",
                "work",
                "card_wait",
                "timed_wait",
            ],
            "title": "Kind",
            "type": "string",
        },
        "title": _text_field(
            "Title",
            "The title it is born with in its file's front matter, where `markdown`"
            " gives none; a prose item without `markdown` needs it, and a work item,"
            " whose line shows it",
        ),
        "markdown": _text_field(
            "Markdown",
            "A short prose item's whole text, minted with it and parsed now: its own"
            " front-matter `title` stands, else `title` is written in",
        ),
        "step": _text_field(
            "Step",
            "The id of the plan's task it serves: a prose item's front matter where"
            " `markdown` gives none, a work item's brief",
        ),
        "urgent": {
            "default": False,
            "description": (
                "A prose item that is urgent: `urgent: true` in its front matter where"
                " `markdown` gives none"
            ),
            "title": "Urgent",
            "type": "boolean",
        },
        "for": _text_field(
            "For",
            "The handle of the person a prose item is for, in its front matter where"
            " `markdown` gives none",
        ),
        "summary": _text_field(
            "Summary",
            "A prose item's summary, in its front matter where `markdown` gives none",
        ),
        "attachments": {
            "description": (
                "What it carries, hung on it in this order: an attachment already"
                " made, by its id, or material copied in now as `attach_file` copies"
                " it, `<environment>:<path>`"
            ),
            "items": {
                "pattern": r"^([0-9A-Fa-f-]{36}|[^:\s/]+:/.*)$",
                "type": "string",
            },
            "title": "Attachments",
            "type": "array",
        },
        "repo": _optional(
            "Repo",
            "A work item's repository, `owner/Name`: Pilot makes its environment from"
            " it",
            pattern=r"^[^/\s]+/[^/\s]+$",
        ),
        "cwd": _text_field(
            "Cwd",
            "A work item's working directory in its environment, a checkout under"
            " `/work`: the repository's own, `/work/<Name>`, or one its manifest"
            " checks out beside it",
        ),
        "brief": _text_field(
            "Brief",
            "A work item's brief, its first turn, yours; Pilot appends the plan task"
            " it serves, the switch and the project's handbook",
        ),
        "agent": _text_field("Agent", "A work item's agent, where given"),
        "model": _text_field("Model", "A work item's model, where given"),
        "reasoning_effort": _text_field(
            "Reasoning Effort", "A work item's reasoning effort, where given"
        ),
    },
    "required": ["kind"],
    "title": "NewItem",
    "type": "object",
}

# Each tool: its parameters, its result and its description, the words as the
# brain reads them (TD §4.5, F86).
STORE_SURFACE = {
    "add_item": (
        {
            "$defs": {"NewItem": _NEW_ITEM},
            "properties": {
                "item": {
                    "$ref": "#/$defs/NewItem",
                    "description": "The item, in `timeline.json`'s shape",
                }
            },
            "required": ["item"],
            "title": "add_itemArguments",
            "type": "object",
        },
        {
            "description": "The item added.",
            "properties": {
                "id": {
                    **_UUID,
                    "description": "Its id, as `timeline.json` gives it",
                    "title": "Id",
                },
                "path": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": (
                        "A prose item's file, its absolute path, which you fill; none"
                        " for a work item"
                    ),
                    "title": "Path",
                },
                "state": {
                    "anyOf": [
                        {"enum": ["starting", "held"], "type": "string"},
                        {"type": "null"},
                    ],
                    "description": (
                        "A work item's session: `starting`, or `held` at the gate;"
                        " none for a prose item"
                    ),
                    "title": "State",
                },
                "held": {
                    "anyOf": [
                        {
                            "enum": ["paused", "controller_unreachable", "slot"],
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "description": (
                        "Why a held work item waits: the project is paused, the"
                        " controller is unreachable, or no slot is free; none"
                        " otherwise"
                    ),
                    "title": "Held",
                },
                "effect": _EFFECT,
            },
            "required": ["id", "path", "state", "held", "effect"],
            "title": "Added",
            "type": "object",
        },
        "Add an item to the project's timeline. A prose item is minted with its"
        " file under the project's folder, born with `title` in its front matter"
        " and `step`, `urgent`, `for` and `summary` beside it, and its `path`"
        " answered for you to fill; a short one may come whole as `markdown`,"
        " minted with it. A work item is started on add in an environment Pilot"
        " makes from `repo`, on your placement, its first turn your `brief`"
        " followed by Pilot's own lines; `state` answers whether it is `starting`"
        " or `held` at the gate, and `held` why — say so to the person. A wait, a"
        " field the kind does not take or one it needs missing, a text with no"
        " title or with faults, an attachment or a plan task not of your project,"
        " material that cannot be copied, or a start the project refuses is"
        " refused with the reason, each fault with its line, and nothing is added."
        " Answers `{id, path, state, held, effect}`.",
    ),
    "attach_file": (
        {
            "properties": {
                "source": {
                    "description": (
                        "The material's environment and its absolute path there,"
                        " `<environment>:<path>`: a file, or a folder's every file"
                        " under it"
                    ),
                    "pattern": r"^[^:\s/]+:/.*$",
                    "title": "Source",
                    "type": "string",
                },
                "to": {
                    "anyOf": [_UUID, {"type": "null"}],
                    "default": None,
                    "description": (
                        "The id of the item it hangs on, an item of your project;"
                        " none in a draft's definition chat"
                    ),
                    "title": "To",
                },
            },
            "required": ["source"],
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
                },
                "effect": _EFFECT,
            },
            "required": ["ids", "effect"],
            "title": "AttachedMaterial",
            "type": "object",
        },
        "Copy outside material into Pilot's record — a design record whole or in"
        " part, a file the person points you at — from any environment of the"
        " fleet, by `<environment>:<path>`: a file, or a folder and every file"
        " under it, one attachment per file, all of one batch, each with its"
        " source. Each is copied now; what changes there later is not seen. `to`"
        " is the item it hangs on; in a draft's definition chat give none: the"
        " material hangs on nothing until Create project hangs it on the opening."
        " A call that cannot copy every file it names — no `to` outside a draft's"
        " definition chat, a `to` not of your project, an environment the"
        " controller does not have, a path outside `/work`, no file there, a file"
        " over 16 MiB, a folder over the cap of one call — attaches nothing and"
        " answers the reason. Answers `{ids, effect}`, the attachments' ids, a"
        " folder's in its files' path order, and the call's effect line.",
    ),
    "answer": (
        {
            "properties": {
                "block": {
                    "description": (
                        "The block's id, `<item id>/<local id>`; in a draft's"
                        " definition chat, `project.md/<local id>` for a block of"
                        " the draft"
                    ),
                    "pattern": r"^(?:[0-9A-Fa-f-]{36}|project\.md)/\S+$",
                    "title": "Block",
                    "type": "string",
                },
                "value": {
                    "description": (
                        "The answer: an option's label, `Agree`, `Yes`, `No`, the"
                        " person's own words, or `deferred` with `to`"
                    ),
                    "minLength": 1,
                    "title": "Value",
                    "type": "string",
                },
                "for": {
                    "description": "The handle of the person whose answer it is",
                    "minLength": 1,
                    "title": "For",
                    "type": "string",
                },
                "note": _optional("Note", "Their words, as they gave them"),
                "to": _optional(
                    "To",
                    "With `deferred`: the id of the plan's task the block returns"
                    " at, or `plan`, the project's end",
                ),
            },
            "required": ["block", "value", "for"],
            "title": "answerArguments",
            "type": "object",
        },
        _RECORDED,
        "Record a person's answer to a block, given in the chat, on their behalf:"
        " `for` names them by handle, `value` is the answer and `note` their words."
        " A deferral they ask for is `deferred` with `to`. It is their answer,"
        " through the chat, which they can undo; it replaces the block's answer,"
        " yours included, while the item is open, and the answer to an item's one"
        " block is its Done. In a draft's definition chat, a block of the draft is"
        " `project.md/<local id>`; its answer has no undo, and answering it again"
        " replaces it. A block not of your project, a block of `project.md`"
        " outside its draft's definition chat, a `for` that names no person, an"
        " answer the block does not take, an item that is done, or a registered"
        " document whose file has not been read yet is refused with the reason,"
        " and nothing is recorded. Answers `{effect}`, the call's effect line.",
    ),
    "mark": (
        {
            "properties": {
                "item": {**_ITEM, "description": "The item's id"},
                "mark": {
                    "description": (
                        "`done` on a document, `read` on a notice, `reviewed` on"
                        " a review"
                    ),
                    "enum": ["done", "read", "reviewed"],
                    "title": "Mark",
                    "type": "string",
                },
                "for": _optional(
                    "For",
                    "The handle of the person the mark is for; without it, your"
                    " own `done`",
                    minLength=1,
                ),
            },
            "required": ["item", "mark"],
            "title": "markArguments",
            "type": "object",
        },
        _RECORDED,
        "Mark an item on behalf of the person `for` names: `done` on a document,"
        " its unanswered blocks answered with their recommendations as Done"
        " answers them; `read` on a notice; `reviewed` on a review. Without `for`,"
        " the mark is your own, and only `done`, on a document you settled whole,"
        " every block of it answered. An item not of your project, a `for` that"
        " names no person, a mark its kind does not take, an item that is done, a"
        " document with a block neither answered nor recommended, or, without"
        " `for`, one with a block unanswered is refused with the reason, and"
        " nothing is marked. Answers `{effect}`, the call's effect line.",
    ),
    "stop_work": (
        {
            "properties": {"item": {**_ITEM, "description": "The work item's id"}},
            "required": ["item"],
            "title": "stop_workArguments",
            "type": "object",
        },
        _RECORDED,
        "Stop a work item's session that runs, is starting or is held at the gate:"
        " a runaway session, or one a correction makes moot. A turn in flight is"
        " interrupted and the conversation kept; the item shows it stopped by"
        " Pilot, and a person can resume it. An item not of your project, one that"
        " is no work item, or one whose session is not running, starting or held"
        " is refused with the reason. Answers `{effect}`, the call's effect line.",
    ),
    "finish": (
        {"properties": {}, "title": "finishArguments", "type": "object"},
        _RECORDED,
        "Finish the project, as the project menu's Finish does: only on the"
        " operator's Yes to the decision you asked once the plan's last task was"
        " done. Every open item is closed unanswered, auto pilot is switched off"
        " and a pause lifted, and every session of the project that runs, is"
        " starting or is held is stopped, this one's turn among them once the call"
        " is recorded. A project that is a draft, finished or archived is refused"
        " with the reason. Answers `{effect}`, the call's effect line.",
    ),
    "ask_writer": (
        {
            "properties": {
                "document": {
                    "description": "The registered document's item id",
                    "format": "uuid",
                    "title": "Document",
                    "type": "string",
                },
                "block": {
                    **_BLOCK,
                    "description": (
                        "The block's id, `<item id>/<local id>`, a block of `document`"
                    ),
                },
                "question": {
                    "description": "The question, in the words the writer is to read",
                    "minLength": 1,
                    "title": "Question",
                    "type": "string",
                },
            },
            "required": ["document", "block", "question"],
            "title": "ask_writerArguments",
            "type": "object",
        },
        {
            "description": "The document's blocks its writer is asked about.",
            "properties": {
                "blocks": {
                    "description": (
                        "Their local ids, the block this call asked about among"
                        " them, in their order in the document"
                    ),
                    "items": {"type": "string"},
                    "title": "Blocks",
                    "type": "array",
                }
            },
            "required": ["blocks"],
            "title": "Asked",
            "type": "object",
        },
        "Ask the writer of a registered document about one of its blocks that you"
        " cannot read and the record does not answer: what it asks, which option"
        " the writer means, what a thing it names is. Only the pre-ruling pass"
        " asks, once a block. The question is recorded on the document with your"
        " turn, and the document's line says that Pilot asked its writer. A"
        " document that is no registered document of your project or is done, a"
        " block not of it, answered or asked about already, or a call from the"
        " chat is refused with the reason, and nothing is recorded. Answers"
        " `{blocks}`, the document's blocks its writer is asked about.",
    ),
}

STORE_INSTRUCTIONS = (
    "Pilot, the project manager, whose brain this session is, for the one project"
    " `$PILOT_PROJECT` names. These tools are the one door to Pilot's record"
    " beyond the files of the project's folder: each acts on that project alone,"
    " and only while your turn runs. An `item` is an item's id and a `block` a"
    " block's, `<item id>/<local id>`: the item's id as `timeline.json` gives it,"
    " the block's local id as its fence does; `add_item` alone takes the item"
    " itself, in `timeline.json`'s shape. A call the record refuses changes"
    " nothing and answers the reason."
)

_SURFACES = [
    pytest.param(WORK_PATH, WORK_SURFACE, WORK_INSTRUCTIONS, id="pilot-work"),
    pytest.param(STORE_PATH, STORE_SURFACE, STORE_INSTRUCTIONS, id="pilot-store"),
]

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
    @pytest.mark.parametrize(("path", "pinned", "instructions"), _SURFACES)
    async def test_the_tools_are_pinned(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        path: str,
        pinned: dict[str, Any],
        instructions: str,
    ) -> None:
        async with mcp_session(mcp_app, path=path) as (session, _):
            tools = (await session.list_tools()).tools

        surface = {
            tool.name: (
                tool.inputSchema,
                tool.outputSchema,
                _words(tool.description or ""),
            )
            for tool in tools
        }
        assert surface == pinned
        assert routes.calls == []

    @pytest.mark.parametrize(("path", "pinned", "instructions"), _SURFACES)
    async def test_the_server_is_pilot_with_its_instructions(
        self,
        mcp_app: Starlette,
        path: str,
        pinned: dict[str, Any],
        instructions: str,
    ) -> None:
        async with mcp_session(mcp_app, path=path) as (_, initialized):
            pass

        assert initialized.serverInfo.name == "pilot"
        assert initialized.instructions == instructions


@pytest.mark.anyio
class TestTheBearer:
    @pytest.mark.parametrize(
        "authorization",
        [None, "Bearer ", "Bearer   ", "bearer worker-token", "Basic worker-token"],
    )
    @pytest.mark.parametrize("path", [WORK_PATH, STORE_PATH])
    async def test_a_request_with_no_bearer_is_refused(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        authorization: str | None,
        path: str,
    ) -> None:
        headers = {} if authorization is None else {"Authorization": authorization}
        async with http_client(mcp_app, headers) as http:
            response = await http.post(path, json=_INITIALIZE, headers=_ACCEPT)

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

    @pytest.mark.parametrize(("path", "pinned", "instructions"), _SURFACES)
    async def test_a_bearer_is_admitted_without_its_check(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        path: str,
        pinned: dict[str, Any],
        instructions: str,
    ) -> None:
        headers = {"Authorization": "Bearer a-token-no-session-has"}
        async with mcp_session(mcp_app, headers, path) as (session, _):
            tools = (await session.list_tools()).tools

        assert {tool.name for tool in tools} == set(pinned)
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
