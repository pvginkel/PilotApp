"""The MCP process's clients of the API, one call per tool.

- `pilot-work`'s (`app/api/pilot_work.py`) and `pilot-store`'s
  (`app/api/pilot_store.py`) call the tools' routes under the bearer the
  tool's caller presented, which the API resolves to its Session, with the
  call's tool-use id where it has one.
- `pilot-projects`' calls the API's own routes under `/api/`, under the
  service user's token (`credential.py`) and never the caller's bearer, which
  its door has checked (F150.13), with the caller's environment and session
  as the call's two headers carried them. Its lists of items and files are
  paged here, as KubeCoder's fleet adapter pages its own: their routes answer
  a list whole. A conversation's tools call `/api/conversations`
  (`app/api/conversations.py`), which reads whose a conversation is from
  those two headers; a message whose send failed is its tool's error.
  `get_response` alone holds its call (F150.10): it asks the API where the
  conversation stands every `POLL_SECONDS`, each ask answered at once, until
  no turn is in flight or its wait is over, then reads the reply once, and
  reports progress to its caller every `PROGRESS_SECONDS` meanwhile. No
  request of it waits in the API.

An answer outside 2xx is a `ToolError` carrying the API's `error`, its reason
whole, or the answer's status where it is not the API's envelope; an API that
does not answer is one naming that.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol, Self

import httpx
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from pydantic.alias_generators import to_camel

from pilot_mcp.credential import ServiceCredential

TOOL_USE_ID_HEADER = "Tool-Use-Id"
"""The header the routes read a call's tool-use id from
(`app/services/effect_service.py`)."""

_TIMEOUT = httpx.Timeout(300.0, connect=5.0)

WAIT_MS_DEFAULT = 900_000
WAIT_MS_MAX = 3_600_000
"""`get_response`'s wait, in ms, where its call gives none, and the most it
holds, KubeCoder's `get_session_response`'s own (F150.10)."""

POLL_SECONDS = 2.0
"""How long a held `get_response` leaves between two asks of where its
conversation stands."""

PROGRESS_SECONDS = 30.0
"""The seconds after which a held `get_response` tells its caller it still
waits, read after each ask: two progress notifications are this, one sleep
and one ask apart at most. Claude Code ends a tool call that sent no
response or progress for 300 s."""

_POLL_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
"""The timeout of one ask of a held `get_response`: no progress is reported
while an ask is out."""

Mark = Literal["done", "read", "reviewed"]

SOURCE = r"^[^:\s/]+:/.*$"
"""A source, `<environment>:<path>`: an environment id has no colon, and a
path starts with `/`."""

_REPO = r"^[^/\s]+/[^/\s]+$"

_ATTACHMENT = r"^([0-9A-Fa-f-]{36}|[^:\s/]+:/.*)$"
"""An attachment's id, or a source."""

BLOCK_ID = r"^[0-9A-Fa-f-]{36}/\S+$"
"""A block's id (TD §4.9), `<item id>/<local id>`."""

StepState = Literal["pending", "active", "done"]

MAX_STEP_CODE = 64
MAX_STEP_LABEL = 120
MAX_STEP_WHY = 120
MAX_STEPS = 100
"""The limits of a work item's list of steps, as its route takes them
(`app/schemas/pilot_work.py`)."""

MAX_DEBRIEF = 16_000
MAX_DEBRIEF_ENTRIES = 500
MAX_ENTRY_SECTION = 120
MAX_ENTRY_ROLE = 64
MAX_ENTRY_WORDS = 4_000
MAX_ENTRY_WHY = 120
MAX_ENTRY_NUMBER = 2**31 - 1
"""The limits of a work item's debrief, as its route takes them
(`app/schemas/pilot_work.py`)."""


class NewItem(BaseModel):
    """An item to add, in `timeline.json`'s shape."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "decision",
        "question",
        "action",
        "notice",
        "document",
        "review",
        "work",
        "card_wait",
        "timed_wait",
    ] = Field(
        description=(
            "`decision`, `question`, `action`, `notice`, `document` or `review`"
            " for a prose item, `work` for a work item, `card_wait` or"
            " `timed_wait` for a wait"
        )
    )
    title: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The title it is born with in its file's front matter, where"
            " `markdown` gives none; a prose item without `markdown` needs it, and"
            " a work item and a wait, whose line shows it"
        ),
    )
    markdown: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "A short prose item's whole text, minted with it and parsed now: its"
            " own front-matter `title` stands, else `title` is written in"
        ),
    )
    step: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The id of the plan's task it serves: a prose item's front matter"
            " where `markdown` gives none, a work item's brief"
        ),
    )
    urgent: bool = Field(
        default=False,
        description=(
            "A prose item that is urgent: `urgent: true` in its front matter where"
            " `markdown` gives none"
        ),
    )
    for_: str | None = Field(
        default=None,
        alias="for",
        min_length=1,
        description=(
            "The handle of the person a prose item is for, in its front matter"
            " where `markdown` gives none"
        ),
    )
    summary: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "A prose item's summary, in its front matter where `markdown` gives none"
        ),
    )
    attachments: list[Annotated[str, Field(pattern=_ATTACHMENT)]] = Field(
        default_factory=list,
        description=(
            "What it carries, hung on it in this order: an attachment already"
            " made, by its id, or material copied in now as `attach_file` copies"
            " it, `<environment>:<path>`"
        ),
    )
    repo: str | None = Field(
        default=None,
        pattern=_REPO,
        description=(
            "A work item's repository, `owner/Name`: Pilot makes its environment"
            " from it"
        ),
    )
    cwd: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "A work item's working directory in its environment, a checkout"
            " under `/work`: the repository's own, `/work/<Name>`, or one its"
            " manifest checks out beside it"
        ),
    )
    brief: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "A work item's brief, its first turn, yours; Pilot appends the plan"
            " task it serves, the switch and the project's handbook"
        ),
    )
    agent: str | None = Field(
        default=None, min_length=1, description="A work item's agent, where given"
    )
    model: str | None = Field(
        default=None, min_length=1, description="A work item's model, where given"
    )
    reasoning_effort: str | None = Field(
        default=None,
        min_length=1,
        description="A work item's reasoning effort, where given",
    )
    claims: list[Annotated[str, Field(pattern=BLOCK_ID)]] = Field(
        default_factory=list,
        description=(
            "The actions of workers' documents or of items you added that a"
            " work item does and you claimed, by their blocks' ids, `<item"
            " id>/<local id>`: each block's line names this work item, and the"
            " job after its turn names them for their `done`"
        ),
    )
    cards: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        description=(
            "A card wait's cards, one or more ticket ids, each named once: it"
            " fires whenever one of them enters one of `states`"
        ),
    )
    states: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        description=(
            "A card wait's states, one or more of the tracker's names, each named"
            " once, matched whatever their case: list the states that derail the"
            " wait beside the one you hope for, since nothing else fires it"
        ),
    )
    due_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "A timed wait's due time, with its offset, ahead of now: it fires"
            " once when it comes"
        ),
    )
    researches: list[Annotated[str, Field(pattern=BLOCK_ID)]] = Field(
        default_factory=list,
        description=(
            "The blocks of workers' documents you left unanswered while a work"
            " item checks a fact their answers rest on, by their ids, `<item"
            " id>/<local id>`: each block's line names this work item, and the"
            " job after its turn names them for you to route"
        ),
    )


class RegisteredDocument(BaseModel):
    """The registered document."""

    id: uuid.UUID = Field(
        description="Its item's id on the project's timeline, `attach_file`'s `to`"
    )


class AttachedFiles(BaseModel):
    """The attachments the material was copied into."""

    ids: list[uuid.UUID] = Field(
        description="Their ids, one per file, a folder's in its files' path order"
    )


class Recorded(BaseModel):
    """What the call changed."""

    effect: str = Field(
        description=(
            "Its effect line, `<verb> · <what>`, as it shows where the call ran"
        )
    )


class Added(BaseModel):
    """The item added."""

    id: uuid.UUID = Field(description="Its id, as `timeline.json` gives it")
    path: str | None = Field(
        description=(
            "A prose item's file, its absolute path, which you fill; none for a"
            " work item or a wait"
        )
    )
    state: Literal["starting", "held"] | None = Field(
        description=(
            "A work item's session: `starting`, or `held` at the gate; none for"
            " a prose item or a wait"
        )
    )
    held: (
        Literal[
            "week_halt", "five_hour_halt", "paused", "controller_unreachable", "slot"
        ]
        | None
    ) = Field(
        description=(
            "Why a held work item waits: the week's or the five-hour usage halt"
            " holds work items, the project is paused, the controller is"
            " unreachable, or no slot is free; none otherwise"
        )
    )
    effect: str = Field(
        description=(
            "Its effect line, `<verb> · <what>`, as it shows where the call ran"
        )
    )


class AttachedMaterial(BaseModel):
    """The attachments the material was copied into."""

    ids: list[uuid.UUID] = Field(
        description="Their ids, one per file, a folder's in its files' path order"
    )
    effect: str = Field(
        description=(
            "Its effect line, `<verb> · <what>`, as it shows where the call ran"
        )
    )


class Asked(BaseModel):
    """The document's blocks its writer is asked about."""

    blocks: list[str] = Field(
        description=(
            "Their local ids, the block this call asked about among them, in"
            " their order in the document"
        )
    )


class Step(BaseModel):
    """A step of your work item's list."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=MAX_STEP_CODE,
        description=(
            "Your name for the step, unique in the list, at most 64 characters:"
            " `set_progress_step` takes it"
        ),
    )
    label: str = Field(
        min_length=1,
        max_length=MAX_STEP_LABEL,
        description="The step's words on the tile, at most 120 characters",
    )
    state: StepState | None = Field(
        default=None,
        description=(
            "`pending`, `active` or `done`; without it, a code already on the"
            " list keeps its state and a new one starts `pending`"
        ),
    )
    why: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_STEP_WHY,
        description=(
            "A short line shown under the step's label, at most 120 characters;"
            " without it, the step has none"
        ),
    )


class PublishedStep(BaseModel):
    """A step of your work item's list as it stands."""

    code: str = Field(description="Your name for the step")
    label: str = Field(description="Its words on the tile")
    state: StepState = Field(description="`pending`, `active` or `done`")
    why: str | None = Field(
        default=None, description="Its line under the label; none where not given"
    )


class DebriefEntry(BaseModel):
    """One account of your work item's debrief."""

    model_config = ConfigDict(extra="forbid")

    section: str = Field(
        min_length=1,
        max_length=MAX_ENTRY_SECTION,
        description=(
            "The name of the part of the run it ran in, at most 120 characters:"
            " consecutive entries of one name show as one section"
        ),
    )
    round: int = Field(
        ge=1,
        le=MAX_ENTRY_NUMBER,
        strict=True,
        description="Its round of that part, 1 or more",
    )
    role: str = Field(
        min_length=1,
        max_length=MAX_ENTRY_ROLE,
        description="Whose account it is, at most 64 characters",
    )
    duration: int = Field(
        ge=0,
        le=MAX_ENTRY_NUMBER,
        strict=True,
        description="The time its turn took, in whole seconds",
    )
    words: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_ENTRY_WORDS,
        description=(
            "The account, in its own words, at most 4,000 characters; none with"
            " `passed`"
        ),
    )
    passed: bool | None = Field(
        default=None,
        strict=True,
        description="A pass or a fail in place of words; none with `words`",
    )
    why: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_ENTRY_WHY,
        description=(
            "On an entry that opens a round past the first, why that round was"
            " needed, at most 120 characters"
        ),
    )

    @model_validator(mode="after")
    def _words_or_a_result(self) -> Self:
        if self.words is not None and self.passed is not None:
            raise ValueError("an entry gives at most one of words and passed")
        return self


class RegisteredDebrief(BaseModel):
    """The debrief stored."""

    entries: int = Field(description="The number of its entries")


class Progress(BaseModel):
    """Your work item's list of steps as it stands."""

    steps: list[PublishedStep] = Field(description="Its steps, in order")


ENVIRONMENT_HEADER = "X-Pilot-Environment"
SESSION_HEADER = "X-Pilot-Session"
"""The two headers of a call to `pilot-projects` that name its caller: the
id of the environment it calls from, and its session's name there. The
operator's entry in `~/.claude.json` is written against them (F150.1)."""


@dataclass(frozen=True)
class Caller:
    """Who calls `pilot-projects`: the environment's id and the session's
    name, each none where its header is absent or empty (DB decision 77)."""

    environment: str | None
    session: str | None

    def headers(self) -> dict[str, str]:
        """The caller as the two headers, one that is none not sent."""
        return _given(
            **{ENVIRONMENT_HEADER: self.environment, SESSION_HEADER: self.session}
        )


ProjectState = Literal["draft", "open", "finished", "adopted"]

ProjectStatus = Literal[
    "running",
    "waiting_on_you",
    "waiting_on_event",
    "done",
    "idle",
    "pausing",
    "paused",
]

_STATE = (
    "`draft` until Create project, then `open`, and `finished` once finished;"
    " `adopted` for a project that stands for a group of slices run before"
    " Pilot, which is archived from its birth and never opened"
)

_STATUS = (
    "`paused`, or `pausing` while a turn of its work still runs; else `running`"
    " while Pilot or a work item of the project works, `waiting_on_you` while"
    " an open item waits on a member, `waiting_on_event` while it waits on a"
    " card or a time, `done` once every step of its plan is done, `idle`"
    " otherwise; none for a draft and a finished project"
)

_FOLDER = (
    "Its folder, the first segment of its files' paths: `draft-<number>` while"
    " a draft, its slug once created"
)


class ListedProject(BaseModel):
    """A project Pilot manages, as the list shows it."""

    id: uuid.UUID = Field(description="Its id, which names it for good")
    folder: str = Field(description=_FOLDER)
    name: str | None = Field(description="Its name; none while a draft has no title")
    state: ProjectState = Field(description=_STATE)
    status: ProjectStatus | None = Field(description=_STATUS)


class Projects(BaseModel):
    """The projects Pilot manages, of one list."""

    projects: list[ListedProject] = Field(
        description="A row per project, in the order they were started"
    )


class PlanProgress(BaseModel):
    """Where the project's plan stands."""

    done: int = Field(description="The plan's steps done")
    total: int = Field(description="The plan's steps")
    in_progress: list[str] = Field(
        description="The titles of the steps in progress, in the plan's order"
    )


class RunningWork(BaseModel):
    """A work item of the project that runs or waits to start."""

    seq: int = Field(description="Its number among the project's items")
    title: str | None = Field(description="Its title")
    environment: str | None = Field(
        description=(
            "The name of the environment it runs in; none while it waits to start"
        )
    )


class ProjectHead(BaseModel):
    """The head of a project Pilot manages."""

    id: uuid.UUID = Field(description="Its id, which names it for good")
    folder: str = Field(description=_FOLDER)
    name: str | None = Field(description="Its name; none while a draft has no title")
    state: ProjectState = Field(description=_STATE)
    archived: bool = Field(
        description="Whether it is archived: an archived project's files are not read"
    )
    status: ProjectStatus | None = Field(description=_STATUS)
    autopilot: bool = Field(description="Whether auto pilot is on")
    members: list[str] = Field(
        description="Its members' handles, in the order they joined"
    )
    progress: PlanProgress
    running_work: list[RunningWork] = Field(
        description="Its work items that run or wait to start, in their order"
    )
    open_items: int = Field(
        description="The count of its open items, `running_work` not counted"
    )
    url: str = Field(description="Its page in Pilot's app")


class StartedProject(BaseModel):
    """The draft a call started."""

    id: uuid.UUID = Field(description="Its id, which names it for good")
    folder: str = Field(
        description=(
            "Its folder, the first segment of its files' paths: `draft-<number>`"
            " until Create project gives the project its slug"
        )
    )
    url: str = Field(description="Its page in Pilot's app")


ConversationCloseCause = Literal["ended", "timeout", "finished", "reopened", "archived"]


class Conversation(BaseModel):
    """A conversation with Pilot about a project, as it stands."""

    id: uuid.UUID = Field(
        description="Its id, which the other conversation tools take as `conversation`"
    )
    project: uuid.UUID = Field(
        description="The id of the project it is about, which `get_project` takes"
    )
    environment: str = Field(
        description="The id of the environment whose session opened it"
    )
    session: str | None = Field(
        description="The name of the session that opened it; none where it gave none"
    )
    opened_at: str = Field(description="When it was opened, in UTC")
    closed_at: str | None = Field(
        description="When it was closed, in UTC; none while it is open"
    )
    close_cause: ConversationCloseCause | None = Field(
        description=(
            "Why it was closed: `ended` by `end_conversation`, `timeout` by"
            " Pilot once it stood quiet for some time after its last turn,"
            " `finished`, `reopened` or `archived` when its project was;"
            " none while it is open"
        )
    )
    turns: int = Field(description="The count of its turns so far")
    running: bool = Field(
        description=(
            "Whether a turn of it is in flight, a stopped one that has not"
            " ended yet included: `send` is refused while one is"
        )
    )


class Conversations(BaseModel):
    """The conversations with Pilot a caller's environment opened."""

    conversations: list[Conversation] = Field(
        description="A row per conversation, in the order they were opened"
    )


class SentMessage(BaseModel):
    """The turn a message started."""

    turn: int = Field(description="The turn's number in the conversation")


class TurnResponse(BaseModel):
    """Pilot's reply to your latest message in a conversation, as it stands."""

    turn: int | None = Field(
        description=(
            "The number of the turn your message started, as `send` answered"
            " it, 1 for the conversation's first; none while `state` is"
            " `running`"
        )
    )
    state: Literal["running", "done", "error", "interrupted"] = Field(
        description=(
            "`running` while the turn is in flight: the wait ran out first, so"
            " call again. `done` once it has ended, `error` when it failed,"
            " `interrupted` when it was stopped: by `interrupt`, by a person,"
            " or by Pilot while it updated"
        )
    )
    text: str | None = Field(
        description=(
            "Every message Pilot wrote in the turn, in order, separated by"
            " `\\n\\n---\\n\\n`: the ones so far while `running`. A turn that"
            " failed ends it with why, as a section of its own. None when"
            " there is none"
        )
    )


class Clock(Protocol):
    """The time a held call waits by."""

    def now(self) -> float:
        """Seconds on a clock that never runs back."""
        ...

    async def sleep(self, seconds: float) -> None: ...


class _SystemClock:
    def now(self) -> float:
        return time.perf_counter()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


StillRunning = Callable[[float, float], Awaitable[None]]
"""Tells a held call's caller it still waits: the seconds waited so far, and
the seconds of the whole wait."""


ItemKind = Literal[
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
]
"""An item's kinds, as `reference.json` lists them."""

LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 1000
FIND_LIMIT_DEFAULT = 50
FIND_LIMIT_MAX = 200
"""The pages of `list_files` and `list_items`, and of `find_files`: KubeCoder's
fleet adapter's (F150.5, F150.8)."""


_PAGED = ConfigDict(alias_generator=to_camel, populate_by_name=True)
"""A page's and a read's fields in the fleet's file tools' names: `totalCount`,
`limitHit`, `isDirectory`, `lineCut`."""

TotalCount = Annotated[int, Field(description="The count of every entry, on any page")]

LimitHit = Annotated[
    bool,
    Field(description="Whether more remain past this page: page on with `offset`"),
]


class ListedItem(BaseModel):
    """An item of a project; a field with nothing to say is left out."""

    model_config = ConfigDict(populate_by_name=True)

    seq: int = Field(description="Its number among the project's items")
    kind: str = Field(description="Its kind, a code of `reference.json`'s `item_kinds`")
    title: str | None = Field(default=None, description="Its title")
    path: str | None = Field(
        default=None,
        description=(
            "Its file, a path `read_file` takes but for an archived project's,"
            " whose files are not read; left out for an item with no file, a"
            " work item and a wait among them"
        ),
    )
    created_at: str = Field(description="When it was added, in UTC")
    done_cause: str | None = Field(
        default=None,
        description=(
            "How it came to be done: `answered`, `marked`, `settled`,"
            " `turn_ended`, `finished`, `cancelled` or `withdrawn`; left out"
            " while it is open"
        ),
    )
    for_: str | None = Field(
        default=None,
        alias="for",
        description="The handle of the person it is for; left out for one for no one",
    )
    urgent: bool = Field(
        default=False, description="True for an urgent item; left out otherwise"
    )

    @model_serializer(mode="wrap")
    def _said(self, fields: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """The fields that say something: one that is none or false is
        dropped (F150.8)."""
        return {
            name: value
            for name, value in fields(self).items()
            if value is not None and value is not False
        }


class Items(BaseModel):
    """A page of a project's items."""

    model_config = _PAGED

    items: list[ListedItem] = Field(
        description="A row per item, in the order they were added"
    )
    total_count: TotalCount
    limit_hit: LimitHit


class FileEntry(BaseModel):
    """A file or a folder of a folder."""

    model_config = _PAGED

    path: str = Field(
        description=(
            "Its path from the root, which the other file tools take; a"
            " folder's ends with `/`"
        )
    )
    is_directory: bool = Field(description="Whether it is a folder")


class FileListing(BaseModel):
    """A page of what a folder holds."""

    model_config = _PAGED

    files: list[FileEntry] = Field(description="Its folders first, then its files")
    total_count: TotalCount
    limit_hit: LimitHit


class FoundFiles(BaseModel):
    """A page of the files a glob matches."""

    model_config = _PAGED

    pattern: str = Field(description="The glob that was matched")
    files: list[str] = Field(
        description="The matching files' paths from the root, in path order"
    )
    total_count: TotalCount
    limit_hit: LimitHit


class FileText(BaseModel):
    """A text file as it was read."""

    model_config = _PAGED

    content: str = Field(
        description="The lines read, each under its number in the file: `N: line`"
    )
    sha256: str = Field(description="The hash of the whole file's bytes")
    total_count: int = Field(description="The count of the file's lines")
    limit_hit: bool = Field(
        description="Whether a range or a tail was cut at 2,000 lines or 128 KB"
    )
    line_cut: bool = Field(
        description="Whether the content is one line cut short, over 128 KB on its own"
    )


class _Routes:
    """One surface's routes, under `/tools/<surface>/`."""

    def __init__(
        self,
        surface: str,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        self._surface = surface
        self._base_url = base_url
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=_TIMEOUT, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(
        self,
        route: str,
        authorization: str,
        tool_use_id: str | None,
        body: dict[str, Any],
    ) -> Any:
        return await self._send("POST", route, authorization, tool_use_id, body)

    async def _send(
        self,
        method: str,
        route: str,
        authorization: str,
        tool_use_id: str | None,
        body: dict[str, Any],
    ) -> Any:
        headers = {"Authorization": authorization}
        if tool_use_id is not None:
            headers[TOOL_USE_ID_HEADER] = tool_use_id
        try:
            response = await self._http.request(
                method, f"/tools/{self._surface}/{route}", json=body, headers=headers
            )
        except httpx.RequestError as exc:
            raise ToolError(
                f"Cannot call {self._surface} because Pilot's API at"
                f" {self._base_url} did not answer ({type(exc).__name__})"
            ) from exc
        if response.is_error:
            raise ToolError(_refusal(response))
        return response.json()


class PilotWorkApi(_Routes):
    def __init__(
        self, base_url: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        """`transport` answers in place of the network, in the suite."""
        super().__init__("pilot-work", base_url, transport)

    async def register_document(
        self, authorization: str, tool_use_id: str | None, path: str
    ) -> RegisteredDocument:
        answer = await self._post(
            "documents", authorization, tool_use_id, {"path": path}
        )
        return RegisteredDocument.model_validate(answer)

    async def attach_file(
        self,
        authorization: str,
        tool_use_id: str | None,
        path: str,
        to: uuid.UUID | None,
    ) -> AttachedFiles:
        body = {"path": path} if to is None else {"path": path, "to": str(to)}
        answer = await self._post("attachments", authorization, tool_use_id, body)
        return AttachedFiles.model_validate(answer)

    async def set_progress(self, authorization: str, steps: list[Step]) -> Progress:
        """No tool-use id is sent: the call records no effect to name it."""
        body = {"steps": [step.model_dump(exclude_none=True) for step in steps]}
        answer = await self._send("PUT", "progress", authorization, None, body)
        return Progress.model_validate(answer)

    async def set_progress_step(
        self, authorization: str, code: str, state: StepState
    ) -> Progress:
        """No tool-use id is sent: the call records no effect to name it."""
        body = {"code": code, "state": state}
        answer = await self._send("PATCH", "progress", authorization, None, body)
        return Progress.model_validate(answer)

    async def register_debrief(
        self, authorization: str, debrief: str, entries: list[DebriefEntry]
    ) -> RegisteredDebrief:
        """No tool-use id is sent: the call records no effect to name it."""
        body = {
            "debrief": debrief,
            "entries": [entry.model_dump(exclude_none=True) for entry in entries],
        }
        answer = await self._post("debrief", authorization, None, body)
        return RegisteredDebrief.model_validate(answer)


class PilotStoreApi(_Routes):
    def __init__(
        self, base_url: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        """`transport` answers in place of the network, in the suite."""
        super().__init__("pilot-store", base_url, transport)

    async def add_item(
        self, authorization: str, tool_use_id: str | None, item: NewItem
    ) -> Added:
        body = item.model_dump(by_alias=True, exclude_defaults=True, mode="json")
        answer = await self._post("items", authorization, tool_use_id, body)
        return Added.model_validate(answer)

    async def attach_file(
        self,
        authorization: str,
        tool_use_id: str | None,
        *,
        source: str,
        to: uuid.UUID | None,
    ) -> AttachedMaterial:
        body = {"source": source} | _given(to=None if to is None else str(to))
        answer = await self._post("attachments", authorization, tool_use_id, body)
        return AttachedMaterial.model_validate(answer)

    async def answer(
        self,
        authorization: str,
        tool_use_id: str | None,
        *,
        block: str,
        value: str,
        person: str,
        note: str | None,
        to: str | None,
    ) -> Recorded:
        body = {"block": block, "value": value, "for": person}
        body |= _given(note=note, to=to)
        answer = await self._post("answers", authorization, tool_use_id, body)
        return Recorded.model_validate(answer)

    async def mark(
        self,
        authorization: str,
        tool_use_id: str | None,
        *,
        item: uuid.UUID,
        mark: Mark,
        person: str | None,
        note: str | None,
    ) -> Recorded:
        body = {"item": str(item), "mark": mark}
        body |= _given(**{"for": person}, note=note)
        answer = await self._post("marks", authorization, tool_use_id, body)
        return Recorded.model_validate(answer)

    async def cancel_ask(
        self,
        authorization: str,
        tool_use_id: str | None,
        *,
        item: uuid.UUID,
        person: str,
    ) -> Recorded:
        answer = await self._post(
            "cancellations",
            authorization,
            tool_use_id,
            {"item": str(item), "for": person},
        )
        return Recorded.model_validate(answer)

    async def stop_work(
        self,
        authorization: str,
        tool_use_id: str | None,
        *,
        item: uuid.UUID,
        reason: str | None,
    ) -> Recorded:
        body = {"item": str(item)} | _given(reason=reason)
        answer = await self._post("stops", authorization, tool_use_id, body)
        return Recorded.model_validate(answer)

    async def finish(
        self, authorization: str, tool_use_id: str | None, *, archive: bool
    ) -> Recorded:
        answer = await self._post(
            "finish", authorization, tool_use_id, {"archive": archive}
        )
        return Recorded.model_validate(answer)

    async def ask_writer(
        self,
        authorization: str,
        tool_use_id: str | None,
        *,
        block: str,
        question: str,
    ) -> Asked:
        body = {"block": block, "question": question}
        answer = await self._post("writer-questions", authorization, tool_use_id, body)
        return Asked.model_validate(answer)


class PilotProjectsApi:
    def __init__(
        self,
        base_url: str,
        credential: ServiceCredential,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        """`transport` answers in place of the network and `clock` tells the
        time in place of the system's, in the suite."""
        self._base_url = base_url
        self._credential = credential
        self._clock = _SystemClock() if clock is None else clock
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=_TIMEOUT, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._credential.aclose()

    async def list_projects(self, caller: Caller, archived: bool) -> Projects:
        answer = await self._get(
            "/api/projects", caller, {"archived": "true" if archived else "false"}
        )
        return Projects(
            projects=[
                ListedProject(
                    id=row["id"],
                    folder=row["address"],
                    name=row["name"],
                    state=row["state"],
                    status=row["status"],
                )
                for row in answer["projects"]
            ]
        )

    async def get_project(self, caller: Caller, project: str) -> ProjectHead:
        head = await self._get("/api/projects/head", caller, {"address": project})
        return ProjectHead(
            id=head["id"],
            folder=head["address"],
            name=head["name"],
            state=head["state"],
            archived=head["archived"],
            status=head["status"],
            autopilot=head["autopilot"],
            members=[member["handle"] for member in head["members"]],
            progress=PlanProgress.model_validate(head["progress"]),
            running_work=[
                RunningWork(
                    seq=work["seq"],
                    title=work["title"],
                    environment=work["environment"],
                )
                for work in head["running_work"]
            ],
            open_items=head["open_items"],
            url=head["url"],
        )

    async def start_project(
        self, caller: Caller, brief: str, title: str | None, person: str | None
    ) -> StartedProject:
        body = {"words": brief} | _given(title=title, **{"for": person})
        draft = await self._send("POST", "/api/projects", caller, body=body)
        return StartedProject(id=draft["id"], folder=draft["address"], url=draft["url"])

    async def list_items(
        self,
        caller: Caller,
        project: str,
        *,
        open_only: bool,
        kind: ItemKind | None,
        offset: int,
        limit: int,
    ) -> Items:
        query = {"address": project, "open": "true" if open_only else "false"}
        answer = await self._get(
            "/api/projects/items", caller, query | _given(kind=kind)
        )
        page, total, more = _page(answer["items"], offset, limit)
        return Items(
            items=[
                ListedItem.model_validate({**row, "for": row["for_handle"]})
                for row in page
            ],
            total_count=total,
            limit_hit=more,
        )

    async def list_files(
        self, caller: Caller, path: str, offset: int, limit: int
    ) -> FileListing:
        answer = await self._get("/api/tree/entries", caller, {"path": path})
        page, total, more = _page(answer["entries"], offset, limit)
        return FileListing(
            files=[
                FileEntry(path=entry["path"], is_directory=entry["is_directory"])
                for entry in page
            ],
            total_count=total,
            limit_hit=more,
        )

    async def find_files(
        self, caller: Caller, pattern: str, offset: int, limit: int
    ) -> FoundFiles:
        answer = await self._get("/api/tree/matches", caller, {"pattern": pattern})
        page, total, more = _page(answer["paths"], offset, limit)
        return FoundFiles(
            pattern=pattern, files=page, total_count=total, limit_hit=more
        )

    async def read_file(
        self,
        caller: Caller,
        path: str,
        *,
        start_line: int | None,
        end_line: int | None,
        tail_lines: int | None,
    ) -> FileText:
        lines = {
            "start_line": start_line,
            "end_line": end_line,
            "tail_lines": tail_lines,
        }
        query = {"path": path} | {
            name: str(number) for name, number in lines.items() if number is not None
        }
        return FileText.model_validate(await self._get("/api/tree/text", caller, query))

    async def start_conversation(
        self, caller: Caller, project: str, text: str
    ) -> Conversation:
        body = {"address": project, "words": text}
        opened = await self._send("POST", "/api/conversations", caller, body=body)
        return _conversation(opened)

    async def send(
        self, caller: Caller, conversation: uuid.UUID, text: str
    ) -> SentMessage:
        """A message whose send failed is the tool's error, the Turn's own."""
        turn = await self._send(
            "POST",
            f"/api/conversations/{conversation}/messages",
            caller,
            body={"words": text},
        )
        if turn["error"] is not None:
            raise ToolError(turn["error"])
        return SentMessage(turn=turn["seq"])

    async def get_conversation(
        self, caller: Caller, conversation: uuid.UUID
    ) -> Conversation:
        return _conversation(
            await self._get(f"/api/conversations/{conversation}", caller, {})
        )

    async def list_conversations(
        self, caller: Caller, project: str | None
    ) -> Conversations:
        answer = await self._get("/api/conversations", caller, _given(address=project))
        return Conversations(
            conversations=[_conversation(row) for row in answer["conversations"]]
        )

    async def interrupt(self, caller: Caller, conversation: uuid.UUID) -> Conversation:
        return _conversation(
            await self._send(
                "POST", f"/api/conversations/{conversation}/interrupt", caller
            )
        )

    async def end_conversation(
        self, caller: Caller, conversation: uuid.UUID
    ) -> Conversation:
        return _conversation(
            await self._send("POST", f"/api/conversations/{conversation}/end", caller)
        )

    async def get_response(
        self,
        caller: Caller,
        conversation: uuid.UUID,
        wait_seconds: float,
        still_running: StillRunning,
    ) -> TurnResponse:
        """Pilot's reply as it stands once no turn of the conversation is in
        flight, or once `wait_seconds` have passed, whichever comes first:
        the conversation asked every `POLL_SECONDS` where it stands, each ask
        answered at once, and `still_running` told every `PROGRESS_SECONDS`
        meanwhile. A reply read `running` before the wait is over, a turn
        started since the ask, is waited on."""
        path = f"/api/conversations/{conversation}"
        started = self._clock.now()
        reported = started
        while True:
            over = self._clock.now() - started >= wait_seconds
            if over or not await self._in_flight(caller, path):
                reply = TurnResponse.model_validate(
                    await self._get(f"{path}/response", caller, {})
                )
                if over or reply.state != "running":
                    return reply
            now = self._clock.now()
            if now - reported >= PROGRESS_SECONDS:
                await still_running(now - started, wait_seconds)
                reported = now
            left = started + wait_seconds - self._clock.now()
            await self._clock.sleep(max(0.0, min(POLL_SECONDS, left)))

    async def _in_flight(self, caller: Caller, path: str) -> bool:
        """Whether a turn of the conversation at `path` is in flight, asked
        under `_POLL_TIMEOUT`."""
        standing = await self._send("GET", path, caller, timeout=_POLL_TIMEOUT)
        in_flight: bool = standing["in_flight"]
        return in_flight

    async def _get(self, path: str, caller: Caller, query: dict[str, str]) -> Any:
        return await self._send("GET", path, caller, query=query)

    async def _send(
        self,
        method: str,
        path: str,
        caller: Caller,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        timeout: httpx.Timeout = _TIMEOUT,
    ) -> Any:
        headers = {"Authorization": await self._credential.authorization()}
        headers |= caller.headers()
        try:
            response = await self._http.request(
                method,
                path,
                params=query,
                json=body,
                headers=headers,
                timeout=timeout,
            )
        except httpx.RequestError as exc:
            raise ToolError(
                "Cannot call pilot-projects because Pilot's API at"
                f" {self._base_url} did not answer ({type(exc).__name__})"
            ) from exc
        if response.is_error:
            raise ToolError(_refusal(response))
        return response.json()


def _conversation(row: dict[str, Any]) -> Conversation:
    """A conversation as the API answers it, in the surface's words."""
    return Conversation(
        id=row["id"],
        project=row["project_id"],
        environment=row["environment"],
        session=row["session"],
        opened_at=row["opened_at"],
        closed_at=row["closed_at"],
        close_cause=row["close_cause"],
        turns=row["turns"],
        running=row["in_flight"],
    )


def _page[T](rows: list[T], offset: int, limit: int) -> tuple[list[T], int, bool]:
    """The `limit` rows from `offset`, the count of them all, and whether
    more remain past the page."""
    return rows[offset : offset + limit], len(rows), offset + limit < len(rows)


def _given(**values: str | None) -> dict[str, str]:
    """The optional values a call was given; one it was not given is not sent."""
    return {name: value for name, value in values.items() if value is not None}


def _refusal(response: httpx.Response) -> str:
    """The reason of an answer outside 2xx: the `error` of the API's envelope
    (`ApiErrorResponseSchema`), which every error its handlers build carries;
    else its status, for an answer that is not that envelope — spectree's own
    validation answer, or something other than the API at the URL."""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        error = None
    if isinstance(error, str):
        return error
    return (
        f"Pilot's API answered {response.status_code} {response.reason_phrase},"
        " not its error envelope"
    )
