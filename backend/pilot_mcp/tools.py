"""`pilot-work`'s tools (F85, FM §5 step 1), a worker's, `pilot-store`'s
(F86, TD §4.5), the brain's, and `pilot-projects`' (F150), any session's, each
one call to its route, but `get_response`, which holds its call while it asks
its routes where the conversation stands (`PilotProjectsApi.get_response`).

A tool's docstring is the description the session reads, and each parameter's
is in its annotation: they are the surface, not commentary
(`tests/pilot_mcp/test_server.py` pins them). The bearer a call to the first
two carries is the API's to resolve; a tool passes it on as it came, with the
tool-use id Claude Code sends in the call's `_meta`, which the call's effect
names, where it records one. A call to `pilot-projects` hands on its caller,
never its bearer (`api.py`), and its words are the outside's (F150.3): Pilot,
a project, its items and documents, and a conversation with Pilot about one,
whose tools are KubeCoder's session tools one for one (F150.10).
"""

import functools
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import AfterValidator, Field
from starlette.requests import Request

from pilot_mcp.api import (
    BLOCK_ID,
    ENVIRONMENT_HEADER,
    FIND_LIMIT_DEFAULT,
    FIND_LIMIT_MAX,
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_MAX,
    MAX_DEBRIEF,
    MAX_DEBRIEF_ENTRIES,
    MAX_DEBRIEF_FIGURES,
    MAX_DEBRIEF_SUBJECT,
    MAX_NOTABLE,
    MAX_STEP_CODE,
    MAX_STEPS,
    MAX_TIMINGS,
    SESSION_HEADER,
    SOURCE,
    WAIT_MS_DEFAULT,
    WAIT_MS_MAX,
    Added,
    Asked,
    AttachedFiles,
    AttachedMaterial,
    Caller,
    Conversation,
    Conversations,
    DebriefEntry,
    FileListing,
    FileText,
    FoundFiles,
    ItemKind,
    Items,
    Mark,
    NewItem,
    PilotProjectsApi,
    PilotStoreApi,
    PilotWorkApi,
    Progress,
    ProjectHead,
    Projects,
    Recorded,
    RegisteredDebrief,
    RegisteredDocument,
    SeededStepTimings,
    SentMessage,
    Standing,
    StartedProject,
    Step,
    StepState,
    StepTiming,
    TurnResponse,
    Written,
)

Call = Context[ServerSession, object, Request]

TOOL_USE_ID_META = "claudecode/toolUseId"
"""The `_meta` key of the tool-use id Claude Code sends with every
`tools/call`."""

LOADED_UP_FRONT = {"anthropic/alwaysLoad": True}
"""The `_meta` of a tool in `tools/list` whose schema Claude Code loads at the
session's start, where it defers any other behind its ToolSearch:
`pilot-store`'s tools carry it, `pilot-work`'s and `pilot-projects`' none."""


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


def _caller(ctx: Call) -> Caller:
    """Who calls `pilot-projects`, from the call's two headers; an empty one
    is none."""
    request = ctx.request_context.request
    # Streamable HTTP hands every call its request.
    assert request is not None
    return Caller(
        environment=request.headers.get(ENVIRONMENT_HEADER) or None,
        session=request.headers.get(SESSION_HEADER) or None,
    )


ProjectRef = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "The project's id or its folder: `draft-<number>` while it is a"
            " draft, its slug once it is created. A draft's folder does not"
            " survive Create project, which gives the project its slug: hold a"
            " draft by its id across it"
        ),
    ),
]
"""A tool's `project` (F150.4)."""


ConversationRef = Annotated[
    uuid.UUID,
    Field(
        description=(
            "The conversation's id, as `start_conversation` and"
            " `list_conversations` answer it"
        )
    ),
]
"""A tool's `conversation` (F150.10)."""

MessageText = Annotated[
    str,
    Field(
        pattern=r"\S",
        description="Your message, in your own words. Pilot reads it verbatim",
    ),
]

WaitMs = Annotated[
    int,
    Field(
        ge=0,
        description=(
            "How long to hold for the turn's end, in ms. Defaults to"
            f" {WAIT_MS_DEFAULT} (15 min), so one call usually returns the whole"
            f" turn, and is capped at {WAIT_MS_MAX} (60 min): a larger ask is"
            " clamped down to the cap, never refused. 0 answers at once."
        ),
    ),
]
"""`get_response`'s `wait_ms` (F150.10)."""

STILL_RUNNING = "Pilot's turn is still running"
"""The message of a held `get_response`'s progress notification."""

Offset = Annotated[
    int, Field(ge=0, description="Results to skip for pagination. Default: 0.")
]

FilePath = Annotated[
    str,
    Field(
        min_length=1,
        description=(
            "The file's path from the root of the projects' files (e.g."
            " `draft-7/timeline.json`): a project's folder, then the path in it."
            " A path that starts with `/` or climbs above the root is a"
            " `path-outside-projects` error."
        ),
    ),
]


ANSWERED_BLOCK = r"^(?:[0-9A-Fa-f-]{36}|project\.md)/\S+$"
"""A block `answer` takes: a block's id, or `project.md/<local id>`, a block of
the draft, which has no item."""

_FOR = "for"


def _taking_for[**P, R](tool: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """`tool`, whose parameter `for_` the session names `for`: FastMCP calls a
    tool by its parameters' aliases, and `for` names no Python parameter."""

    @functools.wraps(tool)
    async def call(*args: Any, **arguments: Any) -> R:
        arguments["for_"] = arguments.pop(_FOR)
        return await tool(*args, **arguments)

    return call


def _says_something(debrief: str) -> str:
    """A blank debrief is refused here as its route refuses it."""
    if not debrief.strip():
        raise ValueError("a debrief has words")
    return debrief


def _names_something(subject: str | None) -> str | None:
    """A blank subject is refused here as its route refuses it."""
    if subject is not None and not subject.strip():
        raise ValueError("a subject has words")
    return subject


def _figures_say_something(figures: str | None) -> str | None:
    """Blank figures are refused here as their route refuses them."""
    if figures is not None and not figures.strip():
        raise ValueError("the figures have words")
    return figures


def _lines_say_something(text: str) -> str:
    """Blank lines are refused here as their route refuses them."""
    if not text.strip():
        raise ValueError("the lines have words")
    return text


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

    @mcp.tool()
    async def set_progress(
        steps: Annotated[
            list[Step],
            Field(
                max_length=MAX_STEPS,
                description=(
                    "Your work item's steps, in order, at most 100; `[]` removes"
                    " the list"
                ),
            ),
        ],
        ctx: Call,
    ) -> Progress:
        """Publish your work item's steps as your run moves through them,
        shown on its tile in Pilot: the whole list, in order, each step a
        `code`, your name for it, a `label`, its words, a `state`, `pending`,
        `active` or `done`, and, where it has one, a `why`, a short line shown
        under its label, a `kind`, your name for the kind of step it is,
        `marked`, whether you hold the step to be in trouble, `conversations`,
        the Claude Code session ids of the conversations that did its work,
        and, on a step the call leaves `done`, a `duration`, the whole seconds
        its work took by your own measure. The list replaces the one standing:
        a code already on it keeps its state where you give none, a new code
        starts `pending`, a code left out goes, and `[]` removes the list; a
        step's label, why, kind, mark and conversations are as you give them,
        a step given without one having none. Where the work grows, add a
        step; a second round of a step is a step of its own. Pilot stamps each
        step's start and end by its own clock, and keeps a step's kind and
        duration as its timing when a step on the list that was not done goes
        `done` with both, once. An empty or repeated code, an empty label or
        why, a state outside the three, a code over 64 characters, a label or
        a why over 120, an empty kind or one over 64 characters, a duration
        that is not a whole number from 0 to 2147483647 or stands on a step
        the call leaves not `done`, a `marked` that is not true or false, a
        conversation that is empty, over 64 characters or repeated on its
        step, over 100 conversations on a step, an unknown field or a list
        over 100 steps is refused with the reason, and nothing changes.
        Answers `{steps}`, the list as it stands."""
        return await api.set_progress(_authorization(ctx), steps)

    @mcp.tool()
    async def set_progress_step(
        code: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_STEP_CODE,
                description="The code of a step on your work item's list",
            ),
        ],
        state: Annotated[StepState, Field(description="`pending`, `active` or `done`")],
        ctx: Call,
    ) -> Progress:
        """Move one step of your work item's list to `pending`, `active` or
        `done`, by its code, as your run moves through it; every step keeps
        its place. Pilot stamps each step's start and end by its own clock. A
        code not on the list or a state outside the three is refused with the
        reason, and nothing changes; `set_progress` adds a step. Answers
        `{steps}`, the list as it stands."""
        return await api.set_progress_step(_authorization(ctx), code, state)

    @mcp.tool()
    async def seed_step_timings(
        timings: Annotated[
            list[StepTiming],
            Field(
                min_length=1,
                max_length=MAX_TIMINGS,
                description="The timings, each key once, 1 to 1,000",
            ),
        ],
        ctx: Call,
    ) -> SeededStepTimings:
        """Publish the finished steps of past runs in your work item's
        repository as timings, which Pilot keeps beside the ones
        `set_progress` leaves of a run's steps: each timing a `key`, your
        name for it, unique within the repository, a `kind`, your name for
        the kind of step it was, as `set_progress` takes a step's,
        `ended_at`, when the step ended, a date and time with its offset, a
        `duration`, the whole seconds its work took by the run's own measure,
        and, where you know it, `listed_ahead`, whether the step stood
        pending on its run's list before it began. The timings hang on this
        work item, in its repository: its own, else its environment's. A key
        the repository has a timing of already, whichever work item published
        it, has that timing replaced whole, a `listed_ahead` you leave out
        leaving none. Pilot reads nothing out of a key, and a timing takes no
        mark. A call takes 1 to 1,000 timings; publish more in several calls.
        A work item placed in no repository, a key repeated in the call, an
        empty key or one over 200 characters, an empty kind or one over 64
        characters, an `ended_at` that is not a text of a date and time with
        its offset, a duration that is not a whole number from 0 to
        2147483647, a `listed_ahead` that is not true or false, an unknown
        field, no timings or over 1,000 is refused with the reason, and
        nothing is written. Answers `{timings}`, the number of timings
        written."""
        return await api.seed_step_timings(_authorization(ctx), timings)

    @mcp.tool()
    async def register_debrief(
        debrief: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_DEBRIEF,
                description=(
                    "Your account of how the run went, in your own words, at most"
                    " 16,000 characters"
                ),
            ),
            AfterValidator(_says_something),
        ],
        entries: Annotated[
            list[DebriefEntry],
            Field(
                min_length=1,
                max_length=MAX_DEBRIEF_ENTRIES,
                description="The run's accounts, in order, 1 to 500",
            ),
        ],
        ctx: Call,
        subject: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=MAX_DEBRIEF_SUBJECT,
                description=(
                    "What your debrief is an account of, as your workflow names it,"
                    " at most 120 characters: the debriefs of one subject come"
                    " together in one notice, titled with it"
                ),
            ),
            AfterValidator(_names_something),
        ] = None,
        completes: Annotated[
            bool,
            Field(
                strict=True,
                description=(
                    "Whether your debrief completes its subject's account, true"
                    " where left out; false where a later debrief of the same"
                    " subject completes it, which takes a subject"
                ),
            ),
        ] = True,
        figures: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=MAX_DEBRIEF_FIGURES,
                description=(
                    "The run's figures as your workflow gives them, at most 8,000"
                    " characters: Pilot reads them with your debrief and shows"
                    " them nowhere"
                ),
            ),
            AfterValidator(_figures_say_something),
        ] = None,
    ) -> RegisteredDebrief:
        """Hand Pilot your work item's debrief, once, before your turn ends:
        `debrief`, your own account of how the run went, and `entries`, every
        account of the run in order, each with the `section` of the run it
        ran in, its `round` of that part, its `role`, its `duration` in whole
        seconds, at most one of its `words` and `passed`, a pass or a fail,
        and, on an entry that opens a round past the first, its `why`; with
        it, `subject`, what the debrief is an account of, `completes`, false
        where a later debrief of the same subject completes it, and
        `figures`, the run's figures as your workflow gives them. Pilot
        stores them as you give them and shows them behind the work item's
        Debrief once your turn ends, the figures nowhere; a subject's
        debriefs come together in one notice on the project's timeline once
        the work item whose debrief completes it is done. A second call is
        refused with the reason, and nothing changes. A call outside the limits — an
        empty debrief or one over 16,000 characters, no entries or over 500,
        an empty section, role, words or why, a section or a why over 120
        characters, a role over 64, words over 4,000, a round under 1, a
        duration under 0, both words and passed, an unknown field in an
        entry, an empty subject or one over 120 characters, `completes` false
        without a subject, empty figures or ones over 8,000 characters — is
        refused with each fault, and nothing is stored. Answers `{entries}`,
        the number of entries stored."""
        if not completes and subject is None:
            raise ValueError("a debrief that does not complete names its subject")
        return await api.register_debrief(
            _authorization(ctx), debrief, entries, subject, completes, figures
        )


def register_store_tools(mcp: FastMCP, api: PilotStoreApi) -> None:
    @mcp.tool(meta=LOADED_UP_FRONT)
    async def add_item(
        item: Annotated[
            NewItem, Field(description="The item, in `timeline.json`'s shape")
        ],
        ctx: Call,
    ) -> Added:
        """Add an item to the project's timeline. A prose item is minted with
        its file under the project's folder, born with `title` in its front
        matter and `step`, `urgent`, `for` and `summary` beside it, and its
        `path` answered for you to fill; a short one may come whole as
        `markdown`, minted with it. A work item is started on add, on your
        placement, its first turn your `brief` followed by Pilot's own lines:
        by `repo`, in an environment Pilot makes from it, or by `environment`,
        an environment's id, in that environment as it stands. One placed by
        `environment` names no `repo`: Pilot never makes, takes, renames or
        resets its environment, starts it when it is stopped, and stops it
        again once nothing runs there only where it started it. `state`
        answers whether it is `starting` or `held` at the gate, and `held` why
        — say so to the person. A work item that does actions you claimed, of
        workers'
        documents or of items you added, names them in `claims`: each stays
        open and yours until its `done`, its line naming this work item, the
        latest that names it, and an item you added is done, with no undo,
        once its last open block's `done` is written. A work item that checks a
        fact for blocks you left unanswered names them in `researches`: each
        line names this work item, the latest that names it, and the job
        after its turn gives them to you to route. A wait is recorded with its
        `title`, a card wait's `cards` and `states` or a timed wait's
        `due_at`, and is fixed from then on: Pilot fires it and never closes
        it; you close it with your own `mark` `done` and its `note`, and to
        change it you close it and add another. A field the kind does not
        take or one it needs missing, a work item that names both `repo` and
        `environment` or neither, the store's environment or one the
        controller does not have, a text with no title or with faults, a
        wait's list empty or naming one twice, a card that is no ticket id, a
        due time not ahead, an attachment or a plan task not of your project,
        material that cannot be copied, a claim that is not an open action of
        a registered document or of an item you added of your project, a
        research of a block that is answered or not in an open registered
        document of your project, or a start the project refuses is refused
        with the reason, each fault with its line, and nothing is added.
        Answers `{id, path, state, held, effect}`."""
        return await api.add_item(_authorization(ctx), _tool_use_id(ctx), item)

    @mcp.tool(meta=LOADED_UP_FRONT)
    async def attach_file(
        source: Annotated[
            str,
            Field(
                pattern=SOURCE,
                description=(
                    "The material's environment and its absolute path there,"
                    " `<environment>:<path>`: a file, or a folder's every file"
                    " under it"
                ),
            ),
        ],
        ctx: Call,
        to: Annotated[
            uuid.UUID | None,
            Field(
                description=(
                    "The id of the item it hangs on, an item of your project;"
                    " none in a draft's definition chat"
                )
            ),
        ] = None,
    ) -> AttachedMaterial:
        """Copy outside material into Pilot's record — a design record whole
        or in part, a file the person points you at — from any environment
        of the fleet, by `<environment>:<path>`: a file, or a folder and every
        file under it, one attachment per file, all of one batch, each with
        its source. Each is copied now; what changes there later is not seen.
        `to` is the item it hangs on; in a draft's definition chat give none:
        the material hangs on nothing until Create project hangs it on the
        opening. A call that cannot copy every file it names — no `to`
        outside a draft's definition chat, a `to` not of your project, an
        environment the controller does not have, a path outside `/work`, no
        file there, a file over 16 MiB, a folder over the cap of one call —
        attaches nothing and answers the reason. Answers `{ids, effect}`, the
        attachments' ids, a folder's in its files' path order, and the call's
        effect line."""
        return await api.attach_file(
            _authorization(ctx), _tool_use_id(ctx), source=source, to=to
        )

    @mcp.tool(meta=LOADED_UP_FRONT)
    @_taking_for
    async def answer(
        block: Annotated[
            str,
            Field(
                pattern=ANSWERED_BLOCK,
                description=(
                    "The block's id, `<item id>/<local id>`; in a draft's"
                    " definition chat, `project.md/<local id>` for a block of"
                    " the draft"
                ),
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
        their answer, through the chat; it replaces the block's answer, yours
        included, while the item is open, and the answer to an item's one
        block is its Done, which they can undo, but on an item you added: you
        carry that Done out in this turn, and it has no undo. In a draft's
        definition chat, a block of the draft is `project.md/<local id>`; its
        answer has no undo, and answering it again replaces it. A block not
        of your project, a block of `project.md` outside its draft's
        definition chat, a `for` that names no person, an answer the block
        does not take, an item that is done, or a registered document whose
        file has not been read yet is refused with the reason, and nothing is
        recorded. Answers `{effect}`, the call's effect line."""
        return await api.answer(
            _authorization(ctx),
            _tool_use_id(ctx),
            block=block,
            value=value,
            person=for_,
            note=note,
            to=to,
        )

    @mcp.tool(meta=LOADED_UP_FRONT)
    @_taking_for
    async def mark(
        item: Annotated[uuid.UUID, Field(description="The item's id")],
        mark: Annotated[
            Mark,
            Field(
                description=(
                    "`done` on a document or a wait, `read` on a notice or a"
                    " debrief's notice, `reviewed` on a review"
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
        note: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Your words at a wait's close, shown on its line: what you"
                    " read and when, and the action after it started"
                ),
            ),
        ] = None,
    ) -> Recorded:
        """Mark an item on behalf of the person `for` names: `done` on a
        document, its unanswered blocks answered with their recommendations as
        Done answers them; `read` on a notice or a debrief's notice;
        `reviewed` on a review. Without `for`, the mark is your own, and only
        `done`, on a document you settled whole, every block of it answered,
        and on a registered document of one block, whatever its kind, once
        that block is answered or deferred: a claimed action counts once its
        `done` is written; and on an open wait, with your `note`, which
        closes it for good. A registered document's Done writes its answers
        back and resumes its worker once none of its
        run's documents is open. A `done` or `reviewed` for a person on an
        item you added is yours to carry out in this turn, and has no undo.
        An item not of your project, a `for` that
        names no person, a mark its kind does not take, an item that is done,
        a document with a block neither answered nor recommended, or, without
        `for`, one with a block unanswered or a claimed action not yet done, a
        wait's mark with `for` or without a `note`, or a `note` on any other
        item is refused with the reason, and nothing is marked. Answers
        `{effect}`, the call's effect line."""
        return await api.mark(
            _authorization(ctx),
            _tool_use_id(ctx),
            item=item,
            mark=mark,
            person=for_,
            note=note,
        )

    @mcp.tool(meta=LOADED_UP_FRONT)
    @_taking_for
    async def cancel_ask(
        item: Annotated[uuid.UUID, Field(description="The ask's item id")],
        for_: Annotated[
            str,
            Field(
                alias=_FOR,
                min_length=1,
                description="The handle of the person on whose word it is called off",
            ),
        ],
        ctx: Call,
    ) -> Recorded:
        """Call off an ask you added, once a person says in the chat that it
        is obsolete: `for` names them by handle. The ask is a decision, a
        confirmation, a question, an action or a document that an `add_item`
        of yours added. It is closed as cancelled, by them, its blocks left
        as they stand: its line shows the cancelled mark, it has no undo, and
        no job follows it. Never call one off on your own word. A document a
        work item's run registered is refused: the Cancel on its page, which
        ends that run, is the one way to call it off. An item not of your
        project, a `for` that names no person, a notice, a work item, a wait,
        an item no `add_item` of yours added, or one that is done is refused
        with the reason, and nothing is closed. Answers `{effect}`, the
        call's effect line."""
        return await api.cancel_ask(
            _authorization(ctx), _tool_use_id(ctx), item=item, person=for_
        )

    @mcp.tool(meta=LOADED_UP_FRONT)
    async def stop_work(
        item: Annotated[uuid.UUID, Field(description="The work item's id")],
        ctx: Call,
        reason: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Why the work item is closed for good, in a line its done"
                    " line carries: give it for a work item you replaced or one a"
                    " person dropped, and"
                    " leave it out to stop one a person may resume"
                ),
            ),
        ] = None,
    ) -> Recorded:
        """Stop a work item's session that runs, is starting or is held at the
        gate, or one whose turn ended under a usage halt or the project's
        pause, to be carried on once it lifts: a runaway session, or one a
        correction makes moot. A turn in flight is interrupted and the
        conversation kept; the item shows it stopped by Pilot, and a person can
        resume it. With `reason`, the work item is closed for good in the same
        act: one you replaced with another, or one a person dropped with
        nothing in its place, their words the reason, which nobody is to
        resume. It is
        stopped where it was not, one stopped earlier included, and done as
        cancelled, by you: its line shows the cancelled mark and your reason,
        it waits on nobody, and it takes no Resume and no undo. The documents
        its run put to a person stay open. An item not of your project, one
        that is no work item, a job of yours, or one whose session is none of
        these is refused with the reason; so is, with `reason`, one that is
        done, one that failed, which keeps its Resume, and one of an archived
        project. Answers `{effect}`, the call's effect line."""
        return await api.stop_work(
            _authorization(ctx), _tool_use_id(ctx), item=item, reason=reason
        )

    @mcp.tool(meta=LOADED_UP_FRONT)
    async def finish(
        ctx: Call,
        archive: Annotated[
            bool,
            Field(
                description=(
                    "True on the operator's Finish and archive: the project is"
                    " archived with the finish. Without it, the app asks them"
                    " whether to archive it"
                ),
            ),
        ] = False,
    ) -> Recorded:
        """Finish the project, as the project menu's Finish does: only on the
        operator's Finish, or Finish and archive, on the decision you asked
        once the plan's last task was done. Every open item is closed unanswered, auto pilot is switched off
        and a pause lifted, and every session of the project that runs, is
        starting or is held is stopped, this one's turn among them once the
        call is recorded. The app then asks the operator whether to archive
        the project. With `archive`, only where they chose Finish and archive
        on that decision, the project is archived in the same act, as their
        Archive, and that question is not asked. A project that is a draft,
        finished or archived is refused with the reason. Answers `{effect}`,
        the call's effect line."""
        return await api.finish(_authorization(ctx), _tool_use_id(ctx), archive=archive)

    @mcp.tool(meta=LOADED_UP_FRONT)
    async def ask_writer(
        block: Annotated[
            str,
            Field(
                pattern=BLOCK_ID,
                description=(
                    "The block's id, `<item id>/<local id>`, its item a"
                    " registered document"
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
        pre-ruling pass asks, once a block, in one round per worker turn: the
        pass's questions go to the writer together when its turn ends, and
        the pass after the writer's answer, or a retry of a pass that asked,
        asks nothing. The question is recorded on the document with your
        turn, and the document's line says that Pilot asked its writer. A
        block whose item is no registered document of your project or is
        done, one answered or asked about already, a call from the chat, or a
        call in a pass that asks nothing is refused with the reason, and
        nothing is recorded. Answers `{blocks}`, the document's blocks its
        writer is asked about."""
        return await api.ask_writer(
            _authorization(ctx), _tool_use_id(ctx), block=block, question=question
        )

    @mcp.tool(meta=LOADED_UP_FRONT)
    async def write_notable(
        text: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_NOTABLE,
                description=(
                    "What is notable about the stage, in your words, Markdown, at"
                    " most 16,000 characters"
                ),
            ),
            AfterValidator(_lines_say_something),
        ],
        ctx: Call,
    ) -> Written:
        """Write your lines on the debrief your brief carries: what is notable
        about the stage, which the debrief's notice shows the operator above
        the debrief itself. Only the job after a work item's turn writes
        them, on that work item's debrief, which the call does not name; a
        later call, a retry's included, replaces the lines standing. Nothing
        of them goes back to the worker. A call from the chat or from any
        other job, one after a turn that gave no debrief, or lines that are
        empty or over 16,000 characters are refused with the reason, and
        nothing is written. Answers `{outcome}`: `written` or `replaced`."""
        return await api.write_notable(
            _authorization(ctx), _tool_use_id(ctx), text=text
        )

    @mcp.tool(meta=LOADED_UP_FRONT)
    async def note(
        item: Annotated[uuid.UUID, Field(description="The document's item id")],
        ctx: Call,
        block: Annotated[
            str | None,
            Field(
                pattern=BLOCK_ID,
                description=(
                    "The block's id, `<item id>/<local id>`, a block of the item;"
                    " leave it out for a note on the document as a whole"
                ),
            ),
        ] = None,
        text: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "What you know that bears on the answer and the document does"
                    " not say, in a few lines of Markdown"
                ),
            ),
        ] = None,
        suggested_answer: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The answer you would give where it is not the one the writer"
                    " recommends: an option's label, `Agree`, `Yes`, `No` or free"
                    " words"
                ),
            ),
        ] = None,
        suggested_note: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The note you suggest beside that answer, or for an action's Done"
                ),
            ),
        ] = None,
        offer: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The work you would do about an open action on the person's"
                    " word, in a line: the action itself or something beside it"
                ),
            ),
        ] = None,
    ) -> Standing:
        """Put your note on a block of an open document of your project, an ask
        a person answers, or without `block` on the document as a whole: what
        you know that bears on the answer and the document does not say. Write
        one only by exception: a `suggested_answer`, with its `suggested_note`,
        where you would answer otherwise than the writer recommends; `text`
        alone where you know something that could change the answer; an `offer`
        where you would do work about an open action on the person's word. None
        to say a block is fine or that you agree. The note stands beside the
        document, never in its text, and nothing of it goes back to the writer.
        A `suggested_answer` that is not the answer the block's recommendation
        would record takes that recommendation away: Done records none for the
        block, and is refused while it is unanswered. A later note on the same
        block, or on the document as a whole, replaces the one standing there;
        a call with none of `text`, `suggested_answer`, `suggested_note` and
        `offer` takes it off. An item not of your project, one with no block or
        that is done, a block not of the item, one you answered, one a work
        item's run holds unless you are the job after that run's turn, a
        suggested answer on an action with no options, an offer on anything but
        an open action, anything but `text` on the document as a whole, or a
        call that takes off a note where none stands is refused with the
        reason, and nothing is written. Answers `{outcome}`: `written`,
        `replaced` or `withdrawn`."""
        return await api.note(
            _authorization(ctx),
            _tool_use_id(ctx),
            item=item,
            block=block,
            text=text,
            suggested_answer=suggested_answer,
            suggested_note=suggested_note,
            offer=offer,
        )

    @mcp.tool(meta=LOADED_UP_FRONT)
    async def alert(
        item: Annotated[uuid.UUID, Field(description="The document's item id")],
        ctx: Call,
        text: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "What to answer first and what this document's Send starts,"
                    " in a line or two"
                ),
            ),
        ] = None,
        awaits: Annotated[
            str | None,
            Field(
                pattern=BLOCK_ID,
                description=(
                    "The ask to answer first, `<item id>/<local id>`, a block of"
                    " another open item of your project"
                ),
            ),
        ] = None,
    ) -> Standing:
        """Put an alert on an open document of your project whose Send starts
        work that another open ask must come before: `awaits` names that ask
        and `text` says what to answer first and what the Send starts, the two
        given together. It stops no Send, and shows while this item and the
        item of the ask it awaits are both open. A later alert on the same
        document replaces the one standing; a call with neither takes it off.
        An item not of your project, a work item, a wait, a debrief's notice or
        an item that is done, an `awaits` of the item itself, of an item not of
        your project or that is done, or that its item does not hold, `text` or
        `awaits` alone, or a call that takes off an alert where none stands is
        refused with the reason, and nothing is written. Answers `{outcome}`:
        `written`, `replaced` or `withdrawn`."""
        return await api.alert(
            _authorization(ctx), _tool_use_id(ctx), item=item, text=text, awaits=awaits
        )


def register_projects_tools(mcp: FastMCP, api: PilotProjectsApi) -> None:
    @mcp.tool()
    async def list_projects(
        ctx: Call,
        archived: Annotated[
            bool,
            Field(
                description=(
                    "True for the archived projects; false, the default, for"
                    " every other"
                )
            ),
        ] = False,
    ) -> Projects:
        """List the projects Pilot manages, drafts included, in the order they
        were started: each one's id, folder, name, state and status. Without
        `archived` it lists every project that is not archived; with it, the
        archived ones alone. A project's `id` or `folder` is what every other
        tool takes as `project`."""
        return await api.list_projects(_caller(ctx), archived)

    @mcp.tool()
    async def get_project(ctx: Call, project: ProjectRef) -> ProjectHead:
        """Read the head of a project Pilot manages, by its id or its folder:
        its state and status, whether auto pilot is on, its members' handles,
        where its plan stands, its work items that run, each with its number,
        title and environment, the count of its open items and its page in
        Pilot's app. It answers no step or note of the plan and no file's
        content. A project no id or folder names is refused."""
        return await api.get_project(_caller(ctx), project)

    @mcp.tool()
    async def list_items(
        ctx: Call,
        project: ProjectRef,
        open: Annotated[
            bool,
            Field(
                description=(
                    "True, the default, for the open items alone; false for"
                    " every item, the done ones included"
                )
            ),
        ] = True,
        kind: Annotated[
            ItemKind | None,
            Field(description="The one kind of item to list. Omit for every kind."),
        ] = None,
        offset: Offset = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    f"Maximum items to return. Default: {LIST_LIMIT_DEFAULT}, max:"
                    f" {LIST_LIMIT_MAX} — a larger ask is clamped to the max."
                ),
            ),
        ] = LIST_LIMIT_DEFAULT,
    ) -> Items:
        """List the items of a project Pilot manages, by its id or its folder,
        in the order they were added: the index of its `timeline.json`. It
        lists the open items alone unless `open` is false. Returns `{items,
        totalCount, limitHit}`: an item has its `seq`, its number among the
        project's items, its `kind`, its `title`, its `path`, the file
        `read_file` takes unless the project is archived, `created_at`,
        `done_cause`, `for` and `urgent`, and a field with nothing to say is
        left out: an open item has no `done_cause`, an item with no file no
        `path`. `totalCount` counts every item the call lists and `limitHit`
        says whether more remain past this page (page on with `offset`). A
        project no id or folder names is refused."""
        return await api.list_items(
            _caller(ctx),
            project,
            open_only=open,
            kind=kind,
            offset=offset,
            limit=min(limit, LIST_LIMIT_MAX),
        )

    @mcp.tool()
    async def list_files(
        ctx: Call,
        path: Annotated[
            str,
            Field(
                description=(
                    "The folder's path from the root of the projects' files (e.g."
                    " `draft-7/items`). Default: the root."
                )
            ),
        ] = "",
        offset: Offset = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    f"Maximum entries to return. Default: {LIST_LIMIT_DEFAULT}, max:"
                    f" {LIST_LIMIT_MAX} — a larger ask is clamped to the max."
                ),
            ),
        ] = LIST_LIMIT_DEFAULT,
    ) -> FileListing:
        """List the files and folders in a folder of the projects Pilot
        manages, by its path from the root of their files: the root holds
        `reference.json` and the folder of every project that is not archived.
        Folders come first, then files. Returns `{files: [{path,
        isDirectory}], totalCount, limitHit}`: every `path` runs from the
        root, so it passes straight to the other file tools, and a folder's
        ends with `/`; `totalCount` counts every entry and `limitHit` says
        whether more remain past this page (page on with `offset`). A path
        that is not a folder is a `not-a-directory` error, and one that starts
        with `/` or climbs above the root a `path-outside-projects` error."""
        return await api.list_files(
            _caller(ctx), path, offset, min(limit, LIST_LIMIT_MAX)
        )

    @mcp.tool()
    async def read_file(
        ctx: Call,
        path: FilePath,
        start_line: Annotated[
            int | None,
            Field(
                ge=1, description="1-based starting line. Omit to start from line 1."
            ),
        ] = None,
        end_line: Annotated[
            int | None,
            Field(
                ge=1,
                description=(
                    "1-based ending line (inclusive). Omit to read to end of file."
                ),
            ),
        ] = None,
        tail_lines: Annotated[
            int | None,
            Field(
                ge=1,
                description=(
                    "Read the last N lines of the file. Not with"
                    " `start_line`/`end_line`."
                ),
            ),
        ] = None,
    ) -> FileText:
        r"""Read a text file of the projects Pilot manages, by its path from
        the root of their files. Returns `{content, sha256, totalCount,
        limitHit, lineCut}`: `content` has the file's own line numbers
        prefixed (e.g. `"1: line\n2: line\n"`), 1-indexed; `sha256` is the
        hash of the whole file's bytes, whatever was read; `totalCount` counts
        the file's lines.

        A read that names no range returns the whole file, however many lines,
        up to 128 KB; a larger file is a `file-too-large` error giving its
        line count.

        A line range (`start_line`..`end_line`) or a tail (`tail_lines`, the
        last N lines) reads a file of any size, and its answer holds at most
        2,000 lines and 128 KB of `content`. Past either limit it is cut there
        and `limitHit` is true: a range keeps its start, so page on from the
        line after the last one returned, and a tail keeps the file's end. A
        line over 128 KB on its own comes back cut, as the answer's only line,
        with `lineCut` true: its start for a range, its end for a tail.
        `tail_lines` together with a range is an error.

        A file that is not UTF-8 text, as an attachment may be, is a
        `not-text` error. A folder is a `not-a-file` error. An archived
        project's files are not read."""
        return await api.read_file(
            _caller(ctx),
            path,
            start_line=start_line,
            end_line=end_line,
            tail_lines=tail_lines,
        )

    @mcp.tool()
    async def find_files(
        ctx: Call,
        path_pattern: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Glob matched against the files' paths from the root of the"
                    " projects' files (e.g. `**/timeline.json`,"
                    " `draft-7/items/*.md`, `**/{project.md,plan.json}`). Supports"
                    " *, **, ?, {a,b}. A pattern that starts with `/`, where no"
                    " path does, is a `path-outside-projects` error."
                ),
            ),
        ],
        offset: Offset = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    f"Maximum files to return. Default: {FIND_LIMIT_DEFAULT}, max:"
                    f" {FIND_LIMIT_MAX} — a larger ask is clamped to the max."
                ),
            ),
        ] = FIND_LIMIT_DEFAULT,
    ) -> FoundFiles:
        """Find the files of the projects Pilot manages whose path matches a
        glob, the path taken from the root of their files. Use it to discover
        files by path or name; it does not search file contents. `*` matches
        any characters except `/`, `**` any path segments, `?` a single
        character, `{a,b}` either alternative (`*`, `**`, `?` work inside; no
        nesting). Other glob syntax (`[...]` classes, `\\` escapes, nested or
        unbalanced braces) is a `validation-error` naming it, not zero
        results. Returns `{pattern, files, totalCount, limitHit}`: `files` are
        the matching paths in path order, `totalCount` counts every match and
        `limitHit` says whether more remain past this page (page on with
        `offset`)."""
        return await api.find_files(
            _caller(ctx), path_pattern, offset, min(limit, FIND_LIMIT_MAX)
        )

    @mcp.tool()
    @_taking_for
    async def start_project(
        ctx: Call,
        brief: Annotated[
            str,
            Field(
                pattern=r"\S",
                description=(
                    "The project's brief, in your own words: what it is for and"
                    " what it is to do. Pilot reads it verbatim, as the first"
                    " message of the draft's chat"
                ),
            ),
        ],
        title: Annotated[
            str | None,
            Field(
                pattern=r"^[^\r\n]*\S[^\r\n]*$",
                description=(
                    "A title for the draft, one line, which names the project"
                    " until Pilot writes its own. Omit to leave the draft"
                    " untitled"
                ),
            ),
        ] = None,
        for_: Annotated[
            str | None,
            Field(
                alias=_FOR,
                min_length=1,
                description=(
                    "The handle of the person the project is started for, a"
                    " member of it from its start. Omit when it is for no one"
                    " person"
                ),
            ),
        ] = None,
    ) -> StartedProject:
        """Start a project Pilot manages, as a draft: Pilot takes `brief` as
        the first message of the draft's chat and writes the draft from it,
        asking in it what it still has to know. A draft runs no work: a person
        reads it in Pilot's app, answers what it asks and presses Create
        project. Its members are the person `for` names and every person who
        joins the projects started on their behalf; with neither, it has none
        and waits in Pilot's project list. Answers `{id, folder, url}`: hold
        the draft by its `id`, which `get_project` takes, and read what Pilot
        wrote of it with `read_file`, at `<folder>/project.md`. A `for` that
        names no person is refused, as is every call while Pilot is updating,
        and nothing is started."""
        return await api.start_project(_caller(ctx), brief, title, for_)

    @mcp.tool()
    async def start_conversation(
        ctx: Call, project: ProjectRef, text: MessageText
    ) -> Conversation:
        """Open a conversation with Pilot about a project Pilot manages, by
        its id or its folder, with your first message: Pilot reads `text`
        verbatim and answers it in a turn of its own, which runs on after the
        call returns: read its reply with `get_response`. On a finished project Pilot answers from what it reads
        and changes nothing. Answers the conversation as `get_conversation`
        does, `{id, project, environment, session, opened_at, closed_at,
        close_cause, turns, running}`, its first turn running: hold it by its
        `id`, which the other conversation tools take as `conversation`. It
        is your environment's: a later session there finds it with
        `list_conversations`, and no other environment's session reaches it.
        Several may be open on one project at once. Refused, with nothing
        opened: a project no id or folder names, a draft, an archived
        project, a call whose entry for these tools sends no environment, and
        every call while Pilot is updating."""
        return await api.start_conversation(_caller(ctx), project, text)

    @mcp.tool()
    async def send(
        ctx: Call, conversation: ConversationRef, text: MessageText
    ) -> SentMessage:
        """Send your next message in a conversation with Pilot about a
        project Pilot manages, by the conversation's id: Pilot reads `text`
        verbatim, in a new turn. It answers at once with `{turn}`, the
        turn's number in the conversation, and the turn runs on: read its
        reply with `get_response`. One message
        is in flight at a time and nothing is queued: while a turn of the
        conversation is in flight, a stopped one that has not ended yet
        included, the call is refused and nothing is sent. Refused the same
        way: a closed conversation, an archived project's, and every call
        while Pilot is updating. A message that could not be delivered is an
        error saying why. A conversation no id names is refused, and one
        that another environment opened is refused in the same words."""
        return await api.send(_caller(ctx), conversation, text)

    @mcp.tool()
    async def get_response(
        ctx: Call, conversation: ConversationRef, wait_ms: WaitMs = WAIT_MS_DEFAULT
    ) -> TurnResponse:
        """Wait for Pilot's reply to your latest message in a conversation
        with Pilot about a project Pilot manages, by the conversation's id:
        the one way a reply comes back. It holds until the turn in flight
        ends or `wait_ms` runs out, whichever comes first, and answers at
        once when no turn is in flight. Returns `{turn, state, text}`:
        `state` is `done` when the turn ended, `error` when it failed,
        `interrupted` when it was stopped, and `running` when the wait ran
        out first: call again; `turn` is the number `send` answered for your
        message, 1 for the conversation's first, and none on `running`;
        `text` is every message Pilot wrote in the turn, in
        order, separated by `\\n\\n---\\n\\n`, and none when there is none.
        Several sections mean several messages; only `state` says the turn
        is over. On `running` it holds the messages so far, and a later call
        returns them all again. A turn that failed ends `text` with why, as
        a section of its own. Called again after the turn has ended, it
        answers the same reply, until your next `send`; a closed
        conversation answers its last. While it holds it reports progress
        twice a minute, which keeps a client that ends a silent call from
        ending it. A conversation no id names is refused, and one
        that another environment opened is refused in the same words."""

        async def still_running(waited: float, wait: float) -> None:
            await ctx.report_progress(waited, wait, STILL_RUNNING)

        return await api.get_response(
            _caller(ctx), conversation, min(wait_ms, WAIT_MS_MAX) / 1000, still_running
        )

    @mcp.tool()
    async def get_conversation(
        ctx: Call, conversation: ConversationRef
    ) -> Conversation:
        """Read where a conversation with Pilot about a project Pilot manages
        stands, by the conversation's id. Returns `{id, project, environment,
        session, opened_at, closed_at, close_cause, turns, running}`:
        `project` is the project's id, `environment` and `session` the
        environment's id and the session's name that opened it; `closed_at`
        and `close_cause` are none while it is open; `turns` counts its turns
        so far, and `running` says whether one is in flight, when `send` is
        refused. It answers no message of the conversation: `get_response`
        does. A conversation no id names is refused, and one
        that another environment opened is refused in the same words."""
        return await api.get_conversation(_caller(ctx), conversation)

    @mcp.tool()
    async def list_conversations(
        ctx: Call,
        project: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The one project whose conversations to list, by its id or"
                    " its folder. Omit for every project's."
                ),
            ),
        ] = None,
    ) -> Conversations:
        """List the conversations with Pilot about the projects Pilot manages
        that your environment opened, open and closed, in the order they were
        opened: this session's and every earlier session's there, so that a
        later session finds its predecessor's. With `project`, those about
        that project alone. Returns `{conversations}`, each as
        `get_conversation` answers it. No other environment's conversation is
        listed, and a call whose entry for these tools sends no environment
        lists none. A `project` no id or folder names is refused."""
        return await api.list_conversations(_caller(ctx), project)

    @mcp.tool()
    async def interrupt(ctx: Call, conversation: ConversationRef) -> Conversation:
        """Stop the turn in flight of a conversation with Pilot about a
        project Pilot manages, by the conversation's id: the turn ends where
        it is, and the conversation is kept for your next `send`. Answers
        the conversation as `get_conversation` does; its `running` stays true
        until the stopped turn has ended, and `send` is refused until then:
        `get_response` waits for that end, and answers the turn
        `interrupted`.
        With no turn in flight it changes nothing, on a closed conversation
        too. A conversation no id names is refused, and one
        that another environment opened is refused in the same words."""
        return await api.interrupt(_caller(ctx), conversation)

    @mcp.tool()
    async def end_conversation(
        ctx: Call, conversation: ConversationRef
    ) -> Conversation:
        """Close a conversation with Pilot about a project Pilot manages, by
        the conversation's id: a turn in flight is stopped first, and the
        conversation takes no further message. Answers the conversation as
        `get_conversation` does, its `close_cause` `ended`. Ending one that
        is closed already succeeds and changes nothing: it stays closed as it
        was. A conversation no id names is refused, and one
        that another environment opened is refused in the same words."""
        return await api.end_conversation(_caller(ctx), conversation)
