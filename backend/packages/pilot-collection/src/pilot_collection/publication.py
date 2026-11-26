"""A collector's publication of one transcript: the call's shape (DB decisions
79 and 81; F152.3).

One call is one Transcript, a main thread's or one sub-agent's, with every
fact of DB §2.6 and §2.7 the collector read off its file, and under each Tool
Call the commits it made and the file it edited (§2.9). A reference value is
named by its code, a row Pilot holds by what the file names it by: a Call by
its `message_id`, a Tool Call by its `tool_use_id`, a Prompt and a Compaction
by their place in the file. It carries nothing of the transcript's text (DB
decision 79.41).

A call is whole, the file as it stands, or appended, for a file that grew
(F152.15): one with `appended`, which names what the call builds on and the
boundary its Launches, Compactions and Calls start at. A place and a
`position` count through the file in both, from 1.

The workflow's labels ride in a call's `labelling`, the labeller's answer for
the Transcript, each row named as both sides compute it (F152.6, F152.7), with
a main thread's `group` (F152.8); an appended call's labelling is its answer
from the call's boundary on. A call with no labelling is one no labeller
answered for: it carries the file's facts alone, and no `group`.
"""

import uuid
from decimal import Decimal
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

Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{4,64}$")]
"""A commit's hash as git prints it, whole or abbreviated."""

FilePath = Annotated[str, StringConstraints(pattern=r"^[^/]")]
"""A file's path within the checkout that holds it."""

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


class PublishedCommitSchema(_Published):
    """A commit a Tool Call made, as its command and its output show it,
    held with no lines until its Repository gives them."""

    repository: Name = Field(
        description="The name of the checkout the commit was made in"
    )
    subject: Name = Field(description="Its message's first line")
    sha: Sha | None = Field(
        default=None,
        description=(
            "Its hash as the call showed it, abbreviated or whole; none where"
            " none showed"
        ),
    )


class PublishedFileEditSchema(_Published):
    """An edit of one file a Repository keeps by a successful Edit or Write,
    with its lines."""

    repository: Name = Field(description="The name of the checkout that holds it")
    path: FilePath = Field(description="The file's path within that checkout")
    lines_added: Count = Field(description="The lines it added")
    lines_removed: Count = Field(description="The lines it removed")


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
    commits: list[PublishedCommitSchema] = Field(
        default_factory=list,
        description="The commits it made, in the order its output shows them",
    )
    file_edits: list[PublishedFileEditSchema] = Field(
        default_factory=list,
        description=(
            "What a successful Edit or Write changed of each file a Repository"
            " keeps; none for another call"
        ),
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


class LabelledLaunchSchema(_Published):
    """A Launch's label."""

    n: Place = Field(description="The Launch's place among the Transcript's Launches")
    work_unit: Name | None = Field(
        default=None, description="The key of the lowest Work Unit it carried out"
    )


class LabelledCallSchema(_Published):
    """A Call's labels."""

    id: Name = Field(description="The Call's `message_id`")
    segment: Place | None = Field(
        default=None, description="The `position` of the Segment it falls in"
    )
    call_class: Name | None = Field(
        default=None, description="The Call Class's code: what the Call was doing"
    )
    avoidable_kind: Name | None = Field(
        default=None, description="The Avoidable Kind's code, where it was avoidable"
    )
    wait_cause: Name | None = Field(
        default=None,
        description="The Wait Cause's code: what woke the Transcript before it",
    )


class LabelledSegmentSchema(_Published):
    """A stretch of the Transcript's Calls by what it was doing."""

    position: Place = Field(description="Its place among the Transcript's Segments")
    kind: Name = Field(description="The Segment Kind's code")


class LabelledToolCallSchema(_Published):
    """A Tool Call's labels."""

    tool_use_id: Name = Field(description="The Tool Call's `tool_use_id`")
    command_class: Name | None = Field(
        default=None, description="The Command Class's code of what it ran"
    )
    effect_kind: Name | None = Field(
        default=None, description="The Tool Effect Kind's code of the change it made"
    )
    effect_subject: Name | None = Field(
        default=None, description="The id of what that change touched"
    )
    rules: list[Name] = Field(
        default_factory=list, description="The codes of the Rules it breached"
    )


class LabelledEventSchema(_Published):
    """An occurrence the labeller marks on a Call."""

    call: Name = Field(description="The `message_id` of the Call it is held on")
    kind: Name = Field(description="The labeller's Event Kind's code")
    at: AwareDatetime = Field(description="When it occurred")
    detail: str | None = Field(default=None, description="Its one qualifier")


class LabelledContextPartSchema(_Published):
    """A component of a Call's opening prompt the labeller recognised, which
    Pilot carves out of the collector's part for that prompt."""

    call: Name = Field(description="The `message_id` of the Call that carried it")
    kind: Name = Field(description="The labeller's Context Part Kind's code")
    name: str | None = Field(default=None, description="Which one of its kind")
    characters: Count = Field(description="Its length")


class LabelledTestFailureSchema(_Published):
    """A test that failed at least one attempt in a Test Run."""

    test: Name = Field(description="The test's name, as its suite names it")
    attempts: Place = Field(description="How often it was tried in the run")
    flaky: bool = Field(description="Whether a later attempt passed")


class LabelledTestRunSchema(_Published):
    """A run of one Test Suite, by a Tool Call or by a Work Unit."""

    tool_use_id: Name | None = Field(
        default=None, description="The Tool Call that ran it, none for a unit's"
    )
    work_unit: Name | None = Field(
        default=None, description="The key of the Work Unit that ran it"
    )
    suite: Name = Field(description="The Test Suite's code")
    passed: bool = Field(description="Whether the run had no failure")
    tests: Count = Field(description="The tests it ran")
    retries_allowed: Count | None = Field(
        default=None, description="How often a failing test was tried again"
    )
    started_at: AwareDatetime | None = Field(default=None, description="Its start")
    ended_at: AwareDatetime | None = Field(default=None, description="Its end")
    failures: list[LabelledTestFailureSchema] = Field(
        default_factory=list, description="The tests that failed an attempt"
    )


class LabelledCIWaitSchema(_Published):
    """A wait of a Tool Call on one CI Build."""

    tool_use_id: Name = Field(description="The Tool Call that waited")
    job: Name = Field(description="The CI Build's job")
    number: Place = Field(description="The CI Build's number")


class LabelledDocumentSchema(_Published):
    """A Document's label, on a main thread's labelling."""

    id: uuid.UUID = Field(description="Pilot's id of the Document, as handed")
    ask_category: Name | None = Field(
        default=None, description="The Ask Category's code of the asks it puts"
    )


class PublishedLabelsSchema(_Published):
    """The labels of the Transcript's own rows, each list in the labeller's
    order; a row the labels do not name takes none. On an appended call, the
    labels of its rows from its boundary on, of the Work Units' Test Runs and
    of the Documents."""

    launches: list[LabelledLaunchSchema] = Field(
        default_factory=list, description="A main thread's Launches' labels"
    )
    calls: list[LabelledCallSchema] = Field(
        default_factory=list, description="The Calls' labels"
    )
    segments: list[LabelledSegmentSchema] = Field(
        default_factory=list,
        description=(
            "Every Segment, by position from 1; on an appended call from the"
            " one its boundary's Call falls in"
        ),
    )
    tool_calls: list[LabelledToolCallSchema] = Field(
        default_factory=list, description="The labels of the Tool Calls with any"
    )
    events: list[LabelledEventSchema] = Field(
        default_factory=list, description="The labeller's Events"
    )
    context_parts: list[LabelledContextPartSchema] = Field(
        default_factory=list,
        description="The labeller's Context Parts, each carved out of its Call's prompt",
    )
    test_runs: list[LabelledTestRunSchema] = Field(
        default_factory=list, description="The Test Runs the Transcript's labels hold"
    )
    ci_waits: list[LabelledCIWaitSchema] = Field(
        default_factory=list, description="The waits of its Tool Calls on CI Builds"
    )
    documents: list[LabelledDocumentSchema] = Field(
        default_factory=list,
        description="A main thread's labels of the Documents handed with it",
    )


class PublishedMeasureSchema(_Published):
    """A figure read for a Work Unit."""

    measure: Name = Field(description="The Unit Measure's code")
    amount: Decimal = Field(description="The figure, in the measure's unit")


class PublishedWorkUnitSchema(_Published):
    """A Work Unit, whole, by its key, which is the same at every relabel."""

    key: Name = Field(description="The labeller's key of the unit")
    kind: Name = Field(description="The Work Unit Kind's code")
    part_of: Name | None = Field(
        default=None, description="The key of the unit it sits in"
    )
    occasioned_by: Name | None = Field(
        default=None, description="The key of the unit whose outcome made it necessary"
    )
    rework_kind: Name | None = Field(
        default=None, description="The Rework Kind's code, where it is work redone"
    )
    title: Name = Field(description="Its title")
    variant: str | None = Field(default=None, description="Its variant")
    role: str | None = Field(default=None, description="The role that did it")
    round: Place | None = Field(default=None, description="Its round")
    outcome: Name | None = Field(default=None, description="The Unit Outcome's code")
    started_at: AwareDatetime | None = Field(default=None, description="Its start")
    ended_at: AwareDatetime | None = Field(default=None, description="Its end")
    card: str | None = Field(default=None, description="The card it serves")
    measures: list[PublishedMeasureSchema] = Field(
        default_factory=list, description="Its figures, one per Unit Measure"
    )


class PublishedTestSuiteSchema(_Published):
    """A Test Suite a Test Run names."""

    code: Name = Field(description="The labeller's code of the suite")
    name: Name = Field(description="Its name, to be read")


class PublishedCIBuildSchema(_Published):
    """A CI Build a CI Wait names, as the wait gave it."""

    job: Name = Field(description="Its job")
    number: Place = Field(description="Its number")
    result: Name | None = Field(default=None, description="The Build Result's code")
    queued_at: AwareDatetime | None = Field(default=None, description="When queued")
    started_at: AwareDatetime | None = Field(default=None, description="Its start")
    ended_at: AwareDatetime | None = Field(default=None, description="Its end")
    commit: Name | None = Field(
        default=None, description="The hash the wait's command named"
    )
    deployed_at: AwareDatetime | None = Field(
        default=None, description="When the deploy it triggered finished"
    )


class PublishedLabellingSchema(_Published):
    """The labeller's labels of one Transcript: what Pilot holds of its labels
    after the call, on an appended call from its boundary on (DB decision 81,
    assertion 561)."""

    version: Name = Field(
        description="The labeller's own version that gave them", examples=["1.0.0"]
    )
    stamp: Name = Field(
        description=("The labeller's stamp of all it read for them besides the file")
    )
    labels: PublishedLabelsSchema = Field(description="The Transcript's own labels")
    units: list[PublishedWorkUnitSchema] = Field(
        default_factory=list,
        description=(
            "Every Work Unit the labels name and every one above them, each after"
            " the units it sits in and is occasioned by"
        ),
    )
    test_suites: list[PublishedTestSuiteSchema] = Field(
        default_factory=list, description="Every Test Suite a Test Run names"
    )
    ci_builds: list[PublishedCIBuildSchema] = Field(
        default_factory=list, description="Every CI Build a CI Wait names"
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
            "A main thread's label, with a labelling alone: the group it belongs"
            " to, whose adopted project then adopts it; none where its labels"
            " name none, and the transcript is then adopted by no project"
        ),
    )
    labelling: PublishedLabellingSchema | None = Field(
        default=None,
        description=(
            "The labeller's labels of the Transcript, which replace all Pilot"
            " holds, on an appended call all it holds from the boundary on; none"
            " where no labeller answered for it, and Pilot then keeps the labels"
            " it holds"
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
