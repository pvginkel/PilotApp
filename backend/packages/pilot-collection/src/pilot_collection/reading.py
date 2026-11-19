"""A conversation's reading (F152.13): one transcript as a collector serves
it to Pilot's backend, never as its file.

A reading is one Transcript, a main thread's or one sub-agent's, whole: every
Call the file holds, by the `message_id` its publication names it by and in
the file's order, each with what came in before it, since the Call before,
and what it put out; then what follows the last Call. Each of those is a
block, with its kind, the time of the line it stood in and its full text.

It carries no image's bytes: a block, or a result, says that an image stood
there and how large it was. `file_size` and `file_modified_at` are the file's
as the reading was read, its validator.
"""

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from pilot_collection.publication import Name, Size

Writer = Literal["person", "brief", "parent", "notice"]
"""Who wrote a line that arrives as the person's: a person; a caller of
Claude Code's SDK, as Pilot is with its brief; the agent that started or
steers a sub-agent; or Claude Code itself, a notice."""


class ReadingVersionRangeSchema(BaseModel):
    """The versions of the reading a collector serves, both ends included:
    a 426's body."""

    min: int = Field(description="The oldest version of the reading served")
    max: int = Field(description="The newest version of the reading served")


class _Read(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadImageSchema(_Read):
    """An image that stood in a result: what it was, never its bytes."""

    media_type: str = Field(description="Its media type", examples=["image/png"])
    size: Size = Field(description="Its size in bytes")


class ReadResultSchema(_Read):
    """A tool's result."""

    at: AwareDatetime = Field(description="When it returned")
    error: bool = Field(description="Whether the tool said it failed")
    text: str = Field(description="Its text, whole")
    images: list[ReadImageSchema] = Field(
        description="The images it held, in its order"
    )


class _Block(_Read):
    at: AwareDatetime = Field(description="The time of the line it stood in")


class UserBlockSchema(_Block):
    """A line that arrived as the person's and is no tool's result."""

    kind: Literal["user"]
    writer: Writer | None = Field(
        description=(
            "Who wrote it; none where the file does not say, as a main"
            " thread's of a Claude Code that named no source"
        )
    )
    text: str = Field(description="Its text, whole")


class ImageBlockSchema(_Block, ReadImageSchema):
    """An image that stood in the line of the `user` block before it."""

    kind: Literal["image"]


class SyntheticBlockSchema(_Block):
    """Words Claude Code wrote itself where a response would stand: no
    Call."""

    kind: Literal["synthetic"]
    text: str = Field(description="Its text, whole")


class AttachmentBlockSchema(_Block):
    """What Claude Code added to the request beside the conversation's own
    lines: a reminder, the instruction files it loaded, a listing."""

    kind: Literal["attachment"]
    type: Name = Field(
        description="Claude Code's word for what it is",
        examples=["instructions", "total_tokens_reminder"],
    )
    text: str = Field(
        description="Its words where it is words, else what it holds, as JSON"
    )


class SystemBlockSchema(_Block):
    """A line Claude Code wrote into the conversation as itself: a local
    command's output, a compaction's boundary, a turn's end."""

    kind: Literal["system"]
    subtype: str | None = Field(
        description="Claude Code's word for what it is, none where it names none",
        examples=["local_command", "turn_duration"],
    )
    text: str | None = Field(description="Its words, none where it has none")


class ToolResultBlockSchema(_Block, ReadResultSchema):
    """A tool's result that sits on no tool call: the file holds no request
    of its id, or an earlier result answered it."""

    kind: Literal["tool_result"]
    tool_use_id: Name = Field(description="Claude's id of the request it names")


class TextBlockSchema(_Block):
    """Words the model put out."""

    kind: Literal["text"]
    text: str = Field(description="Its text, whole")


class ThinkingBlockSchema(_Block):
    """The model's thinking."""

    kind: Literal["thinking"]
    text: str = Field(description="Its text where the file has it, else empty")


class ToolCallBlockSchema(_Block):
    """A tool the Call requested, with the result that answered it."""

    kind: Literal["tool_call"]
    tool_use_id: Name = Field(
        description="Claude's id of the request, which its Tool Call's fact carries"
    )
    tool: Name = Field(description="The tool's name")
    input: dict[str, Any] = Field(description="What the tool was given, whole")
    started: Name | None = Field(
        description=(
            "The `agent_id` of the sub-agent's Transcript the call started, in"
            " this conversation; none where it started none"
        )
    )
    result: ReadResultSchema | None = Field(
        description="Its result; none where the file holds none"
    )


Received = Annotated[
    UserBlockSchema
    | ImageBlockSchema
    | SyntheticBlockSchema
    | AttachmentBlockSchema
    | SystemBlockSchema
    | ToolResultBlockSchema,
    Field(discriminator="kind"),
]
"""A block of what came in."""

Sent = Annotated[
    TextBlockSchema | ThinkingBlockSchema | ToolCallBlockSchema,
    Field(discriminator="kind"),
]
"""A block of what a Call put out."""


class ReadCallSchema(_Read):
    """One Call of the conversation."""

    message_id: Name = Field(
        description="Claude's id of the response, which the Call's fact carries"
    )
    received: list[Received] = Field(
        description="What came in before it, since the Call before, in order"
    )
    sent: list[Sent] = Field(description="What it put out, in order")


class ReadingSchema(_Read):
    """One conversation's reading."""

    session_id: Name = Field(description="Claude Code's id of the main thread")
    agent_id: Name | None = Field(
        description="Claude Code's id of the sub-agent, none on a main thread"
    )
    file_size: Size = Field(description="The file's size in bytes as it was read")
    file_modified_at: AwareDatetime = Field(
        description="The file's time as it was read, to the microsecond"
    )
    calls: list[ReadCallSchema] = Field(
        description="Every Call the file holds, in its order"
    )
    after: list[Received] = Field(description="What follows the last Call, in order")
