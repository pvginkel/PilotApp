"""The MCP process's clients of the tools' routes, `pilot-work`'s
(`app/api/pilot_work.py`) and `pilot-store`'s (`app/api/pilot_store.py`): one
call per tool, under the bearer the tool's caller presented, which the API
resolves to its Session, with the call's tool-use id where it has one.

An answer outside 2xx is a `ToolError` carrying the API's `error`, its reason
whole, or the answer's status where it is not the API's envelope; an API that
does not answer is one naming that.
"""

import uuid
from typing import Annotated, Any, Literal

import httpx
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

TOOL_USE_ID_HEADER = "Tool-Use-Id"
"""The header the routes read a call's tool-use id from
(`app/services/effect_service.py`)."""

_TIMEOUT = httpx.Timeout(300.0, connect=5.0)

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
MAX_STEPS = 100
"""The limits of a work item's list of steps, as its route takes them
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
            "The actions of workers' documents a work item does that you"
            " claimed, by their blocks' ids, `<item id>/<local id>`: each"
            " block's line names this work item, and the job after its turn"
            " names them for their `done`"
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


class PublishedStep(BaseModel):
    """A step of your work item's list as it stands."""

    code: str = Field(description="Your name for the step")
    label: str = Field(description="Its words on the tile")
    state: StepState = Field(description="`pending`, `active` or `done`")


class Progress(BaseModel):
    """Your work item's list of steps as it stands."""

    steps: list[PublishedStep] = Field(description="Its steps, in order")


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

    async def stop_work(
        self, authorization: str, tool_use_id: str | None, *, item: uuid.UUID
    ) -> Recorded:
        answer = await self._post(
            "stops", authorization, tool_use_id, {"item": str(item)}
        )
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
