"""A Session's records on the wire, and the view a browser subscribes (design 2
§11.1, §11.2).

A record has one shape on the records route's pages and in the stream's live
`record` frames.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _RecordBase(BaseModel):
    seq: int = Field(..., description="The record's number in its Session, from 1")
    at: datetime = Field(..., description="When the record was written")
    turn: int | None = Field(
        ..., description="The number of the record's Turn; null outside any Turn"
    )


class ClaudeRecordSchema(_RecordBase):
    """A line of the controller session's raw response stream, as `claude`
    printed it."""

    kind: Literal["claude"]
    payload: Any = Field(
        ..., description="The line: its JSON, or a string for a line that is not"
    )
    raw_offset: int = Field(
        ..., description="The byte offset after the line in its raw stream"
    )


class ResultRecordSchema(_RecordBase):
    """The worker's `result` frame, which ended the Turn."""

    kind: Literal["result"]
    payload: Any = Field(
        ..., description="The frame: turn, result, isError, interrupted"
    )


class ServerRecordSchema(_RecordBase):
    """The server's own line."""

    kind: Literal["server"]
    payload: Any


class SendRecordSchema(_RecordBase):
    """A person's message, in its place among the lines."""

    kind: Literal["send"]
    author: str | None = Field(..., description="The handle of the Turn's author")
    message: str = Field(..., description="The Turn's words")


SessionRecordSchema = Annotated[
    ClaudeRecordSchema | ResultRecordSchema | ServerRecordSchema | SendRecordSchema,
    Field(discriminator="kind"),
]


class SessionRecordsQuerySchema(BaseModel):
    """Which records a page holds: those after `after`, at most `limit`."""

    model_config = ConfigDict(extra="forbid")

    after: int = Field(0, ge=0, description="The page starts after this record number")
    limit: int = Field(
        200, ge=1, le=1000, description="The most records the page holds"
    )


class SessionRecordPageSchema(BaseModel):
    """A page of a Session's records, in order."""

    records: list[SessionRecordSchema]
    ended: bool = Field(
        ...,
        description="The page holds the Session's last record, and its stream has ended",
    )


class SessionStreamViewSchema(BaseModel):
    """A view of a Session's stream on the browser's SSE connection."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(
        ..., min_length=1, max_length=255, description="The SSE connection's request id"
    )
    view: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="The view's key, unique within its connection",
    )
