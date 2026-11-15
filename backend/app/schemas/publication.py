"""A collector's publication of one transcript: the call's shape (DB decisions
79 and 81; F152.3).

One call is one Transcript, a main thread's or one sub-agent's, with every
fact of DB §2.6 and §2.7 the collector read off its file. A reference value is
named by its code, a row Pilot holds by what the file names it by: a Call by
its `message_id`, a Prompt and a Compaction by their place in the file. It
carries nothing of the transcript's text (DB decision 79.41).
"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(min_length=1)]
"""What the file names something by: an id of Claude Code's, a reference
value's code, a version."""

Count = Annotated[int, Field(ge=0, le=2_147_483_647)]
"""A number of tokens, characters or milliseconds, which an `integer` column
holds."""

Place = Annotated[int, Field(ge=1, le=2_147_483_647)]
"""A row's place among its Transcript's rows of its entity, in the file's
order, from 1."""

CallTokenKind = Literal[
    "input", "cache_write_5m", "cache_write_1h", "cache_read", "output"
]
"""A Token Kind a Call's tokens are counted by: one nothing is within (DB
547)."""


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
        description="The Prompt Source's code", examples=["person", "hook"]
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
        description="The time of its last line that carries one, none while it runs",
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


class PublicationSchema(_Published):
    """One Transcript as its file stands, read whole."""

    session_id: Name = Field(description="Claude Code's id of the main thread")
    agent_id: Name | None = Field(
        default=None,
        description="Claude Code's id of the sub-agent, none on a main thread",
    )
    file_size: int = Field(
        ge=0, le=9_223_372_036_854_775_807, description="The file's size in bytes"
    )
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
    launches: list[PublishedLaunchSchema] = Field(
        default_factory=list,
        description="A main thread's Launches, in the file's order",
    )
    compactions: list[PublishedCompactionSchema] = Field(
        default_factory=list, description="Its Compactions, in the file's order"
    )
    calls: list[PublishedCallSchema] = Field(
        default_factory=list,
        description="Its Calls, in the file's order: the first has position 1",
    )
