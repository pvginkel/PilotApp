"""The MCP process's client of `pilot-work`'s routes (`app/api/pilot_work.py`):
one call per tool, under the bearer the tool's caller presented, which the API
resolves to its Session.

An answer outside 2xx is a `ToolError` carrying the API's `error`, its reason
whole, or the answer's status where it is not the API's envelope; an API that
does not answer is one naming that.
"""

import uuid
from typing import Any

import httpx
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

ROUTES = "/tools/pilot-work"

_TIMEOUT = httpx.Timeout(300.0, connect=5.0)


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


class PilotWorkApi:
    def __init__(
        self, base_url: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        """`transport` answers in place of the network, in the suite."""
        self._base_url = base_url
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=_TIMEOUT, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def register_document(
        self, authorization: str, path: str
    ) -> RegisteredDocument:
        answer = await self._post("documents", authorization, {"path": path})
        return RegisteredDocument.model_validate(answer)

    async def attach_file(
        self, authorization: str, path: str, to: uuid.UUID | None
    ) -> AttachedFiles:
        body = {"path": path} if to is None else {"path": path, "to": str(to)}
        answer = await self._post("attachments", authorization, body)
        return AttachedFiles.model_validate(answer)

    async def _post(self, route: str, authorization: str, body: dict[str, str]) -> Any:
        try:
            response = await self._http.post(
                f"{ROUTES}/{route}",
                json=body,
                headers={"Authorization": authorization},
            )
        except httpx.RequestError as exc:
            raise ToolError(
                f"Cannot call pilot-work because Pilot's API at {self._base_url}"
                f" did not answer ({type(exc).__name__})"
            ) from exc
        if response.is_error:
            raise ToolError(_refusal(response))
        return response.json()


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
