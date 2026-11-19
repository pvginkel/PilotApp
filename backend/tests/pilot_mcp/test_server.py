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
from app.services.caller_environment_service import (
    CALLER_ENVIRONMENT_HEADER,
    CALLER_SESSION_HEADER,
)
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
                "why": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": "Its line under the label; none where not given",
                    "title": "Why",
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
# worker reads them (FM §5 step 1, F65.3, F85, F85.3, F85.4, F85.5).
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
                        "why": {
                            "anyOf": [
                                {"maxLength": 120, "minLength": 1, "type": "string"},
                                {"type": "null"},
                            ],
                            "default": None,
                            "description": (
                                "A short line shown under the step's label, at most"
                                " 120 characters; without it, the step has none"
                            ),
                            "title": "Why",
                        },
                        "kind": {
                            "anyOf": [
                                {"maxLength": 64, "minLength": 1, "type": "string"},
                                {"type": "null"},
                            ],
                            "default": None,
                            "description": (
                                "Your name for the kind of step it is, at most 64"
                                " characters, kept and shown as given: steps of one"
                                " kind are timed together; without it, the step has"
                                " none"
                            ),
                            "title": "Kind",
                        },
                        "duration": {
                            "anyOf": [
                                {
                                    "maximum": 2147483647,
                                    "minimum": 0,
                                    "type": "integer",
                                },
                                {"type": "null"},
                            ],
                            "default": None,
                            "description": (
                                "On a step this call leaves `done`, the whole"
                                " seconds its work took by your own measure, 0 or"
                                " more"
                            ),
                            "title": "Duration",
                        },
                        "marked": {
                            "anyOf": [{"type": "boolean"}, {"type": "null"}],
                            "default": None,
                            "description": (
                                "Whether you hold the step to be in trouble, true or"
                                " false; without it, the step has no mark"
                            ),
                            "title": "Marked",
                        },
                        "conversations": {
                            "anyOf": [
                                {
                                    "items": {
                                        "maxLength": 64,
                                        "minLength": 1,
                                        "type": "string",
                                    },
                                    "maxItems": 100,
                                    "type": "array",
                                },
                                {"type": "null"},
                            ],
                            "default": None,
                            "description": (
                                "The conversations that did the step's work, each by"
                                " its Claude Code session id of at most 64"
                                " characters, each once, at most 100; without it,"
                                " the step names none"
                            ),
                            "title": "Conversations",
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
        " it, a `label`, its words, a `state`, `pending`, `active` or `done`, and,"
        " where it has one, a `why`, a short line shown under its label, a `kind`,"
        " your name for the kind of step it is, `marked`, whether you hold the step"
        " to be in trouble, `conversations`, the Claude Code session ids of the"
        " conversations that did its work, and, on a step the call leaves `done`, a"
        " `duration`, the whole seconds its work took by your own measure. The list"
        " replaces the one standing: a code already on it keeps its state where you"
        " give none, a new code starts `pending`, a code left out goes, and `[]`"
        " removes the list; a step's label, why, kind, mark and conversations are"
        " as you give them, a step given without one having none. Where the work"
        " grows, add a step; a second round of a step is a step of its own. Pilot"
        " stamps each step's start and end by its own clock, and keeps a step's"
        " kind and duration as its timing when a step on the list that was not done"
        " goes `done` with both, once. An empty or repeated code, an empty label or"
        " why, a state outside the three, a code over 64 characters, a label or a"
        " why over 120, an empty kind or one over 64 characters, a duration that is"
        " not a whole number from 0 to 2147483647 or stands on a step the call"
        " leaves not `done`, a `marked` that is not true or false, a conversation"
        " that is empty, over 64 characters or repeated on its step, over 100"
        " conversations on a step, an unknown field or a list over 100 steps is"
        " refused with the reason, and nothing changes. Answers `{steps}`, the list"
        " as it stands.",
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
    "register_debrief": (
        {
            "$defs": {
                "DebriefEntry": {
                    "additionalProperties": False,
                    "description": "One account of your work item's debrief.",
                    "properties": {
                        "section": {
                            "description": (
                                "The name of the part of the run it ran in, at most"
                                " 120 characters: consecutive entries of one name"
                                " show as one section"
                            ),
                            "maxLength": 120,
                            "minLength": 1,
                            "title": "Section",
                            "type": "string",
                        },
                        "round": {
                            "description": "Its round of that part, 1 or more",
                            "maximum": 2147483647,
                            "minimum": 1,
                            "title": "Round",
                            "type": "integer",
                        },
                        "role": {
                            "description": "Whose account it is, at most 64 characters",
                            "maxLength": 64,
                            "minLength": 1,
                            "title": "Role",
                            "type": "string",
                        },
                        "duration": {
                            "description": "The time its turn took, in whole seconds",
                            "maximum": 2147483647,
                            "minimum": 0,
                            "title": "Duration",
                            "type": "integer",
                        },
                        "words": {
                            "anyOf": [
                                {"maxLength": 4000, "minLength": 1, "type": "string"},
                                {"type": "null"},
                            ],
                            "default": None,
                            "description": (
                                "The account, in its own words, at most 4,000"
                                " characters; none with `passed`"
                            ),
                            "title": "Words",
                        },
                        "passed": {
                            "anyOf": [{"type": "boolean"}, {"type": "null"}],
                            "default": None,
                            "description": (
                                "A pass or a fail in place of words; none with `words`"
                            ),
                            "title": "Passed",
                        },
                        "why": {
                            "anyOf": [
                                {"maxLength": 120, "minLength": 1, "type": "string"},
                                {"type": "null"},
                            ],
                            "default": None,
                            "description": (
                                "On an entry that opens a round past the first, why"
                                " that round was needed, at most 120 characters"
                            ),
                            "title": "Why",
                        },
                    },
                    "required": ["section", "round", "role", "duration"],
                    "title": "DebriefEntry",
                    "type": "object",
                }
            },
            "properties": {
                "debrief": {
                    "description": (
                        "Your account of how the run went, in your own words, at"
                        " most 16,000 characters"
                    ),
                    "maxLength": 16000,
                    "minLength": 1,
                    "title": "Debrief",
                    "type": "string",
                },
                "entries": {
                    "description": "The run's accounts, in order, 1 to 500",
                    "items": {"$ref": "#/$defs/DebriefEntry"},
                    "maxItems": 500,
                    "minItems": 1,
                    "title": "Entries",
                    "type": "array",
                },
                "subject": {
                    "anyOf": [
                        {"maxLength": 120, "minLength": 1, "type": "string"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": (
                        "What your debrief is an account of, as your workflow names"
                        " it, at most 120 characters: the debriefs of one subject"
                        " come together in one notice, titled with it"
                    ),
                    "title": "Subject",
                },
                "completes": {
                    "default": True,
                    "description": (
                        "Whether your debrief completes its subject's account, true"
                        " where left out; false where a later debrief of the same"
                        " subject completes it, which takes a subject"
                    ),
                    "title": "Completes",
                    "type": "boolean",
                },
                "figures": {
                    "anyOf": [
                        {"maxLength": 8000, "minLength": 1, "type": "string"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": (
                        "The run's figures as your workflow gives them, at most"
                        " 8,000 characters: Pilot reads them with your debrief and"
                        " shows them nowhere"
                    ),
                    "title": "Figures",
                },
            },
            "required": ["debrief", "entries"],
            "title": "register_debriefArguments",
            "type": "object",
        },
        {
            "description": "The debrief stored.",
            "properties": {
                "entries": {
                    "description": "The number of its entries",
                    "title": "Entries",
                    "type": "integer",
                }
            },
            "required": ["entries"],
            "title": "RegisteredDebrief",
            "type": "object",
        },
        "Hand Pilot your work item's debrief, once, before your turn ends:"
        " `debrief`, your own account of how the run went, and `entries`, every"
        " account of the run in order, each with the `section` of the run it ran in,"
        " its `round` of that part, its `role`, its `duration` in whole seconds, at"
        " most one of its `words` and `passed`, a pass or a fail, and, on an entry"
        " that opens a round past the first, its `why`; with it, `subject`, what the"
        " debrief is an account of, `completes`, false where a later debrief of the"
        " same subject completes it, and `figures`, the run's figures as your"
        " workflow gives them. Pilot stores them as you give them and shows them"
        " behind the work item's Debrief once your turn ends, the figures nowhere; a"
        " subject's debriefs come together in one notice on the project's timeline"
        " once the work item whose debrief completes it is done. A second call is"
        " refused with the reason, and nothing changes. A call outside the limits —"
        " an empty debrief or one over 16,000 characters, no entries or over 500, an"
        " empty section, role, words or why, a section or a why over 120 characters,"
        " a role over 64, words over 4,000, a round under 1, a duration under 0, both"
        " words and passed, an unknown field in an entry, an empty subject or one"
        " over 120 characters, `completes` false without a subject, empty figures or"
        " ones over 8,000 characters — is refused with each fault, and nothing is"
        " stored. Answers `{entries}`, the number of entries stored.",
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


def _optional_text(title: str, description: str) -> dict[str, Any]:
    """An optional parameter of words, none or one character or more."""
    return {
        "anyOf": [{"minLength": 1, "type": "string"}, {"type": "null"}],
        "default": None,
        "description": description,
        "title": title,
    }


_STANDING = {
    "description": "What the call did to the note or the alert standing in its place.",
    "properties": {
        "outcome": {
            "description": (
                "`written` where none stood, `replaced` where one stood, `withdrawn`"
                " where the call took it off"
            ),
            "enum": ["written", "replaced", "withdrawn"],
            "title": "Outcome",
            "type": "string",
        }
    },
    "required": ["outcome"],
    "title": "Standing",
    "type": "object",
}

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
            " it; a work item names this or `environment`, never both",
            pattern=r"^[^/\s]+/[^/\s]+$",
        ),
        "environment": _optional(
            "Environment",
            "The id of the environment a work item is placed in, in place of `repo`:"
            " it runs there, the environment as it stands",
            pattern=r"^[^:\s/]+$",
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
                "The actions of workers' documents or of items you added that a"
                " work item does and you claimed, by their blocks' ids, `<item"
                " id>/<local id>`: each block's line names this work item, and the"
                " job after its turn names them for their `done`"
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
        " minted with it. A work item is started on add, on your placement, its"
        " first turn your `brief` followed by Pilot's own lines: by `repo`, in an"
        " environment Pilot makes from it, or by `environment`, an environment's"
        " id, in that environment as it stands. One placed by `environment` names"
        " no `repo`: Pilot never makes, takes, renames or resets its environment,"
        " starts it when it is stopped, and stops it again once nothing runs"
        " there only where it started it. `state` answers whether it is `starting`"
        " or `held` at the gate, and `held` why — say so to the person. A work"
        " item that does actions you claimed, of workers' documents or of items"
        " you added, names them in `claims`: each stays open and yours until its"
        " `done`, its line naming this work item, the latest that names it, and"
        " an item you added is done, with no undo, once its last open block's"
        " `done` is written. A work item that checks a fact for blocks you"
        " left unanswered names them in `researches`: each line names this work"
        " item, the latest that names it, and the job after its turn gives them"
        " to you to route. A wait is recorded with its `title`, a card wait's"
        " `cards` and `states` or a timed wait's `due_at`, and is fixed from then"
        " on: Pilot fires it and never closes it; you close it with your own"
        " `mark` `done` and its `note`, and to change it you close it and add"
        " another. A field the kind does not take or one it needs missing, a work"
        " item that names both `repo` and `environment` or neither, the store's"
        " environment or one the controller does not have, a text"
        " with no title or with faults, a wait's list empty or naming one twice, a"
        " card that is no ticket id, a due time not ahead, an attachment or a plan"
        " task not of your project, material that cannot be copied, a claim that"
        " is not an open action of a registered document or of an item you added"
        " of your project, a research of a block that is answered or not in an"
        " open registered"
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
        " through the chat; it replaces the block's answer, yours included, while"
        " the item is open, and the answer to an item's one block is its Done,"
        " which they can undo, but on an item you added: you carry that Done out"
        " in this turn, and it has no undo. In a draft's definition chat, a block"
        " of the draft is"
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
                        "`done` on a document or a wait, `read` on a notice or"
                        " a debrief's notice, `reviewed` on a review"
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
        " answers them; `read` on a notice or a debrief's notice; `reviewed` on a"
        " review. Without `for`,"
        " the mark is your own, and only `done`, on a document you settled whole,"
        " every block of it answered, and on a registered document of one block,"
        " whatever its kind, once that block is answered or deferred: a claimed"
        " action counts once its `done` is written; and on an open wait, with your"
        " `note`, which closes it for good. A registered document's Done writes its"
        " answers back and resumes its worker once none of its run's documents is"
        " open. A `done` or `reviewed` for a person on an item you added is yours"
        " to carry out in this turn, and has no undo. An item not of your"
        " project, a `for` that names no person, a mark"
        " its kind does not take, an item that is done, a document with a block"
        " neither answered nor recommended, or, without `for`, one with a block"
        " unanswered or a claimed action not yet done, a wait's mark with `for` or"
        " without a `note`, or a `note` on any other item is refused with the"
        " reason, and nothing is marked. Answers `{effect}`, the call's effect"
        " line.",
    ),
    "cancel_ask": (
        {
            "properties": {
                "item": {**_ITEM, "description": "The ask's item id"},
                "for": {
                    "description": (
                        "The handle of the person on whose word it is called off"
                    ),
                    "minLength": 1,
                    "title": "For",
                    "type": "string",
                },
            },
            "required": ["item", "for"],
            "title": "cancel_askArguments",
            "type": "object",
        },
        _RECORDED,
        "Call off an ask you added, once a person says in the chat that it is"
        " obsolete: `for` names them by handle. The ask is a decision, a"
        " confirmation, a question, an action or a document that an `add_item` of"
        " yours added. It is closed as cancelled, by them, its blocks left as they"
        " stand: its line shows the cancelled mark, it has no undo, and no job"
        " follows it. Never call one off on your own word. A document a work"
        " item's run registered is refused: the Cancel on its page, which ends"
        " that run, is the one way to call it off. An item not of your project, a"
        " `for` that names no person, a notice, a work item, a wait, an item no"
        " `add_item` of yours added, or one that is done is refused with the"
        " reason, and nothing is closed. Answers `{effect}`, the call's effect"
        " line.",
    ),
    "stop_work": (
        {
            "properties": {
                "item": {**_ITEM, "description": "The work item's id"},
                "reason": {
                    "anyOf": [{"minLength": 1, "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": (
                        "Why the work item is closed for good, in a line its done"
                        " line carries: give it for a work item you replaced or one a"
                        " person dropped, and"
                        " leave it out to stop one a person may resume"
                    ),
                    "title": "Reason",
                },
            },
            "required": ["item"],
            "title": "stop_workArguments",
            "type": "object",
        },
        _RECORDED,
        "Stop a work item's session that runs, is starting or is held at the gate,"
        " or one whose turn ended under a usage halt or the project's pause, to be"
        " carried on once it lifts: a runaway session, or one a correction makes"
        " moot. A turn in flight is interrupted and the conversation kept; the item"
        " shows it stopped by Pilot, and a person can resume it. With `reason`,"
        " the work item is closed for good in the same act: one you replaced with"
        " another, or one a person dropped with nothing in its place, their words"
        " the reason, which nobody is to resume. It is stopped where it was not, one"
        " stopped earlier included, and done as cancelled, by you: its line shows"
        " the cancelled mark and your reason, it waits on nobody, and it takes no"
        " Resume and no undo. The documents its run put to a person stay open. An"
        " item not of your project, one that is no work item, a job of yours, or"
        " one whose session is none of these is refused with the reason; so is,"
        " with `reason`, one that is done, one that failed, which keeps its Resume,"
        " and one of an archived project. Answers `{effect}`, the call's effect"
        " line.",
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
    "write_notable": (
        {
            "properties": {
                "text": {
                    "description": (
                        "What is notable about the stage, in your words, Markdown,"
                        " at most 16,000 characters"
                    ),
                    "maxLength": 16000,
                    "minLength": 1,
                    "title": "Text",
                    "type": "string",
                },
            },
            "required": ["text"],
            "title": "write_notableArguments",
            "type": "object",
        },
        {
            "description": "What the call did to your lines on the debrief.",
            "properties": {
                "outcome": {
                    "description": (
                        "`written` where none stood, `replaced` where some stood"
                    ),
                    "enum": ["written", "replaced"],
                    "title": "Outcome",
                    "type": "string",
                }
            },
            "required": ["outcome"],
            "title": "Written",
            "type": "object",
        },
        "Write your lines on the debrief your brief carries: what is notable about"
        " the stage, which the debrief's notice shows the operator above the debrief"
        " itself. Only the job after a work item's turn writes them, on that work"
        " item's debrief, which the call does not name; a later call, a retry's"
        " included, replaces the lines standing. Nothing of them goes back to the"
        " worker. A call from the chat or from any other job, one after a turn that"
        " gave no debrief, or lines that are empty or over 16,000 characters are"
        " refused with the reason, and nothing is written. Answers `{outcome}`:"
        " `written` or `replaced`.",
    ),
    "note": (
        {
            "properties": {
                "item": {**_ITEM, "description": "The document's item id"},
                "block": {
                    "anyOf": [
                        {"pattern": _BLOCK["pattern"], "type": "string"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": (
                        "The block's id, `<item id>/<local id>`, a block of the item;"
                        " leave it out for a note on the document as a whole"
                    ),
                    "title": "Block",
                },
                "text": _optional_text(
                    "Text",
                    "What you know that bears on the answer and the document does"
                    " not say, in a few lines of Markdown",
                ),
                "suggested_answer": _optional_text(
                    "Suggested Answer",
                    "The answer you would give where it is not the one the writer"
                    " recommends: an option's label, `Agree`, `Yes`, `No` or free"
                    " words",
                ),
                "suggested_note": _optional_text(
                    "Suggested Note",
                    "The note you suggest beside that answer, or for an action's Done",
                ),
                "offer": _optional_text(
                    "Offer",
                    "The work you would do about an open action on the person's"
                    " word, in a line: the action itself or something beside it",
                ),
            },
            "required": ["item"],
            "title": "noteArguments",
            "type": "object",
        },
        _STANDING,
        "Put your note on a block of an open document of your project, an ask a"
        " person answers, or without `block` on the document as a whole: what you"
        " know that bears on the answer and the document does not say. Write one"
        " only by exception: a `suggested_answer`, with its `suggested_note`, where"
        " you would answer otherwise than the writer recommends; `text` alone where"
        " you know something that could change the answer; an `offer` where you"
        " would do work about an open action on the person's word. None to say a"
        " block is fine or that you agree. The note stands beside the document,"
        " never in its text, and nothing of it goes back to the writer. A"
        " `suggested_answer` that is not the answer the block's recommendation"
        " would record takes that recommendation away: Done records none for the"
        " block, and is refused while it is unanswered. A later"
        " note on the same block, or on the document as a whole, replaces the one"
        " standing there; a call with none of `text`, `suggested_answer`,"
        " `suggested_note` and `offer` takes it off. An item not of your project,"
        " one with no block or that is done, a block not of the item, one you"
        " answered, one a work item's run holds unless you are the job after that"
        " run's turn, a suggested answer on an action with no options, an offer on"
        " anything but an open action, anything but `text` on the document as a"
        " whole, or a call that takes off a note where none stands is refused with"
        " the reason, and nothing is written. Answers `{outcome}`: `written`,"
        " `replaced` or `withdrawn`.",
    ),
    "alert": (
        {
            "properties": {
                "item": {**_ITEM, "description": "The document's item id"},
                "text": _optional_text(
                    "Text",
                    "What to answer first and what this document's Send starts, in a"
                    " line or two",
                ),
                "awaits": {
                    "anyOf": [
                        {"pattern": _BLOCK["pattern"], "type": "string"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": (
                        "The ask to answer first, `<item id>/<local id>`, a block of"
                        " another open item of your project"
                    ),
                    "title": "Awaits",
                },
            },
            "required": ["item"],
            "title": "alertArguments",
            "type": "object",
        },
        _STANDING,
        "Put an alert on an open document of your project whose Send starts work"
        " that another open ask must come before: `awaits` names that ask and"
        " `text` says what to answer first and what the Send starts, the two given"
        " together. It stops no Send, and shows while this item and the item of"
        " the ask it awaits are both open. A later alert on the same document replaces"
        " the one standing; a call with neither takes it off. An item not of your"
        " project, a work item, a wait, a debrief's notice or an item that is done,"
        " an `awaits` of the item itself, of an item not of your project or that is"
        " done, or that its item does not hold, `text` or `awaits` alone, or a call"
        " that takes off an alert where none stands is refused with the reason, and"
        " nothing is written. Answers `{outcome}`: `written`, `replaced` or"
        " `withdrawn`.",
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
    async def test_the_store_tools_alone_are_marked_to_load_up_front(
        self,
        mcp_app: Starlette,
        path: str,
        pinned: dict[str, Any],
        instructions: str,
    ) -> None:
        """Each of `pilot-store`'s eleven tools carries the `_meta` on which
        Claude Code loads a tool with no ToolSearch before it, and no tool of
        the worker's carries any (P-403)."""
        async with mcp_session(mcp_app, path=path) as (session, _):
            tools = (await session.list_tools()).tools

        mark = {"anthropic/alwaysLoad": True} if path == STORE_PATH else None
        assert {tool.name: tool.meta for tool in tools} == dict.fromkeys(pinned, mark)
        assert len(STORE_SURFACE) == 11

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
                {
                    "code": "P1.code",
                    "label": "P1 · the client",
                    "state": "done",
                    "why": None,
                },
                {
                    "code": "P1.review",
                    "label": "P1 · review",
                    "state": "active",
                    "why": None,
                },
                {"code": "test", "label": "Test", "state": "pending", "why": None},
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
        "`draft` until Create project, then `open`, and `finished` once finished;"
        " `adopted` for a project that stands for a group of slices run before"
        " Pilot, which is archived from its birth and never opened"
    ),
    "enum": ["draft", "open", "finished", "adopted"],
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

_CONVERSATION_REF = {
    "description": (
        "The conversation's id, as `start_conversation` and `list_conversations`"
        " answer it"
    ),
    "format": "uuid",
    "title": "Conversation",
    "type": "string",
}

_MESSAGE_TEXT = {
    "description": "Your message, in your own words. Pilot reads it verbatim",
    "pattern": "\\S",
    "title": "Text",
    "type": "string",
}

_ONE_CONVERSATION = {
    "properties": {"conversation": _CONVERSATION_REF},
    "required": ["conversation"],
    "type": "object",
}

# A conversation as every tool but `send` answers it (F150.10, F150.11).
_CONVERSATION = {
    "description": "A conversation with Pilot about a project, as it stands.",
    "properties": {
        "id": {
            **_UUID,
            "description": (
                "Its id, which the other conversation tools take as `conversation`"
            ),
            "title": "Id",
        },
        "project": {
            **_UUID,
            "description": (
                "The id of the project it is about, which `get_project` takes"
            ),
            "title": "Project",
        },
        "environment": {
            "description": "The id of the environment whose session opened it",
            "title": "Environment",
            "type": "string",
        },
        "session": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": (
                "The name of the session that opened it; none where it gave none"
            ),
            "title": "Session",
        },
        "opened_at": {
            "description": "When it was opened, in UTC",
            "title": "Opened At",
            "type": "string",
        },
        "closed_at": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "When it was closed, in UTC; none while it is open",
            "title": "Closed At",
        },
        "close_cause": {
            "anyOf": [
                {
                    "enum": ["ended", "timeout", "finished", "reopened", "archived"],
                    "type": "string",
                },
                {"type": "null"},
            ],
            "description": (
                "Why it was closed: `ended` by `end_conversation`, `timeout` by"
                " Pilot once it stood quiet for some time after its last turn,"
                " `finished`, `reopened` or `archived` when its project was; none"
                " while it is open"
            ),
            "title": "Close Cause",
        },
        "turns": {
            "description": "The count of its turns so far",
            "title": "Turns",
            "type": "integer",
        },
        "running": {
            "description": (
                "Whether a turn of it is in flight, a stopped one that has not"
                " ended yet included: `send` is refused while one is"
            ),
            "title": "Running",
            "type": "boolean",
        },
    },
    "required": [
        "id",
        "project",
        "environment",
        "session",
        "opened_at",
        "closed_at",
        "close_cause",
        "turns",
        "running",
    ],
    "title": "Conversation",
    "type": "object",
}

_NOT_YOURS = (
    " A conversation no id names is refused, and one that another environment"
    " opened is refused in the same words."
)

# Each tool: its parameters, its result and its description, the words as a
# session anywhere in the fleet reads them (F150.3 to F150.11).
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
    "list_items": (
        {
            "properties": {
                "project": {
                    "description": (
                        "The project's id or its folder: `draft-<number>` while it is a"
                        " draft, its slug once it is created. A draft's folder does not"
                        " survive Create project, which gives the project its slug: hold a"
                        " draft by its id across it"
                    ),
                    "minLength": 1,
                    "title": "Project",
                    "type": "string",
                },
                "open": {
                    "default": True,
                    "description": (
                        "True, the default, for the open items alone; false for every item,"
                        " the done ones included"
                    ),
                    "title": "Open",
                    "type": "boolean",
                },
                "kind": {
                    "anyOf": [
                        {
                            "enum": [
                                "opening",
                                "decision",
                                "confirmation",
                                "question",
                                "action",
                                "notice",
                                "document",
                                "review",
                                "archive_question",
                                "work",
                                "card_wait",
                                "timed_wait",
                                "debrief_notice",
                            ],
                            "type": "string",
                        },
                        {
                            "type": "null",
                        },
                    ],
                    "default": None,
                    "description": "The one kind of item to list. Omit for every kind.",
                    "title": "Kind",
                },
                "offset": {
                    "default": 0,
                    "description": "Results to skip for pagination. Default: 0.",
                    "minimum": 0,
                    "title": "Offset",
                    "type": "integer",
                },
                "limit": {
                    "default": 100,
                    "description": (
                        "Maximum items to return. Default: 100, max: 1000 — a larger ask is"
                        " clamped to the max."
                    ),
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            "required": [
                "project",
            ],
            "title": "list_itemsArguments",
            "type": "object",
        },
        {
            "$defs": {
                "ListedItem": {
                    "description": (
                        "An item of a project; a field with nothing to say is left out."
                    ),
                    "properties": {
                        "seq": {
                            "description": "Its number among the project's items",
                            "title": "Seq",
                            "type": "integer",
                        },
                        "kind": {
                            "description": "Its kind, a code of `reference.json`'s `item_kinds`",
                            "title": "Kind",
                            "type": "string",
                        },
                        "title": {
                            "anyOf": [
                                {
                                    "type": "string",
                                },
                                {
                                    "type": "null",
                                },
                            ],
                            "default": None,
                            "description": "Its title",
                            "title": "Title",
                        },
                        "path": {
                            "anyOf": [
                                {
                                    "type": "string",
                                },
                                {
                                    "type": "null",
                                },
                            ],
                            "default": None,
                            "description": (
                                "Its file, a path `read_file` takes but for an archived"
                                " project's, whose files are not read; left out for an item"
                                " with no file, a work item and a wait among them"
                            ),
                            "title": "Path",
                        },
                        "created_at": {
                            "description": "When it was added, in UTC",
                            "title": "Created At",
                            "type": "string",
                        },
                        "done_cause": {
                            "anyOf": [
                                {
                                    "type": "string",
                                },
                                {
                                    "type": "null",
                                },
                            ],
                            "default": None,
                            "description": (
                                "How it came to be done: `answered`, `marked`, `settled`,"
                                " `turn_ended`, `finished`, `cancelled` or `withdrawn`; left out"
                                " while it is open"
                            ),
                            "title": "Done Cause",
                        },
                        "for": {
                            "anyOf": [
                                {
                                    "type": "string",
                                },
                                {
                                    "type": "null",
                                },
                            ],
                            "default": None,
                            "description": (
                                "The handle of the person it is for; left out for one for no one"
                            ),
                            "title": "For",
                        },
                        "urgent": {
                            "default": False,
                            "description": "True for an urgent item; left out otherwise",
                            "title": "Urgent",
                            "type": "boolean",
                        },
                    },
                    "required": [
                        "seq",
                        "kind",
                        "created_at",
                    ],
                    "title": "ListedItem",
                    "type": "object",
                },
            },
            "description": "A page of a project's items.",
            "properties": {
                "items": {
                    "description": "A row per item, in the order they were added",
                    "items": {
                        "$ref": "#/$defs/ListedItem",
                    },
                    "title": "Items",
                    "type": "array",
                },
                "totalCount": {
                    "description": "The count of every entry, on any page",
                    "title": "Totalcount",
                    "type": "integer",
                },
                "limitHit": {
                    "description": "Whether more remain past this page: page on with `offset`",
                    "title": "Limithit",
                    "type": "boolean",
                },
            },
            "required": [
                "items",
                "totalCount",
                "limitHit",
            ],
            "title": "Items",
            "type": "object",
        },
        (
            "List the items of a project Pilot manages, by its id or its"
            " folder, in the order they were added: the index of its"
            " `timeline.json`. It lists the open items alone unless `open` is"
            " false. Returns `{items, totalCount, limitHit}`: an item has its"
            " `seq`, its number among the project's items, its `kind`, its"
            " `title`, its `path`, the file `read_file` takes unless the project"
            " is archived, `created_at`, `done_cause`, `for` and `urgent`, and a"
            " field with nothing to say"
            " is left out: an open item has no `done_cause`, an item with no"
            " file no `path`. `totalCount` counts every item the call lists and"
            " `limitHit` says whether more remain past this page (page on with"
            " `offset`). A project no id or folder names is refused."
        ),
    ),
    "list_files": (
        {
            "properties": {
                "path": {
                    "default": "",
                    "description": (
                        "The folder's path from the root of the projects' files (e.g."
                        " `draft-7/items`). Default: the root."
                    ),
                    "title": "Path",
                    "type": "string",
                },
                "offset": {
                    "default": 0,
                    "description": "Results to skip for pagination. Default: 0.",
                    "minimum": 0,
                    "title": "Offset",
                    "type": "integer",
                },
                "limit": {
                    "default": 100,
                    "description": (
                        "Maximum entries to return. Default: 100, max: 1000 — a larger ask"
                        " is clamped to the max."
                    ),
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            "title": "list_filesArguments",
            "type": "object",
        },
        {
            "$defs": {
                "FileEntry": {
                    "description": "A file or a folder of a folder.",
                    "properties": {
                        "path": {
                            "description": (
                                "Its path from the root, which the other file tools take; a"
                                " folder's ends with `/`"
                            ),
                            "title": "Path",
                            "type": "string",
                        },
                        "isDirectory": {
                            "description": "Whether it is a folder",
                            "title": "Isdirectory",
                            "type": "boolean",
                        },
                    },
                    "required": [
                        "path",
                        "isDirectory",
                    ],
                    "title": "FileEntry",
                    "type": "object",
                },
            },
            "description": "A page of what a folder holds.",
            "properties": {
                "files": {
                    "description": "Its folders first, then its files",
                    "items": {
                        "$ref": "#/$defs/FileEntry",
                    },
                    "title": "Files",
                    "type": "array",
                },
                "totalCount": {
                    "description": "The count of every entry, on any page",
                    "title": "Totalcount",
                    "type": "integer",
                },
                "limitHit": {
                    "description": "Whether more remain past this page: page on with `offset`",
                    "title": "Limithit",
                    "type": "boolean",
                },
            },
            "required": [
                "files",
                "totalCount",
                "limitHit",
            ],
            "title": "FileListing",
            "type": "object",
        },
        (
            "List the files and folders in a folder of the projects Pilot"
            " manages, by its path from the root of their files: the root holds"
            " `reference.json` and the folder of every project that is not"
            " archived. Folders come first, then files. Returns `{files: [{path,"
            " isDirectory}], totalCount, limitHit}`: every `path` runs from the"
            " root, so it passes straight to the other file tools, and a"
            " folder's ends with `/`; `totalCount` counts every entry and"
            " `limitHit` says whether more remain past this page (page on with"
            " `offset`). A path that is not a folder is a `not-a-directory`"
            " error, and one that starts with `/` or climbs above the root a"
            " `path-outside-projects` error."
        ),
    ),
    "read_file": (
        {
            "properties": {
                "path": {
                    "description": (
                        "The file's path from the root of the projects' files (e.g."
                        " `draft-7/timeline.json`): a project's folder, then the path in it."
                        " A path that starts with `/` or climbs above the root is a"
                        " `path-outside-projects` error."
                    ),
                    "minLength": 1,
                    "title": "Path",
                    "type": "string",
                },
                "start_line": {
                    "anyOf": [
                        {
                            "minimum": 1,
                            "type": "integer",
                        },
                        {
                            "type": "null",
                        },
                    ],
                    "default": None,
                    "description": "1-based starting line. Omit to start from line 1.",
                    "title": "Start Line",
                },
                "end_line": {
                    "anyOf": [
                        {
                            "minimum": 1,
                            "type": "integer",
                        },
                        {
                            "type": "null",
                        },
                    ],
                    "default": None,
                    "description": (
                        "1-based ending line (inclusive). Omit to read to end of file."
                    ),
                    "title": "End Line",
                },
                "tail_lines": {
                    "anyOf": [
                        {
                            "minimum": 1,
                            "type": "integer",
                        },
                        {
                            "type": "null",
                        },
                    ],
                    "default": None,
                    "description": (
                        "Read the last N lines of the file. Not with"
                        " `start_line`/`end_line`."
                    ),
                    "title": "Tail Lines",
                },
            },
            "required": [
                "path",
            ],
            "title": "read_fileArguments",
            "type": "object",
        },
        {
            "description": "A text file as it was read.",
            "properties": {
                "content": {
                    "description": "The lines read, each under its number in the file: `N: line`",
                    "title": "Content",
                    "type": "string",
                },
                "sha256": {
                    "description": "The hash of the whole file's bytes",
                    "title": "Sha256",
                    "type": "string",
                },
                "totalCount": {
                    "description": "The count of the file's lines",
                    "title": "Totalcount",
                    "type": "integer",
                },
                "limitHit": {
                    "description": "Whether a range or a tail was cut at 2,000 lines or 128 KB",
                    "title": "Limithit",
                    "type": "boolean",
                },
                "lineCut": {
                    "description": (
                        "Whether the content is one line cut short, over 128 KB on its own"
                    ),
                    "title": "Linecut",
                    "type": "boolean",
                },
            },
            "required": [
                "content",
                "sha256",
                "totalCount",
                "limitHit",
                "lineCut",
            ],
            "title": "FileText",
            "type": "object",
        },
        (
            "Read a text file of the projects Pilot manages, by its path from"
            " the root of their files. Returns `{content, sha256, totalCount,"
            " limitHit, lineCut}`: `content` has the file's own line numbers"
            ' prefixed (e.g. `"1: line\\n2: line\\n"`), 1-indexed; `sha256` is the'
            " hash of the whole file's bytes, whatever was read; `totalCount`"
            " counts the file's lines. A read that names no range returns the"
            " whole file, however many lines, up to 128 KB; a larger file is a"
            " `file-too-large` error giving its line count. A line range"
            " (`start_line`..`end_line`) or a tail (`tail_lines`, the last N"
            " lines) reads a file of any size, and its answer holds at most"
            " 2,000 lines and 128 KB of `content`. Past either limit it is cut"
            " there and `limitHit` is true: a range keeps its start, so page on"
            " from the line after the last one returned, and a tail keeps the"
            " file's end. A line over 128 KB on its own comes back cut, as the"
            " answer's only line, with `lineCut` true: its start for a range,"
            " its end for a tail. `tail_lines` together with a range is an"
            " error. A file that is not UTF-8 text, as an attachment may be, is"
            " a `not-text` error. A folder is a `not-a-file` error. An archived"
            " project's files are not read."
        ),
    ),
    "find_files": (
        {
            "properties": {
                "path_pattern": {
                    "description": (
                        "Glob matched against the files' paths from the root of the"
                        " projects' files (e.g. `**/timeline.json`, `draft-7/items/*.md`,"
                        " `**/{project.md,plan.json}`). Supports *, **, ?, {a,b}. A pattern"
                        " that starts with `/`, where no path does, is a"
                        " `path-outside-projects` error."
                    ),
                    "minLength": 1,
                    "title": "Path Pattern",
                    "type": "string",
                },
                "offset": {
                    "default": 0,
                    "description": "Results to skip for pagination. Default: 0.",
                    "minimum": 0,
                    "title": "Offset",
                    "type": "integer",
                },
                "limit": {
                    "default": 50,
                    "description": (
                        "Maximum files to return. Default: 50, max: 200 — a larger ask is"
                        " clamped to the max."
                    ),
                    "minimum": 1,
                    "title": "Limit",
                    "type": "integer",
                },
            },
            "required": [
                "path_pattern",
            ],
            "title": "find_filesArguments",
            "type": "object",
        },
        {
            "description": "A page of the files a glob matches.",
            "properties": {
                "pattern": {
                    "description": "The glob that was matched",
                    "title": "Pattern",
                    "type": "string",
                },
                "files": {
                    "description": "The matching files' paths from the root, in path order",
                    "items": {
                        "type": "string",
                    },
                    "title": "Files",
                    "type": "array",
                },
                "totalCount": {
                    "description": "The count of every entry, on any page",
                    "title": "Totalcount",
                    "type": "integer",
                },
                "limitHit": {
                    "description": "Whether more remain past this page: page on with `offset`",
                    "title": "Limithit",
                    "type": "boolean",
                },
            },
            "required": [
                "pattern",
                "files",
                "totalCount",
                "limitHit",
            ],
            "title": "FoundFiles",
            "type": "object",
        },
        (
            "Find the files of the projects Pilot manages whose path matches a"
            " glob, the path taken from the root of their files. Use it to"
            " discover files by path or name; it does not search file contents."
            " `*` matches any characters except `/`, `**` any path segments, `?`"
            " a single character, `{a,b}` either alternative (`*`, `**`, `?`"
            " work inside; no nesting). Other glob syntax (`[...]` classes, `\\`"
            " escapes, nested or unbalanced braces) is a `validation-error`"
            " naming it, not zero results. Returns `{pattern, files, totalCount,"
            " limitHit}`: `files` are the matching paths in path order,"
            " `totalCount` counts every match and `limitHit` says whether more"
            " remain past this page (page on with `offset`)."
        ),
    ),
    "start_project": (
        {
            "properties": {
                "brief": {
                    "description": (
                        "The project's brief, in your own words: what it is for"
                        " and what it is to do. Pilot reads it verbatim, as the"
                        " first message of the draft's chat"
                    ),
                    "pattern": "\\S",
                    "title": "Brief",
                    "type": "string",
                },
                "title": {
                    "anyOf": [
                        {"pattern": "^[^\\r\\n]*\\S[^\\r\\n]*$", "type": "string"},
                        {"type": "null"},
                    ],
                    "default": None,
                    "description": (
                        "A title for the draft, one line, which names the project"
                        " until Pilot writes its own. Omit to leave the draft"
                        " untitled"
                    ),
                    "title": "Title",
                },
                "for": {
                    "anyOf": [{"minLength": 1, "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": (
                        "The handle of the person the project is started for, a"
                        " member of it from its start. Omit when it is for no one"
                        " person"
                    ),
                    "title": "For",
                },
            },
            "required": ["brief"],
            "title": "start_projectArguments",
            "type": "object",
        },
        {
            "description": "The draft a call started.",
            "properties": {
                "id": _ID,
                "folder": {
                    "description": (
                        "Its folder, the first segment of its files' paths:"
                        " `draft-<number>` until Create project gives the project"
                        " its slug"
                    ),
                    "title": "Folder",
                    "type": "string",
                },
                "url": {
                    "description": "Its page in Pilot's app",
                    "title": "Url",
                    "type": "string",
                },
            },
            "required": ["id", "folder", "url"],
            "title": "StartedProject",
            "type": "object",
        },
        "Start a project Pilot manages, as a draft: Pilot takes `brief` as the"
        " first message of the draft's chat and writes the draft from it, asking"
        " in it what it still has to know. A draft runs no work: a person reads"
        " it in Pilot's app, answers what it asks and presses Create project. Its"
        " members are the person `for` names and every person who joins the"
        " projects started on their behalf; with neither, it has none and waits"
        " in Pilot's project list. Answers `{id, folder, url}`: hold the draft by"
        " its `id`, which `get_project` takes, and read what Pilot wrote of it"
        " with `read_file`, at `<folder>/project.md`. A `for` that names no"
        " person is refused, as is every call while Pilot is updating, and"
        " nothing is started.",
    ),
    "start_conversation": (
        {
            "properties": {"project": _PROJECT, "text": _MESSAGE_TEXT},
            "required": ["project", "text"],
            "title": "start_conversationArguments",
            "type": "object",
        },
        _CONVERSATION,
        "Open a conversation with Pilot about a project Pilot manages, by its id"
        " or its folder, with your first message: Pilot reads `text` verbatim and"
        " answers it in a turn of its own, which runs on after the call returns:"
        " read its reply with `get_response`. On a finished project Pilot answers"
        " from what it reads and changes"
        " nothing. Answers the conversation as `get_conversation` does, `{id,"
        " project, environment, session, opened_at, closed_at, close_cause, turns,"
        " running}`, its first turn running: hold it by its `id`, which the other"
        " conversation tools take as `conversation`. It is your environment's: a"
        " later session there finds it with `list_conversations`, and no other"
        " environment's session reaches it. Several may be open on one project at"
        " once. Refused, with nothing opened: a project no id or folder names, a"
        " draft, an archived project, a call whose entry for these tools sends no"
        " environment, and every call while Pilot is updating.",
    ),
    "send": (
        {
            "properties": {"conversation": _CONVERSATION_REF, "text": _MESSAGE_TEXT},
            "required": ["conversation", "text"],
            "title": "sendArguments",
            "type": "object",
        },
        {
            "description": "The turn a message started.",
            "properties": {
                "turn": {
                    "description": "The turn's number in the conversation",
                    "title": "Turn",
                    "type": "integer",
                }
            },
            "required": ["turn"],
            "title": "SentMessage",
            "type": "object",
        },
        "Send your next message in a conversation with Pilot about a project"
        " Pilot manages, by the conversation's id: Pilot reads `text` verbatim, in"
        " a new turn. It answers at once with `{turn}`, the turn's number in the"
        " conversation, and the turn runs on: read its reply with `get_response`."
        " One message is in flight at a time"
        " and nothing is queued: while a turn of the conversation is in flight, a"
        " stopped one that has not ended yet included, the call is refused and"
        " nothing is sent. Refused the same way: a closed conversation, an"
        " archived project's, and every call while Pilot is updating. A message"
        " that could not be delivered is an error saying why." + _NOT_YOURS,
    ),
    "get_response": (
        {
            "properties": {
                "conversation": _CONVERSATION_REF,
                "wait_ms": {
                    "default": 900000,
                    "description": (
                        "How long to hold for the turn's end, in ms. Defaults to"
                        " 900000 (15 min), so one call usually returns the whole"
                        " turn, and is capped at 3600000 (60 min): a larger ask is"
                        " clamped down to the cap, never refused. 0 answers at"
                        " once."
                    ),
                    "minimum": 0,
                    "title": "Wait Ms",
                    "type": "integer",
                },
            },
            "required": ["conversation"],
            "title": "get_responseArguments",
            "type": "object",
        },
        {
            "description": (
                "Pilot's reply to your latest message in a conversation, as it stands."
            ),
            "properties": {
                "turn": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}],
                    "description": (
                        "The number of the turn your message started, as `send`"
                        " answered it, 1 for the conversation's first; none while"
                        " `state` is `running`"
                    ),
                    "title": "Turn",
                },
                "state": {
                    "description": (
                        "`running` while the turn is in flight: the wait ran out"
                        " first, so call again. `done` once it has ended, `error`"
                        " when it failed, `interrupted` when it was stopped: by"
                        " `interrupt`, by a person, or by Pilot while it updated"
                    ),
                    "enum": ["running", "done", "error", "interrupted"],
                    "title": "State",
                    "type": "string",
                },
                "text": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": (
                        "Every message Pilot wrote in the turn, in order,"
                        " separated by `\\n\\n---\\n\\n`: the ones so far while"
                        " `running`. A turn that failed ends it with why, as a"
                        " section of its own. None when there is none"
                    ),
                    "title": "Text",
                },
            },
            "required": ["turn", "state", "text"],
            "title": "TurnResponse",
            "type": "object",
        },
        "Wait for Pilot's reply to your latest message in a conversation with"
        " Pilot about a project Pilot manages, by the conversation's id: the one"
        " way a reply comes back. It holds until the turn in flight ends or"
        " `wait_ms` runs out, whichever comes first, and answers at once when no"
        " turn is in flight. Returns `{turn, state, text}`: `state` is `done` when"
        " the turn ended, `error` when it failed, `interrupted` when it was"
        " stopped, and `running` when the wait ran out first: call again; `turn`"
        " is the number `send` answered for your message, 1 for the"
        " conversation's first, and none on `running`; `text` is every message"
        " Pilot wrote in the turn, in order, separated by `\\n\\n---\\n\\n`, and"
        " none when there is none. Several sections mean several messages; only"
        " `state` says the turn is over. On `running` it holds the messages so"
        " far, and a later call returns them all again. A turn that failed ends"
        " `text` with why, as a section of its own. Called again after the turn"
        " has ended, it answers the same reply, until your next `send`; a closed"
        " conversation answers its last. While it holds it reports progress twice"
        " a minute, which keeps a client that ends a silent call from ending it."
        + _NOT_YOURS,
    ),
    "get_conversation": (
        {**_ONE_CONVERSATION, "title": "get_conversationArguments"},
        _CONVERSATION,
        "Read where a conversation with Pilot about a project Pilot manages"
        " stands, by the conversation's id. Returns `{id, project, environment,"
        " session, opened_at, closed_at, close_cause, turns, running}`: `project`"
        " is the project's id, `environment` and `session` the environment's id"
        " and the session's name that opened it; `closed_at` and `close_cause` are"
        " none while it is open; `turns` counts its turns so far, and `running`"
        " says whether one is in flight, when `send` is refused. It answers no"
        " message of the conversation: `get_response` does." + _NOT_YOURS,
    ),
    "list_conversations": (
        {
            "properties": {
                "project": {
                    "anyOf": [{"minLength": 1, "type": "string"}, {"type": "null"}],
                    "default": None,
                    "description": (
                        "The one project whose conversations to list, by its id or"
                        " its folder. Omit for every project's."
                    ),
                    "title": "Project",
                }
            },
            "title": "list_conversationsArguments",
            "type": "object",
        },
        {
            "$defs": {"Conversation": _CONVERSATION},
            "description": "The conversations with Pilot a caller's environment opened.",
            "properties": {
                "conversations": {
                    "description": (
                        "A row per conversation, in the order they were opened"
                    ),
                    "items": {"$ref": "#/$defs/Conversation"},
                    "title": "Conversations",
                    "type": "array",
                }
            },
            "required": ["conversations"],
            "title": "Conversations",
            "type": "object",
        },
        "List the conversations with Pilot about the projects Pilot manages that"
        " your environment opened, open and closed, in the order they were opened:"
        " this session's and every earlier session's there, so that a later"
        " session finds its predecessor's. With `project`, those about that"
        " project alone. Returns `{conversations}`, each as `get_conversation`"
        " answers it. No other environment's conversation is listed, and a call"
        " whose entry for these tools sends no environment lists none. A `project`"
        " no id or folder names is refused.",
    ),
    "interrupt": (
        {**_ONE_CONVERSATION, "title": "interruptArguments"},
        _CONVERSATION,
        "Stop the turn in flight of a conversation with Pilot about a project"
        " Pilot manages, by the conversation's id: the turn ends where it is, and"
        " the conversation is kept for your next `send`. Answers the conversation"
        " as `get_conversation` does; its `running` stays true until the stopped"
        " turn has ended, and `send` is refused until then: `get_response` waits"
        " for that end, and answers the turn `interrupted`. With no turn in flight"
        " it changes nothing, on a closed conversation too." + _NOT_YOURS,
    ),
    "end_conversation": (
        {**_ONE_CONVERSATION, "title": "end_conversationArguments"},
        _CONVERSATION,
        "Close a conversation with Pilot about a project Pilot manages, by the"
        " conversation's id: a turn in flight is stopped first, and the"
        " conversation takes no further message. Answers the conversation as"
        " `get_conversation` does, its `close_cause` `ended`. Ending one that is"
        " closed already succeeds and changes nothing: it stays closed as it was."
        + _NOT_YOURS,
    ),
}

PROJECTS_INSTRUCTIONS = (
    "Pilot, the project manager, and its projects. These tools read a project"
    " Pilot manages, its documents and its items, start one, and talk to Pilot"
    " about one. Load the skill `kubecoder:pilot-usage` before you use them: it"
    " maps a project's files and says which of them answers which question."
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

    async def test_no_tool_is_marked_to_load_up_front(
        self, projects_app: Starlette
    ) -> None:
        """The surface's tools stay behind a session's ToolSearch (P-403)."""
        async with mcp_session(projects_app, PROJECTS_HEADERS, PROJECTS_PATH) as (
            session,
            _,
        ):
            tools = (await session.list_tools()).tools

        assert {tool.name: tool.meta for tool in tools} == dict.fromkeys(
            PROJECTS_SURFACE
        )

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
            " project Pilot manages, its documents and its items, start one, and"
            " talk to Pilot about one."
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

    def test_the_api_reads_the_caller_from_the_two_headers_the_process_sends(
        self,
    ) -> None:
        assert (CALLER_ENVIRONMENT_HEADER, CALLER_SESSION_HEADER) == (
            ENVIRONMENT_HEADER,
            SESSION_HEADER,
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
