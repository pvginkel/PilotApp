"""`pilot-work`'s tools (F85, FM §5 step 1), a worker's, `pilot-store`'s
(F86, TD §4.5), the brain's, and `pilot-projects`' (F150), any session's, each
one call to its route.

A tool's docstring is the description the session reads, and each parameter's
is in its annotation: they are the surface, not commentary
(`tests/pilot_mcp/test_server.py` pins them). The bearer a call to the first
two carries is the API's to resolve; a tool passes it on as it came, with the
tool-use id Claude Code sends in the call's `_meta`, which the call's effect
names, where it records one. A call to `pilot-projects` hands on its caller,
never its bearer (`api.py`), and its words are the outside's (F150.3): Pilot,
a project, its items and documents.
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
    BLOCK_ID,
    ENVIRONMENT_HEADER,
    FIND_LIMIT_DEFAULT,
    FIND_LIMIT_MAX,
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_MAX,
    MAX_STEP_CODE,
    MAX_STEPS,
    SESSION_HEADER,
    SOURCE,
    Added,
    Asked,
    AttachedFiles,
    AttachedMaterial,
    Caller,
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
    RegisteredDocument,
    StartedProject,
    Step,
    StepState,
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
        `code`, your name for it, a `label`, its words, and a `state`,
        `pending`, `active` or `done`. The list replaces the one standing: a
        code already on it keeps its state where you give none, a new code
        starts `pending`, a code left out goes, and `[]` removes the list.
        Where the work grows, add a step; a second round of a step is a step
        of its own. Pilot stamps each step's start and end by its own clock.
        An empty or repeated code, an empty label, a state outside the three,
        a code over 64 characters, a label over 120 or a list over 100 steps
        is refused with the reason, and nothing changes. Answers `{steps}`,
        the list as it stands."""
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


def register_store_tools(mcp: FastMCP, api: PilotStoreApi) -> None:
    @mcp.tool()
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
        `markdown`, minted with it. A work item is started on add in an
        environment Pilot makes from `repo`, on your placement, its first turn
        your `brief` followed by Pilot's own lines; `state` answers whether it
        is `starting` or `held` at the gate, and `held` why — say so to the
        person. A work item that does actions you claimed names them in
        `claims`: each stays open and yours until its `done`, its line naming
        this work item, the latest that names it. A work item that checks a
        fact for blocks you left unanswered names them in `researches`: each
        line names this work item, the latest that names it, and the job
        after its turn gives them to you to route. A wait is recorded with its
        `title`, a card wait's `cards` and `states` or a timed wait's
        `due_at`, and is fixed from then on: Pilot fires it and never closes
        it; you close it with your own `mark` `done` and its `note`, and to
        change it you close it and add another. A field the kind does not
        take or one it needs missing, a text with no title or with faults, a
        wait's list empty or naming one twice, a card that is no ticket id, a
        due time not ahead, an attachment or a plan task not of your project,
        material that cannot be copied, a claim that is not an open action of
        a registered document of your project, a research of a block that is
        answered or not in an open registered document of your project, or a
        start the project refuses is refused with the reason, each fault with
        its line, and nothing is added. Answers `{id, path, state, held,
        effect}`."""
        return await api.add_item(_authorization(ctx), _tool_use_id(ctx), item)

    @mcp.tool()
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

    @mcp.tool()
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
        their answer, through the chat, which they can undo; it replaces the
        block's answer, yours included, while the item is open, and the answer
        to an item's one block is its Done. In a draft's definition chat, a
        block of the draft is `project.md/<local id>`; its answer has no undo,
        and answering it again replaces it. A block not of your project, a
        block of `project.md` outside its draft's definition chat, a `for`
        that names no person, an answer the block does not take, an item that
        is done, or a registered document whose file has not been read yet is
        refused with the reason, and nothing is recorded. Answers
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
                    "`done` on a document or a wait, `read` on a notice,"
                    " `reviewed` on a review"
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
        Done answers them; `read` on a notice; `reviewed` on a review. Without
        `for`, the mark is your own, and only `done`, on a document you settled
        whole, every block of it answered, and on a registered document of one
        block, whatever its kind, once that block is answered or deferred: a
        claimed action counts once its `done` is written; and on an open wait,
        with your `note`, which closes it for good. A registered document's
        Done writes its answers back and resumes its worker once none of its
        run's documents is open. An item not of your project, a `for` that
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

    @mcp.tool()
    async def stop_work(
        item: Annotated[uuid.UUID, Field(description="The work item's id")],
        ctx: Call,
    ) -> Recorded:
        """Stop a work item's session that runs, is starting or is held at the
        gate, or one whose turn ended under a usage halt or the project's
        pause, to be carried on once it lifts: a runaway session, or one a
        correction makes moot. A turn in flight is interrupted and the
        conversation kept; the item shows it stopped by Pilot, and a person can
        resume it. An item not of your project, one that is no work item, a job
        of yours, or one whose session is none of these is refused with the
        reason. Answers `{effect}`, the call's effect line."""
        return await api.stop_work(_authorization(ctx), _tool_use_id(ctx), item=item)

    @mcp.tool()
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

    @mcp.tool()
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
