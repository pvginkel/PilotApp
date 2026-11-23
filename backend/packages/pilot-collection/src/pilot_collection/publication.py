"""A collector's publication of one transcript: the call's shape (DB decisions
79 and 81; F152.3).

One call is one Transcript, a main thread's or one sub-agent's, with every
fact of DB §2.6 and §2.7 the collector read off its file. A reference value is
named by its code, a row Pilot holds by what the file names it by: a Call by
its `message_id`, a Tool Call by its `tool_use_id`, a Prompt and a Compaction
by their place in the file. It carries nothing of the transcript's text (DB
decision 79.41).

A call is whole, the file as it stands, or appended, for a file that grew
(F152.15): one with `appended`, which names what the call builds on and the
boundary its Launches, Compactions and Calls start at. A place and a
`position` count through the file in both, from 1.

Of the workflow's labels a call carries one, a main thread's `group` (F152.8).
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(min_length=1)]
"""What the file names something by: an id of Claude Code's, a reference
value's code, a version."""

Count = Annotated[int, Field(ge=0, le=2_147_483_647)]
"""A number of tokens, characters or milliseconds, which an `integer` column
holds."""

Size = Annotated[int, Field(ge=0, le=9_007_199_254_740_991)]
"""A file's size in bytes, up to the largest integer every JSON reader takes
exactly, 2^53 - 1: a bound past it reaches the frontend's OpenAPI cache
rounded, through the JavaScript that writes it."""

Place = Annotated[int, Field(ge=1, le=2_147_483_647)]
"""A row's place among its Transcript's rows of its entity, in the file's
order, from 1."""

CallTokenKind = Literal[
    "input", "cache_write_5m", "cache_write_1h", "cache_read", "output"
]
"""A Token Kind a Call's tokens are counted by: one nothing is within (DB
547)."""


class CollectorProtocolRangeSchema(BaseModel):
    """The protocol versions the server accepts of a collector, both ends
    included: a 426's body."""

    min: int = Field(description="The oldest protocol version accepted")
    max: int = Field(description="The newest protocol version accepted")


class _Published(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublishedVersionSchema(_Published):
    """The collector's version that read the file."""

    version: Name = Field(description="The version, as the collector names it")
    released_at: AwareDatetime | None = Field(
        default=None, description="When it was released, where the collector can tell"
    )


class PublishedComponentSchema(PublishedVersionSchema):
    """A version of one piece of software a Launch ran with."""

    component: Name = Field(
        description="The Component's code", examples=["claude-code", "plugin:dev"]
    )


class PublishedHookRunSchema(_Published):
    """A run of one hook command at the end of a Prompt's run."""

    command: str = Field(description="The command it ran")
    duration_ms: Count = Field(description="How long it ran")
    failed: bool = Field(description="Whether it reported an error")
    prevented_end: bool = Field(description="Whether it kept the run from ending")


class PublishedPromptSchema(_Published):
    """An input a Launch received."""

    received_at: AwareDatetime = Field(description="When it was queued")
    source: Name = Field(
        description="The Prompt Source's code", examples=["typed", "sdk"]
    )
    characters: Count = Field(description="Its length")
    hook_runs: list[PublishedHookRunSchema] = Field(
        default_factory=list, description="The hook runs at its run's end, in order"
    )


class PublishedLaunchSchema(_Published):
    """A start of a Claude Code process on the main thread."""

    started_at: AwareDatetime = Field(
        description="The time of the first line the Launch wrote"
    )
    ended_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "The time of its last line that carries one, the open one's the last so far"
        ),
    )
    components: list[PublishedComponentSchema] = Field(
        min_length=1, description="The versions it ran with, one of each Component"
    )
    prompts: list[PublishedPromptSchema] = Field(
        default_factory=list, description="The inputs it received, in the file's order"
    )


class PublishedCompactionSchema(_Published):
    """A compaction of the Transcript's context."""

    at: AwareDatetime = Field(description="When its boundary was written")
    trigger: Name = Field(
        description="The Compaction Trigger's code", examples=["auto", "manual"]
    )
    tokens_before: Count = Field(description="The context it compacted")
    tokens_after: Count | None = Field(
        default=None, description="The context it left, where the version records it"
    )
    duration_ms: Count | None = Field(
        default=None, description="How long it took, where the version records it"
    )


class PublishedToolCallSchema(_Published):
    """A call of one tool a Call requested, with its result."""

    tool_use_id: Name = Field(description="Claude's id of the request")
    tool: Name = Field(
        description="The Tool's code, Claude Code's name of it",
        examples=["Bash", "mcp__youtrack__get_issues"],
    )
    mcp_server: Name | None = Field(
        default=None, description="The MCP server the Tool is of, none for another"
    )
    first_argument: str | None = Field(
        default=None,
        description="The command, path or query it was given, cut to a line",
    )
    requested_at: AwareDatetime = Field(description="When it was requested")
    returned_at: AwareDatetime | None = Field(
        default=None, description="When its result arrived, none where none did"
    )
    failed: bool = Field(description="Whether the result was an error")
    exit_code: int | None = Field(
        default=None,
        ge=-2_147_483_648,
        le=2_147_483_647,
        description="A command's exit code, where it was not zero",
    )
    interrupted: bool = Field(description="Whether the person interrupted it")
    denial_kind: Name | None = Field(
        default=None,
        description="The Denial Kind's code, where the call was denied",
        examples=["rule", "person", "hook"],
    )
    result_characters: Count | None = Field(
        default=None, description="The size of the result the model was given"
    )
    saved_characters: Count | None = Field(
        default=None,
        description="The output's full size, where it was saved to disk",
    )


class PublishedEventSchema(_Published):
    """An occurrence at one moment that no other part of the call records."""

    kind: Name = Field(
        description="The Event Kind's code", examples=["api_error", "interrupt"]
    )
    is_error: bool = Field(
        description="Whether an Event of its kind counts as an error"
    )
    at: AwareDatetime = Field(description="When it occurred")
    detail: str | None = Field(
        default=None,
        description="Its one qualifier as its source gives it: an API error's status",
    )


class PublishedContextPartSchema(_Published):
    """A component of what a Call carried that no earlier Call of its Launch
    did."""

    kind: Name = Field(
        description="The Context Part Kind's code",
        examples=["system_prompt", "skill_body"],
    )
    name: str | None = Field(
        default=None, description="Which one of its kind: the skill, the file"
    )
    characters: Count = Field(description="Its length")


class PublishedCallSchema(_Published):
    """A request the Transcript made to the model, with its response."""

    message_id: Name = Field(description="Claude's id of the response")
    prompt: Place | None = Field(
        default=None,
        description=(
            "The Prompt it follows, by its place among the Transcript's Prompts:"
            " its Launches' in order, each one's in order"
        ),
    )
    predecessor: Name | None = Field(
        default=None,
        description="The `message_id` of the nearest earlier Call on its chain",
    )
    compaction: Place | None = Field(
        default=None,
        description=(
            "The Compaction its chain crossed on the way to its predecessor, by"
            " its place among the Transcript's Compactions"
        ),
    )
    sent_at: AwareDatetime | None = Field(
        default=None,
        description="When the request was sent, where the version records it",
    )
    completed_at: AwareDatetime = Field(
        description="When the response's last line was written"
    )
    model: Name = Field(
        description="The code of the Model that answered", examples=["claude-opus-4-5"]
    )
    requested_model: Name | None = Field(
        default=None, description="The code of the Model asked for, where it differs"
    )
    effort: str | None = Field(
        default=None,
        description="The request's reasoning effort, in Claude Code's word",
    )
    stop_reason: Name | None = Field(
        default=None,
        description="The Stop Reason's code, where the end was not the ordinary one",
    )
    thinking_tokens: Count | None = Field(
        default=None, description="The output tokens spent on thinking"
    )
    attributed_skill: str | None = Field(
        default=None, description="The skill Claude Code says the Call acted under"
    )
    attributed_plugin: str | None = Field(
        default=None, description="The plugin Claude Code says the Call acted under"
    )
    miss_cause: Name | None = Field(
        default=None, description="The Miss Cause's code, on a cache miss"
    )
    tokens: dict[CallTokenKind, Count] = Field(
        default_factory=dict,
        description="The tokens billed, by Token Kind; a kind left out counts none",
    )
    tool_calls: list[PublishedToolCallSchema] = Field(
        default_factory=list,
        description="The calls of a tool it requested, in the file's order",
    )
    events: list[PublishedEventSchema] = Field(
        default_factory=list,
        description=(
            "The Events it marks, in the file's order: each on the last Call"
            " before it, else the first"
        ),
    )
    context_parts: list[PublishedContextPartSchema] = Field(
        default_factory=list,
        description="What it carried that no earlier Call of its Launch did",
    )


class PublishedBaseSchema(_Published):
    """What an appended publication builds on: the Transcript's file as the
    publication before it read it."""

    file_size: Size = Field(description="The file's size in bytes then")
    file_modified_at: AwareDatetime = Field(description="The file's time then")
    collector: Name = Field(description="The collector's version that read it then")


class PublishedBoundarySchema(_Published):
    """Where what an appended publication carries starts in the file. Each is
    the place of the first one the call carries or, where it carries none,
    the place the file's next would take."""

    call: Place = Field(description="The `position` of the first Call it carries")
    launch: Place = Field(
        description="The place of its first Launch among the Transcript's Launches"
    )
    prompt: Place = Field(
        description=(
            "The place of its first Launch's first Prompt among the Transcript's"
            " Prompts"
        )
    )
    compaction: Place = Field(
        description=(
            "The place of its first Compaction among the Transcript's Compactions"
        )
    )


class PublishedAppendedSchema(_Published):
    """What makes a publication an appended one (DB decision 81 point 1)."""

    builds_on: PublishedBaseSchema = Field(
        description=(
            "What Pilot must hold of the Transcript, or the call is refused and"
            " the transcript published whole"
        )
    )
    boundary: PublishedBoundarySchema = Field(
        description=(
            "Where the call's `launches`, `compactions` and `calls` start: from"
            " there on the call carries all the file holds"
        )
    )


class PublishedGroupSchema(_Published):
    """The group of slices run before Pilot that a main thread's labels name
    (F152.8): what Pilot makes the group's adopted project from, and finds it
    again by."""

    key: Name = Field(
        description="The labeller's key of the group, which never changes",
        examples=["recipe-box-first-menus"],
    )
    name: Name = Field(
        description="The group's name as it now stands, one line: its project's name"
    )
    summary: str = Field(
        description=(
            "The group's summary as it now stands, prose with no ask: with the"
            " name, all its project's `project.md` holds"
        )
    )


class PublicationSchema(_Published):
    """One Transcript as its file stands: read whole or, with `appended`,
    from a boundary on."""

    session_id: Name = Field(description="Claude Code's id of the main thread")
    agent_id: Name | None = Field(
        default=None,
        description="Claude Code's id of the sub-agent, none on a main thread",
    )
    file_size: Size = Field(description="The file's size in bytes")
    file_modified_at: AwareDatetime = Field(description="The file's time")
    collector: PublishedVersionSchema = Field(
        description="The collector's version that read the file"
    )
    working_directory: str = Field(
        description="The directory it was first launched in, as its first line has it"
    )
    repository: Name | None = Field(
        default=None,
        description=(
            "The name of the checkout that holds the working directory, none for"
            " a directory under no checkout"
        ),
    )
    environment: Name | None = Field(
        default=None,
        description=(
            "The id of the environment a main thread ran in, none where its"
            " lines name none"
        ),
    )
    agent_type: str | None = Field(
        default=None, description="A sub-agent's type, as its record names it"
    )
    description: str | None = Field(
        default=None, description="The task a sub-agent's spawning call gave it"
    )
    spawned_by: Name | None = Field(
        default=None,
        description=(
            "The `tool_use_id` of the call that started a sub-agent, where its"
            " record names it"
        ),
    )
    group: PublishedGroupSchema | None = Field(
        default=None,
        description=(
            "A main thread's label: the group it belongs to, whose adopted"
            " project then adopts it; none where its labels name none, and the"
            " transcript is then adopted by no project"
        ),
    )
    appended: PublishedAppendedSchema | None = Field(
        default=None,
        description=(
            "On a publication of a file that grew and nothing else: what it"
            " builds on, and its boundary. None on a whole one"
        ),
    )
    launches: list[PublishedLaunchSchema] = Field(
        default_factory=list,
        description=(
            "A main thread's Launches, in the file's order; on an appended call"
            " those that wrote a line of what it carries, the first with its"
            " Prompts from the boundary's on"
        ),
    )
    compactions: list[PublishedCompactionSchema] = Field(
        default_factory=list,
        description="Its Compactions, in the file's order, from the boundary's on",
    )
    calls: list[PublishedCallSchema] = Field(
        default_factory=list,
        description=(
            "Its Calls, in the file's order: the first has position 1, and on an"
            " appended call the boundary's"
        ),
    )
