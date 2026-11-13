"""Pilot's MCP server (F83): its two surfaces pinned, `pilot-work`'s and
`pilot-store`'s, as a contract the sessions they are handed to are written
against, the bearer it requires, the probes that answer without one, and a
script's lone call with no MCP client (F84.1); and its third,
`pilot-projects` (F150.1 to F150.4), pinned with its words, its door and the
two headers that name its caller."""

import json
import re
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette

from app import models
from pilot_mcp.api import ENVIRONMENT_HEADER, SESSION_HEADER
from pilot_mcp.server import PROJECTS_PATH, STORE_PATH, WORK_PATH
from tests.support.pilot_mcp import (
    BEARER,
    PROJECTS_HEADERS,
    PROJECTS_TOKEN,
    TOKEN,
    ApiRoutes,
    TokenEndpoint,
    http_client,
    mcp_session,
)

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

_STEP_STATE = {"enum": ["pending", "active", "done"], "type": "string"}

_PROGRESS = {
    "$defs": {
        "PublishedStep": {
            "description": "A step of your work item's list as it stands.",
            "properties": {
                "code": {
                    "description": "Your name for the step",
                    "title": "Code",
                    "type": "string",
                },
                "label": {
                    "description": "Its words on the tile",
                    "title": "Label",
                    "type": "string",
                },
                "state": {
                    **_STEP_STATE,
                    "description": "`pending`, `active` or `done`",
                    "title": "State",
                },
            },
            "required": ["code", "label", "state"],
            "title": "PublishedStep",
            "type": "object",
        }
    },
    "description": "Your work item's list of steps as it stands.",
    "properties": {
        "steps": {
            "description": "Its steps, in order",
            "items": {"$ref": "#/$defs/PublishedStep"},
            "title": "Steps",
            "type": "array",
        }
    },
    "required": ["steps"],
    "title": "Progress",
    "type": "object",
}

# Each tool: its parameters, its result and its description, the words as the
# worker reads them (FM §5 step 1, F65.3, F85, F85.3, F85.4).
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
    "set_progress": (
        {
            "$defs": {
                "Step": {
                    "additionalProperties": False,
                    "description": "A step of your work item's list.",
                    "properties": {
                        "code": {
                            "description": (
                                "Your name for the step, unique in the list, at"
                                " most 64 characters: `set_progress_step` takes it"
                            ),
                            "maxLength": 64,
                            "minLength": 1,
                            "title": "Code",
                            "type": "string",
                        },
                        "label": {
                            "description": (
                                "The step's words on the tile, at most 120 characters"
                            ),
                            "maxLength": 120,
                            "minLength": 1,
                            "title": "Label",
                            "type": "string",
                        },
                        "state": {
                            "anyOf": [_STEP_STATE, {"type": "null"}],
                            "default": None,
                            "description": (
                                "`pending`, `active` or `done`; without it, a code"
                                " already on the list keeps its state and a new one"
                                " starts `pending`"
                            ),
                            "title": "State",
                        },
                    },
                    "required": ["code", "label"],
                    "title": "Step",
                    "type": "object",
                }
            },
            "properties": {
                "steps": {
                    "description": (
                        "Your work item's steps, in order, at most 100; `[]` removes"
                        " the list"
                    ),
                    "items": {"$ref": "#/$defs/Step"},
                    "maxItems": 100,
                    "title": "Steps",
                    "type": "array",
                }
            },
            "required": ["steps"],
            "title": "set_progressArguments",
            "type": "object",
        },
        _PROGRESS,
        "Publish your work item's steps as your run moves through them, shown on its"
        " tile in Pilot: the whole list, in order, each step a `code`, your name for"
        " it, a `label`, its words, and a `state`, `pending`, `active` or `done`."
        " The list replaces the one standing: a code already on it keeps its state"
        " where you give none, a new code starts `pending`, a code left out goes, and"
        " `[]` removes the list. Where the work grows, add a step; a second round of"
        " a step is a step of its own. Pilot stamps each step's start and end by its"
        " own clock. An empty or repeated code, an empty label, a state outside the"
        " three, a code over 64 characters, a label over 120 or a list over 100"
        " steps is refused with the reason, and nothing changes. Answers `{steps}`,"
        " the list as it stands.",
    ),
    "set_progress_step": (
        {
            "properties": {
                "code": {
                    "description": "The code of a step on your work item's list",
                    "maxLength": 64,
                    "minLength": 1,
                    "title": "Code",
                    "type": "string",
                },
                "state": {
                    **_STEP_STATE,
                    "description": "`pending`, `active` or `done`",
                    "title": "State",
                },
            },
            "required": ["code", "state"],
            "title": "set_progress_stepArguments",
            "type": "object",
        },
        _PROGRESS,
        "Move one step of your work item's list to `pending`, `active` or `done`, by"
        " its code, as your run moves through it; every step keeps its place. Pilot"
        " stamps each step's start and end by its own clock. A code not on the list"
        " or a state outside the three is refused with the reason, and nothing"
        " changes; `set_progress` adds a step. Answers `{steps}`, the list as it"
        " stands.",
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


def _optional_list(title: str, description: str) -> dict[str, Any]:
    return {
        "anyOf": [
            {"items": {"minLength": 1, "type": "string"}, "type": "array"},
            {"type": "null"},
        ],
        "default": None,
        "description": description,
        "title": title,
    }


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
                " for a prose item, `work` for a work item, `card_wait` or"
                " `timed_wait` for a wait"
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
            " gives none; a prose item without `markdown` needs it, and a work item"
            " and a wait, whose line shows it",
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
        "claims": {
            "description": (
                "The actions of workers' documents a work item does that you"
                " claimed, by their blocks' ids, `<item id>/<local id>`: each"
                " block's line names this work item, and the job after its turn"
                " names them for their `done`"
            ),
            "items": {"pattern": r"^[0-9A-Fa-f-]{36}/\S+$", "type": "string"},
            "title": "Claims",
            "type": "array",
        },
        "cards": _optional_list(
            "Cards",
            "A card wait's cards, one or more ticket ids, each named once: it fires"
            " whenever one of them enters one of `states`",
        ),
        "states": _optional_list(
            "States",
            "A card wait's states, one or more of the tracker's names, each named"
            " once, matched whatever their case: list the states that derail the"
            " wait beside the one you hope for, since nothing else fires it",
        ),
        "due_at": _optional(
            "Due At",
            "A timed wait's due time, with its offset, ahead of now: it fires once"
            " when it comes",
            format="date-time",
        ),
        "researches": {
            "description": (
                "The blocks of workers' documents you left unanswered while a work"
                " item checks a fact their answers rest on, by their ids, `<item"
                " id>/<local id>`: each block's line names this work item, and the"
                " job after its turn names them for you to route"
            ),
            "items": {"pattern": r"^[0-9A-Fa-f-]{36}/\S+$", "type": "string"},
            "title": "Researches",
            "type": "array",
        },
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
                        " for a work item or a wait"
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
                        " none for a prose item or a wait"
                    ),
                    "title": "State",
                },
                "held": {
                    "anyOf": [
                        {
                            "enum": [
                                "week_halt",
                                "five_hour_halt",
                                "paused",
                                "controller_unreachable",
                                "slot",
                            ],
                            "type": "string",
                        },
                        {"type": "null"},
                    ],
                    "description": (
                        "Why a held work item waits: the week's or the five-hour"
                        " usage halt holds work items, the project is paused, the"
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
        " or `held` at the gate, and `held` why — say so to the person. A work"
        " item that does actions you claimed names them in `claims`: each stays"
        " open and yours until its `done`, its line naming this work item, the"
        " latest that names it. A work item that checks a fact for blocks you"
        " left unanswered names them in `researches`: each line names this work"
        " item, the latest that names it, and the job after its turn gives them"
        " to you to route. A wait is recorded with its `title`, a card wait's"
        " `cards` and `states` or a timed wait's `due_at`, and is fixed from then"
        " on: Pilot fires it and never closes it; you close it with your own"
        " `mark` `done` and its `note`, and to change it you close it and add"
        " another. A field the kind does not take or one it needs missing, a text"
        " with no title or with faults, a wait's list empty or naming one twice, a"
        " card that is no ticket id, a due time not ahead, an attachment or a plan"
        " task not of your project, material that cannot be copied, a claim that"
        " is not an open action of a registered document of your project, a"
        " research of a block that is answered or not in an open registered"
        " document of your project, or a start the project refuses is refused"
        " with the reason, each fault with its line, and nothing is added."
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
                        "`done` on a document or a wait, `read` on a notice,"
                        " `reviewed` on a review"
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
                "note": _optional(
                    "Note",
                    "Your words at a wait's close, shown on its line: what you"
                    " read and when, and the action after it started",
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
        " every block of it answered, and on a registered document of one block,"
        " whatever its kind, once that block is answered or deferred: a claimed"
        " action counts once its `done` is written; and on an open wait, with your"
        " `note`, which closes it for good. A registered document's Done writes its"
        " answers back and resumes its worker once none of its run's documents is"
        " open. An item not of your project, a `for` that names no person, a mark"
        " its kind does not take, an item that is done, a document with a block"
        " neither answered nor recommended, or, without `for`, one with a block"
        " unanswered or a claimed action not yet done, a wait's mark with `for` or"
        " without a `note`, or a `note` on any other item is refused with the"
        " reason, and nothing is marked. Answers `{effect}`, the call's effect"
        " line.",
    ),
    "stop_work": (
        {
            "properties": {"item": {**_ITEM, "description": "The work item's id"}},
            "required": ["item"],
            "title": "stop_workArguments",
            "type": "object",
        },
        _RECORDED,
        "Stop a work item's session that runs, is starting or is held at the gate,"
        " or one whose turn ended under a usage halt or the project's pause, to be"
        " carried on once it lifts: a runaway session, or one a correction makes"
        " moot. A turn in flight is interrupted and the conversation kept; the item"
        " shows it stopped by Pilot, and a person can resume it. An item not of"
        " your project, one that is no work item, a job of yours, or one whose"
        " session is none of these is refused with the reason. Answers `{effect}`,"
        " the call's effect line.",
    ),
    "finish": (
        {
            "properties": {
                "archive": {
                    "default": False,
                    "description": (
                        "True on the operator's Finish and archive: the project is"
                        " archived with the finish. Without it, the app asks them"
                        " whether to archive it"
                    ),
                    "title": "Archive",
                    "type": "boolean",
                }
            },
            "title": "finishArguments",
            "type": "object",
        },
        _RECORDED,
        "Finish the project, as the project menu's Finish does: only on the"
        " operator's Finish, or Finish and archive, on the decision you asked"
        " once the plan's last task was done. Every open item is closed unanswered, auto pilot is switched off"
        " and a pause lifted, and every session of the project that runs, is"
        " starting or is held is stopped, this one's turn among them once the call"
        " is recorded. The app then asks the operator whether to archive the"
        " project. With `archive`, only where they chose Finish and archive on"
        " that decision, the project is archived in the same act, as their"
        " Archive, and that question is not asked. A project that is a draft,"
        " finished or archived is refused with the reason. Answers `{effect}`,"
        " the call's effect line.",
    ),
    "ask_writer": (
        {
            "properties": {
                "block": {
                    **_BLOCK,
                    "description": (
                        "The block's id, `<item id>/<local id>`, its item a"
                        " registered document"
                    ),
                },
                "question": {
                    "description": "The question, in the words the writer is to read",
                    "minLength": 1,
                    "title": "Question",
                    "type": "string",
                },
            },
            "required": ["block", "question"],
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
        " asks, once a block, in one round per worker turn: the pass's questions"
        " go to the writer together when its turn ends, and the pass after the"
        " writer's answer, or a retry of a pass that asked, asks nothing. The"
        " question is recorded on the document with your turn, and the"
        " document's line says that Pilot asked its writer. A block whose item"
        " is no registered document of your project or is done, one answered or"
        " asked about already, a call from the chat, or a call in a pass that"
        " asks nothing is refused with the reason, and nothing is recorded."
        " Answers `{blocks}`, the document's blocks its writer is asked about.",
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


_SET_PROGRESS = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "set_progress",
        "arguments": {
            "steps": [
                {"code": "P1.code", "label": "P1 · the client", "state": "done"},
                {"code": "P1.review", "label": "P1 · review", "state": "active"},
                {"code": "test", "label": "Test"},
            ]
        },
    },
}

_SCRIPTS_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
"""Every header a script's call sends: the suite's shared ones are not taken,
so that the test witnesses what the transport admits."""


def _scripts_headers_with(name: str, value: str | None) -> dict[str, str]:
    """A script's headers with `name` set to `value`, or left out for None."""
    headers = {key: kept for key, kept in _SCRIPTS_HEADERS.items() if key != name}
    return headers if value is None else {**headers, name: value}


async def _scripts_post(app: Starlette, headers: dict[str, str]) -> httpx.Response:
    """`_SET_PROGRESS` POSTed alone to `pilot-work`, with no `initialize` before
    it, under `headers` and httpx's defaults alone."""
    async with http_client(app) as http, app.router.lifespan_context(app):
        return await http.post(
            WORK_PATH, content=json.dumps(_SET_PROGRESS).encode(), headers=headers
        )


@pytest.mark.anyio
class TestAScriptsCall:
    """A script the session runs calls a tool with no MCP client (F84.1): one
    JSON-RPC `tools/call` POSTed to `$PILOT_MCP_URL` under `$PILOT_TOKEN`, as
    AIWF-128's client will."""

    async def test_a_lone_tools_call_is_answered_with_the_list_on_the_events_data_line(
        self, mcp_app: Starlette, routes: ApiRoutes, worker: models.Session
    ) -> None:
        response = await _scripts_post(mcp_app, _SCRIPTS_HEADERS)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        (data,) = [
            line.removeprefix("data:").strip()
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        answer = json.loads(data)
        assert (answer["jsonrpc"], answer["id"]) == ("2.0", 1)
        assert answer["result"]["isError"] is False
        assert answer["result"]["structuredContent"] == {
            "steps": [
                {"code": "P1.code", "label": "P1 · the client", "state": "done"},
                {"code": "P1.review", "label": "P1 · review", "state": "active"},
                {"code": "test", "label": "Test", "state": "pending"},
            ]
        }
        [(request, _)] = routes.calls
        assert (request.method, request.url.path) == (
            "PUT",
            "/tools/pilot-work/progress",
        )
        assert request.headers["authorization"] == f"Bearer {TOKEN}"

    @pytest.mark.parametrize(
        "accept",
        ["application/json", "text/event-stream", None],
        ids=["no-event-stream", "no-json", "none"],
    )
    async def test_a_call_not_accepting_both_json_and_the_event_stream_is_refused(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
        accept: str | None,
    ) -> None:
        """Without its own `Accept`, httpx sends `*/*`."""
        response = await _scripts_post(mcp_app, _scripts_headers_with("Accept", accept))

        assert response.status_code == 406
        assert response.json()["error"]["message"] == (
            "Not Acceptable: Client must accept both application/json and"
            " text/event-stream"
        )
        assert routes.calls == []

    @pytest.mark.parametrize("content_type", ["text/plain", None], ids=["text", "none"])
    async def test_a_call_whose_body_is_not_said_to_be_json_is_refused(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        worker: models.Session,
        content_type: str | None,
    ) -> None:
        """Refused by the SDK's transport security, ahead of the transport's
        own 415."""
        response = await _scripts_post(
            mcp_app, _scripts_headers_with("Content-Type", content_type)
        )

        assert (response.status_code, response.text) == (
            400,
            "Invalid Content-Type header",
        )
        assert routes.calls == []


_PROJECT = {
    "description": (
        "The project's id or its folder: `draft-<number>` while it is a draft, its"
        " slug once it is created. A draft's folder does not survive Create"
        " project, which gives the project its slug: hold a draft by its id across"
        " it"
    ),
    "minLength": 1,
    "title": "Project",
    "type": "string",
}

_ID = {
    **_UUID,
    "description": "Its id, which names it for good",
    "title": "Id",
}

_FOLDER = {
    "description": (
        "Its folder, the first segment of its files' paths: `draft-<number>` while"
        " a draft, its slug once created"
    ),
    "title": "Folder",
    "type": "string",
}

_NAME = {
    "anyOf": [{"type": "string"}, {"type": "null"}],
    "description": "Its name; none while a draft has no title",
    "title": "Name",
}

_STATE = {
    "description": (
        "`draft` until Create project, then `open`, and `finished` once finished"
    ),
    "enum": ["draft", "open", "finished"],
    "title": "State",
    "type": "string",
}

_STATUS = {
    "anyOf": [
        {
            "enum": [
                "running",
                "waiting_on_you",
                "waiting_on_event",
                "done",
                "idle",
                "pausing",
                "paused",
            ],
            "type": "string",
        },
        {"type": "null"},
    ],
    "description": (
        "`paused`, or `pausing` while a turn of its work still runs; else"
        " `running` while Pilot or a work item of the project works,"
        " `waiting_on_you` while an open item waits on a member,"
        " `waiting_on_event` while it waits on a card or a time, `done` once every"
        " step of its plan is done, `idle` otherwise; none for a draft and a"
        " finished project"
    ),
    "title": "Status",
}

# Each tool: its parameters, its result and its description, the words as a
# session anywhere in the fleet reads them (F150.3, F150.4, F150.6, F150.7).
PROJECTS_SURFACE = {
    "list_projects": (
        {
            "properties": {
                "archived": {
                    "default": False,
                    "description": (
                        "True for the archived projects; false, the default, for"
                        " every other"
                    ),
                    "title": "Archived",
                    "type": "boolean",
                }
            },
            "title": "list_projectsArguments",
            "type": "object",
        },
        {
            "$defs": {
                "ListedProject": {
                    "description": "A project Pilot manages, as the list shows it.",
                    "properties": {
                        "id": _ID,
                        "folder": _FOLDER,
                        "name": _NAME,
                        "state": _STATE,
                        "status": _STATUS,
                    },
                    "required": ["id", "folder", "name", "state", "status"],
                    "title": "ListedProject",
                    "type": "object",
                }
            },
            "description": "The projects Pilot manages, of one list.",
            "properties": {
                "projects": {
                    "description": "A row per project, in the order they were started",
                    "items": {"$ref": "#/$defs/ListedProject"},
                    "title": "Projects",
                    "type": "array",
                }
            },
            "required": ["projects"],
            "title": "Projects",
            "type": "object",
        },
        "List the projects Pilot manages, drafts included, in the order they were"
        " started: each one's id, folder, name, state and status. Without"
        " `archived` it lists every project that is not archived; with it, the"
        " archived ones alone. A project's `id` or `folder` is what every other"
        " tool takes as `project`.",
    ),
    "get_project": (
        {
            "properties": {"project": _PROJECT},
            "required": ["project"],
            "title": "get_projectArguments",
            "type": "object",
        },
        {
            "$defs": {
                "PlanProgress": {
                    "description": "Where the project's plan stands.",
                    "properties": {
                        "done": {
                            "description": "The plan's steps done",
                            "title": "Done",
                            "type": "integer",
                        },
                        "total": {
                            "description": "The plan's steps",
                            "title": "Total",
                            "type": "integer",
                        },
                        "in_progress": {
                            "description": (
                                "The titles of the steps in progress, in the plan's"
                                " order"
                            ),
                            "items": {"type": "string"},
                            "title": "In Progress",
                            "type": "array",
                        },
                    },
                    "required": ["done", "total", "in_progress"],
                    "title": "PlanProgress",
                    "type": "object",
                },
                "RunningWork": {
                    "description": (
                        "A work item of the project that runs or waits to start."
                    ),
                    "properties": {
                        "seq": {
                            "description": "Its number among the project's items",
                            "title": "Seq",
                            "type": "integer",
                        },
                        "title": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "description": "Its title",
                            "title": "Title",
                        },
                        "environment": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
                            "description": (
                                "The name of the environment it runs in; none while"
                                " it waits to start"
                            ),
                            "title": "Environment",
                        },
                    },
                    "required": ["seq", "title", "environment"],
                    "title": "RunningWork",
                    "type": "object",
                },
            },
            "description": "The head of a project Pilot manages.",
            "properties": {
                "id": _ID,
                "folder": _FOLDER,
                "name": _NAME,
                "state": _STATE,
                "archived": {
                    "description": (
                        "Whether it is archived: an archived project's files are"
                        " not read"
                    ),
                    "title": "Archived",
                    "type": "boolean",
                },
                "status": _STATUS,
                "autopilot": {
                    "description": "Whether auto pilot is on",
                    "title": "Autopilot",
                    "type": "boolean",
                },
                "members": {
                    "description": "Its members' handles, in the order they joined",
                    "items": {"type": "string"},
                    "title": "Members",
                    "type": "array",
                },
                "progress": {"$ref": "#/$defs/PlanProgress"},
                "running_work": {
                    "description": (
                        "Its work items that run or wait to start, in their order"
                    ),
                    "items": {"$ref": "#/$defs/RunningWork"},
                    "title": "Running Work",
                    "type": "array",
                },
                "open_items": {
                    "description": (
                        "The count of its open items, `running_work` not counted"
                    ),
                    "title": "Open Items",
                    "type": "integer",
                },
                "url": {
                    "description": "Its page in Pilot's app",
                    "title": "Url",
                    "type": "string",
                },
            },
            "required": [
                "id",
                "folder",
                "name",
                "state",
                "archived",
                "status",
                "autopilot",
                "members",
                "progress",
                "running_work",
                "open_items",
                "url",
            ],
            "title": "ProjectHead",
            "type": "object",
        },
        "Read the head of a project Pilot manages, by its id or its folder: its"
        " state and status, whether auto pilot is on, its members' handles, where"
        " its plan stands, its work items that run, each with its number, title"
        " and environment, the count of its open items and its page in Pilot's"
        " app. It answers no step or note of the plan and no file's content. A"
        " project no id or folder names is refused.",
    ),
}

PROJECTS_INSTRUCTIONS = (
    "Pilot, the project manager, and its projects. These tools read a project"
    " Pilot manages, its documents and its items, and start one. Load the skill"
    " `kubecoder:pilot-usage` before you use them: it maps a project's files and"
    " says which of them answers which question."
)

_INSIDE_WORDS = re.compile(r"\b(brain|stor(e|es|ed|ing)|record\w*|trees?)\b", re.I)
"""Pilot's own words for its inside, which mean nothing outside it (F150.3)."""


def _texts(value: Any) -> list[str]:
    """Every string of a schema: its descriptions, titles and names."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in [key, *_texts(item)]]
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    return []


@pytest.mark.anyio
class TestTheProjectsSurface:
    async def test_the_tools_are_pinned(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
    ) -> None:
        async with mcp_session(projects_app, PROJECTS_HEADERS, PROJECTS_PATH) as (
            session,
            _,
        ):
            tools = (await session.list_tools()).tools

        surface = {
            tool.name: (
                tool.inputSchema,
                tool.outputSchema,
                _words(tool.description or ""),
            )
            for tool in tools
        }
        assert surface == PROJECTS_SURFACE
        assert gated_routes.calls == []
        assert token_endpoint.forms == []

    async def test_the_server_is_pilot_projects_with_its_instructions(
        self, projects_app: Starlette
    ) -> None:
        async with mcp_session(projects_app, PROJECTS_HEADERS, PROJECTS_PATH) as (
            _,
            initialized,
        ):
            pass

        assert initialized.serverInfo.name == "pilot-projects"
        assert initialized.instructions == PROJECTS_INSTRUCTIONS

    @pytest.mark.parametrize("path", [WORK_PATH, STORE_PATH])
    async def test_no_other_server_of_the_app_has_its_name(
        self, projects_app: Starlette, path: str
    ) -> None:
        async with mcp_session(projects_app, path=path) as (_, initialized):
            pass

        assert initialized.serverInfo.name == "pilot"

    def test_the_instructions_say_what_the_surface_is_before_they_name_the_skill(
        self,
    ) -> None:
        opening, skill = PROJECTS_INSTRUCTIONS.split(" Load the skill ")

        assert opening == (
            "Pilot, the project manager, and its projects. These tools read a"
            " project Pilot manages, its documents and its items, and start one."
        )
        assert skill.startswith("`kubecoder:pilot-usage`")

    @pytest.mark.parametrize("tool", sorted(PROJECTS_SURFACE))
    def test_a_tools_description_names_pilots_projects_in_its_first_words(
        self, tool: str
    ) -> None:
        _, _, description = PROJECTS_SURFACE[tool]
        first, _, _ = description.partition(",")

        assert re.search(r"\bprojects? Pilot manages\b", first), first

    def test_the_words_are_the_outsides(self) -> None:
        said = [PROJECTS_INSTRUCTIONS]
        for arguments, result, description in PROJECTS_SURFACE.values():
            said += [description, *_texts(arguments), *_texts(result)]

        assert [text for text in said if _INSIDE_WORDS.search(text)] == []

    def test_the_callers_two_headers_are_pinned(self) -> None:
        """The operator's entry in `~/.claude.json` is written against them
        (F150.1)."""
        assert (ENVIRONMENT_HEADER, SESSION_HEADER) == (
            "X-Pilot-Environment",
            "X-Pilot-Session",
        )


_NOT_THE_TOKEN = {
    "error": (
        "Cannot call Pilot's projects because the request does not carry their token"
    ),
    "details": {
        "message": "Send PILOT_PROJECTS_TOKEN as `Authorization: Bearer <token>`"
    },
    "code": "AUTHENTICATION_REQUIRED",
}


@pytest.mark.anyio
class TestTheProjectsDoor:
    """The surface's shared token at its door (ruling D1)."""

    @pytest.mark.parametrize(
        "authorization",
        [
            None,
            "Bearer ",
            f"bearer {PROJECTS_TOKEN}",
            f"Basic {PROJECTS_TOKEN}",
            "Bearer another-token",
            f"Bearer {PROJECTS_TOKEN}x",
            f"Bearer {PROJECTS_TOKEN[:-1]}",
            f"Bearer {TOKEN}",
            "Bearer t\u00f6ken".encode("latin-1"),
        ],
    )
    @pytest.mark.parametrize("path", [PROJECTS_PATH, f"{PROJECTS_PATH}/"])
    async def test_a_request_without_the_token_is_refused_and_reaches_nothing(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        token_endpoint: TokenEndpoint,
        authorization: str | bytes | None,
        path: str,
    ) -> None:
        headers = [(b"accept", _ACCEPT["Accept"].encode())]
        if authorization is not None:
            raw = (
                authorization.encode()
                if isinstance(authorization, str)
                else authorization
            )
            headers.append((b"authorization", raw))
        async with http_client(projects_app) as http:
            response = await http.post(path, json=_INITIALIZE, headers=headers)

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == _NOT_THE_TOKEN
        assert gated_routes.calls == []
        assert token_endpoint.forms == []

    async def test_the_token_is_let_in(self, projects_app: Starlette) -> None:
        headers = {"Authorization": f"Bearer {PROJECTS_TOKEN}"}
        async with mcp_session(projects_app, headers, PROJECTS_PATH) as (session, _):
            tools = (await session.list_tools()).tools

        assert {tool.name for tool in tools} == set(PROJECTS_SURFACE)

    @pytest.mark.parametrize(
        "authorization", [None, f"Bearer {PROJECTS_TOKEN}", f"Bearer {TOKEN}"]
    )
    @pytest.mark.parametrize("path", [PROJECTS_PATH, f"{PROJECTS_PATH}/"])
    async def test_a_surface_not_configured_refuses_every_request(
        self,
        mcp_app: Starlette,
        routes: ApiRoutes,
        authorization: str | None,
        path: str,
    ) -> None:
        headers = {} if authorization is None else {"Authorization": authorization}
        async with http_client(mcp_app, headers) as http:
            response = await http.post(path, json=_INITIALIZE, headers=_ACCEPT)

        assert response.status_code == 503
        assert response.json() == {
            "error": (
                "Cannot call Pilot's projects because this Pilot is not set up to"
                " serve them"
            ),
            "details": {
                "message": (
                    "Its token or the client it calls its API with is missing from"
                    " its deployment"
                )
            },
            "code": "SERVICE_UNAVAILABLE",
        }
        assert routes.calls == []

    @pytest.mark.parametrize(("path", "pinned", "instructions"), _SURFACES)
    async def test_the_other_servers_door_is_as_it_was(
        self,
        projects_app: Starlette,
        gated_routes: ApiRoutes,
        path: str,
        pinned: dict[str, Any],
        instructions: str,
    ) -> None:
        """Beside a configured surface a bearer is admitted there without
        its check, the surface's token no more than another, and a request
        with none refused."""
        async with http_client(projects_app) as http:
            refused = await http.post(path, json=_INITIALIZE, headers=_ACCEPT)
        headers = {"Authorization": "Bearer a-token-no-session-has"}
        async with mcp_session(projects_app, headers, path) as (session, _):
            tools = (await session.list_tools()).tools

        assert refused.status_code == 401
        assert refused.json()["error"] == (
            "Cannot call Pilot's MCP server because the request carries no bearer"
        )
        assert {tool.name for tool in tools} == set(pinned)
        assert gated_routes.calls == []

    @pytest.mark.parametrize("path", ["/health/healthz", "/health/readyz"])
    async def test_the_probes_answer_beside_it(
        self, projects_app: Starlette, path: str
    ) -> None:
        async with http_client(projects_app) as http:
            response = await http.get(path)

        assert response.status_code == 200
