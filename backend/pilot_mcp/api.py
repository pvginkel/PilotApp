"""The MCP process's clients of the tools' routes, `pilot-work`'s
(`app/api/pilot_work.py`) and `pilot-store`'s (`app/api/pilot_store.py`): one
call per tool, under the bearer the tool's caller presented, which the API
resolves to its Session, with the call's tool-use id where it has one.

An answer outside 2xx is a `ToolError` carrying the API's `error`, its reason
whole, or the answer's status where it is not the API's envelope; an API that
does not answer is one naming that.
"""

import uuid
from typing import Any, Literal

import httpx
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

TOOL_USE_ID_HEADER = "Tool-Use-Id"
"""The header the routes read a call's tool-use id from
(`app/services/effect_service.py`)."""

_TIMEOUT = httpx.Timeout(300.0, connect=5.0)

Mark = Literal["done", "read", "reviewed"]


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


class Asked(BaseModel):
    """The document's blocks its writer is asked about."""

    blocks: list[str] = Field(
        description=(
            "Their local ids, the block this call asked about among them, in"
            " their order in the document"
        )
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
        body: dict[str, str],
    ) -> Any:
        headers = {"Authorization": authorization}
        if tool_use_id is not None:
            headers[TOOL_USE_ID_HEADER] = tool_use_id
        try:
            response = await self._http.post(
                f"/tools/{self._surface}/{route}", json=body, headers=headers
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


class PilotStoreApi(_Routes):
    def __init__(
        self, base_url: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        """`transport` answers in place of the network, in the suite."""
        super().__init__("pilot-store", base_url, transport)

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
    ) -> Recorded:
        body = {"item": str(item), "mark": mark} | _given(**{"for": person})
        answer = await self._post("marks", authorization, tool_use_id, body)
        return Recorded.model_validate(answer)

    async def stop_work(
        self, authorization: str, tool_use_id: str | None, *, item: uuid.UUID
    ) -> Recorded:
        answer = await self._post(
            "stops", authorization, tool_use_id, {"item": str(item)}
        )
        return Recorded.model_validate(answer)

    async def finish(self, authorization: str, tool_use_id: str | None) -> Recorded:
        answer = await self._post("finish", authorization, tool_use_id, {})
        return Recorded.model_validate(answer)

    async def ask_writer(
        self,
        authorization: str,
        tool_use_id: str | None,
        *,
        document: uuid.UUID,
        block: str,
        question: str,
    ) -> Asked:
        body = {"document": str(document), "block": block, "question": question}
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
