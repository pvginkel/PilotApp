"""The dimensions Pilot's code declares, over Pilot's own record and the
collector's facts (F154.4), and those the record's rows give: a version
dimension per Component, and a vocabulary's rows as a dimension's values.

A dimension's key is the mockup's where the mockup has the dimension
(`design/mockup/dashboard/state.js`), so that a state written there reads
here. The local time's three are derived in the zone given, and a sitting
ends at the gap the joins were made with (DB decision 80.3).
"""

import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    Integer,
    Text,
    case,
    cast,
    exists,
    extract,
    func,
    literal,
    select,
)

from app.dashboard.catalogue import Dimension, Path, Row, Value
from app.dashboard.facts import version_join
from app.models import ClaimAssignment, Component, ResearchAssignment
from app.models.reference import ChatKind, TurnCause, WorkTrigger

_CALL_FIGURES = ("cost", "tokens", "ctx", "waited", "took")
"""What an item that is one Call carries."""

_ITEM_FIGURES = ("calls", "cost", "tokens", "misses", "miss_cost", "ctx")
"""What an item of a part that holds Calls carries."""

_TURN_FIGURES = (*_ITEM_FIGURES, "turn_time", "reported_cost", "failed_turns")

SOURCES = (
    Value("work", "Work items", "A work item's run"),
    Value(
        "pilot",
        "Pilot's jobs and runs",
        "A job, a clarification run or a research run",
    ),
    Value(
        "chat", "Pilot's chats", "A project's chat, a definition chat or a conversation"
    ),
)

WORK_TYPES = (
    *(
        Value(f"chat:{kind.value}", f"{kind.value.capitalize()} chat")
        for kind in ChatKind
    ),
    Value("conversation", "Conversation"),
    *(
        Value(f"job:{trigger.value}", f"Job: {trigger.value.replace('_', ' ')}")
        for trigger in WorkTrigger
    ),
    Value("clarification", "Clarification run"),
    Value("research", "Research run"),
    Value("claimed", "Claimed action"),
    Value("work", "Work item"),
)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _flag(path: Path) -> Path:
    """A two-valued dimension's key, 1 or 0, none read as 0."""
    return lambda row: cast(func.coalesce(path(row), False), Integer)


def _two(yes: str, no: str) -> tuple[Value, Value]:
    return (Value("1", yes), Value("0", no))


def _assigned(entity: type[Any], row: Row) -> ColumnElement[bool]:
    """Whether the row's Session is a Work a row of `entity` names."""
    return exists(select(literal(1)).where(entity.work_id == row["session_id"]))


def _work_type(row: Row) -> ColumnElement[Any]:
    session = row.to("session")
    return case(
        (
            session.c.kind_code == "chat",
            "chat:" + cast(row.to("chat").c.kind_code, Text),
        ),
        (session.c.kind_code == "conversation", "conversation"),
        (
            session.c.kind_code == "job",
            "job:" + cast(row.to("work").c.trigger_code, Text),
        ),
        (row.to("clarification").c.id.is_not(None), "clarification"),
        (_assigned(ResearchAssignment, row), "research"),
        (_assigned(ClaimAssignment, row), "claimed"),
        (session.c.kind_code == "work", "work"),
    )


def _source(row: Row) -> ColumnElement[Any]:
    session = row.to("session")
    return case(
        (session.c.kind_code.in_(("chat", "conversation")), "chat"),
        (session.c.kind_code == "job", "pilot"),
        (row.to("clarification").c.id.is_not(None), "pilot"),
        (_assigned(ResearchAssignment, row), "pilot"),
        (session.c.kind_code == "work", "work"),
    )


def own_dimensions(zone: str) -> tuple[Dimension, ...]:
    """Pilot's own dimensions and the collector's, the local time's derived
    in `zone`."""

    def local(row: Row) -> ColumnElement[Any]:
        return func.timezone(literal(zone, literal_execute=True), row["at"])

    return (
        # The parts: a project, a Session of Pilot's, its Turn, a thread, a
        # Call; and off every project a sitting, a thread, a Call.
        Dimension(
            key="project",
            label="Project",
            group="part",
            line="The project a Session of Pilot's worked, or the adopted one a thread is of",
            path=lambda row: row.to("project").c.id,
            name=lambda row: row.to("project").c.name,
            null="(No project)",
            one="project",
            many="projects",
            next="psession",
            next_null="sitting",
            figures=_ITEM_FIGURES,
        ),
        Dimension(
            key="psession",
            label="Pilot session",
            group="part",
            line="A Session Pilot ran: a chat, a conversation, a job or a work item's run",
            path=lambda row: row["session_id"],
            null="(No Pilot session)",
            one="Pilot session",
            many="Pilot sessions",
            next="pturn",
            next_null="conversation",
            figures=_ITEM_FIGURES,
        ),
        Dimension(
            key="pturn",
            label="Pilot turn",
            group="part",
            line="A Turn of a Session of Pilot's: one message sent and what it set off",
            path=lambda row: row.to("turn").c.id,
            null="(No Pilot turn)",
            one="Pilot turn",
            many="Pilot turns",
            next="conversation",
            figures=_TURN_FIGURES,
        ),
        Dimension(
            key="sitting",
            label="Sitting",
            group="part",
            line=(
                "The threads on no project that follow each other within the "
                "sitting's gap, by the first one's first Call"
            ),
            path=lambda row: row.to("sitting").c.started_at,
            null="(On a project)",
            one="sitting",
            many="sittings",
            next="conversation",
            figures=_ITEM_FIGURES,
        ),
        Dimension(
            key="conversation",
            label="Conversation",
            group="part",
            line="One transcript: a main thread, or one sub-agent's",
            path=lambda row: row["transcript_id"],
            null="(No transcript)",
            one="conversation",
            many="conversations",
            next="call",
            figures=_ITEM_FIGURES,
        ),
        Dimension(
            key="call",
            label="Call",
            group="part",
            line="One billed call to the model",
            path=lambda row: row["call_id"],
            null="(Estimate: no transcript)",
            one="call",
            many="calls",
            figures=_CALL_FIGURES,
            shows=(
                "model",
                "effort",
                "miss",
                "miss_cause",
                "rewind",
                "compaction",
                "estimate",
            ),
        ),
        # Pilot's own attributes.
        Dimension(
            key="source",
            label="Source",
            group="attribute",
            line=(
                "Whose work a Session of Pilot's is: a work item's run, "
                "Pilot's own jobs and runs, or Pilot's chats"
            ),
            path=_source,
            null="(Outside Pilot)",
            values=SOURCES,
        ),
        Dimension(
            key="work_type",
            label="Work type",
            group="attribute",
            line=(
                "What a Session of Pilot's is for: a chat by its kind, a job by "
                "its trigger, a clarification or research run, a claimed "
                "action, or a work item's run"
            ),
            path=_work_type,
            null="(Outside Pilot)",
            values=WORK_TYPES,
            next="psession",
        ),
        Dimension(
            key="session_kind",
            label="Session kind",
            group="attribute",
            line="The kind of the Session of Pilot's",
            path=lambda row: row.to("session").c.kind_code,
            null="(Outside Pilot)",
            next="psession",
        ),
        Dimension(
            key="turn_cause",
            label="Turn cause",
            group="attribute",
            line="Why Pilot sent the Turn",
            path=lambda row: cast(row.to("turn").c.cause_code, Text),
            null="(No Pilot turn)",
            values=tuple(
                Value(cause.value, cause.value.replace("_", " ").capitalize())
                for cause in TurnCause
            ),
        ),
        Dimension(
            key="person",
            label="Person",
            group="attribute",
            line="Whose message the Turn was",
            path=lambda row: row.to("author").c.id,
            name=lambda row: row.to("author").c.name,
            null="(Pilot's own turn)",
        ),
        Dimension(
            key="failed",
            label="Failed turn",
            group="attribute",
            line="Whether the Turn ended on an error",
            path=_flag(lambda row: row.to("turn").c.error.is_not(None)),
            values=_two("Failed turn", "Turn OK"),
        ),
        Dimension(
            key="environment",
            label="Environment",
            group="attribute",
            line="The environment the thread ran in, else the Session's",
            path=lambda row: row.to("environment").c.id,
            name=lambda row: row.to("environment").c.name,
            null="(No environment)",
        ),
        Dimension(
            key="repository",
            label="Repository",
            group="attribute",
            line="The repository the thread worked in",
            path=lambda row: row.to("repository").c.id,
            name=lambda row: row.to("repository").c.name,
            null="(No repository)",
        ),
        # The collector's facts of a thread and of a Call.
        Dimension(
            key="agent_type",
            label="Agent type",
            group="attribute",
            line="A sub-agent's type, as Claude Code names it",
            path=lambda row: row.to("thread").c.agent_type,
            null="(Main thread)",
        ),
        Dimension(
            key="sub",
            label="Sub-agent",
            group="attribute",
            line="Whether the thread is a sub-agent's",
            path=_flag(lambda row: row.to("thread").c.agent_id.is_not(None)),
            values=_two("Sub-agent", "Main thread"),
        ),
        Dimension(
            key="model",
            label="Model",
            group="attribute",
            line="The model that answered the Call",
            path=lambda row: row["model_code"],
            null="(Estimate: no model)",
        ),
        Dimension(
            key="effort",
            label="Effort",
            group="attribute",
            line="The Call's reasoning effort, as Claude Code wrote it",
            path=lambda row: row["effort"],
            null="(No effort)",
        ),
        Dimension(
            key="stop_reason",
            label="Stop reason",
            group="attribute",
            line="Why the response ended, where it was not the ordinary end",
            path=lambda row: row["stop_reason_code"],
            null="(Ordinary end)",
        ),
        Dimension(
            key="miss",
            label="Cache miss",
            group="attribute",
            line="The Call wrote again what its predecessor left cached",
            path=_flag(lambda row: row["cache_miss"]),
            values=_two("Cache miss", "No miss"),
        ),
        Dimension(
            key="miss_cause",
            label="Miss cause",
            group="attribute",
            line="Why the Call's cache was missed, as the collector reads it",
            path=lambda row: row["miss_cause_code"],
            null="(No cause)",
        ),
        Dimension(
            key="past_ttl",
            label="Wait past the cache's lifetime",
            group="attribute",
            line=("The Call waited longer than the cache its predecessor wrote lives"),
            path=_flag(lambda row: row["past_ttl"]),
            values=_two("Past the lifetime", "Within it"),
        ),
        Dimension(
            key="rewind",
            label="Rewind",
            group="attribute",
            line=(
                "The Call's predecessor is an older Call than the one before "
                "it in its thread"
            ),
            path=_flag(lambda row: row["rewind"]),
            values=_two("Rewind", "No rewind"),
        ),
        Dimension(
            key="compaction",
            label="Compaction",
            group="attribute",
            line="The Call follows a compaction of its thread's context",
            path=_flag(lambda row: row["compaction_id"].is_not(None)),
            values=_two("Compaction", "No compaction"),
        ),
        Dimension(
            key="compact_trigger",
            label="Compaction trigger",
            group="attribute",
            line="The occasion of the compaction the Call follows",
            path=lambda row: row.to("compaction").c.trigger_code,
            null="(No compaction)",
        ),
        Dimension(
            key="estimate",
            label="Estimate",
            group="attribute",
            line=(
                "A Turn standing in for the Calls of a conversation never "
                "collected, with the Turn's own reported cost and tokens"
            ),
            path=_flag(lambda row: row["estimate"]),
            values=_two("Estimate", "Measured"),
        ),
        Dimension(
            key="event_kind",
            label="Event kind",
            group="attribute",
            line="The kind of the event",
            path=lambda row: row["kind_code"],
        ),
        Dimension(
            key="event_error",
            label="Error event",
            group="attribute",
            line="Whether the event's kind counts as an error",
            path=_flag(lambda row: row["is_error"]),
            values=_two("Error", "Not an error"),
        ),
        # Time, the local ones in the zone.
        Dimension(
            key="qweek",
            label="Quota week",
            group="time",
            line="The subscription's seven-day window the moment falls in, by its start",
            path=lambda row: row.to("quota_week").c.starts_at,
            null="(No quota week)",
            next="day",
        ),
        Dimension(
            key="day",
            label="Day",
            group="time",
            line=f"The day in {zone}",
            path=lambda row: cast(local(row), Date),
        ),
        Dimension(
            key="weekday",
            label="Weekday",
            group="time",
            line=f"The day of the week in {zone}",
            path=lambda row: cast(extract("isodow", local(row)), Integer),
            values=tuple(
                Value(str(day), name, position=day)
                for day, name in enumerate(_WEEKDAYS, start=1)
            ),
        ),
        Dimension(
            key="hod",
            label="Hour of day",
            group="time",
            line=f"The hour of the day in {zone}",
            path=lambda row: cast(extract("hour", local(row)), Integer),
        ),
        # A part along its own axis.
        Dimension(
            key="session_start",
            label="Pilot session, in the order created",
            group="order",
            line="The Sessions of Pilot's by when each was created",
            path=lambda row: row["session_id"],
            null="(No Pilot session)",
            base="psession",
            axis=lambda row: row.to("session").c.created_at,
            next="pturn",
        ),
        Dimension(
            key="turn_seq",
            label="Pilot turn, in the order sent",
            group="order",
            line="The Turns of Pilot's by when each was sent",
            path=lambda row: row.to("turn").c.id,
            null="(No Pilot turn)",
            base="pturn",
            axis=lambda row: row.to("turn").c.started_at,
            next="conversation",
        ),
    )


def version_keys(components: Sequence[Component]) -> dict[str, str]:
    """The key of each Component's version dimension, by its code: the code
    in the letters a state's part takes, and a number after it where two
    codes read alike."""
    keys: dict[str, str] = {}
    for component in sorted(components, key=lambda component: component.code):
        slug = re.sub(r"[^a-z0-9]+", "_", component.code.lower()).strip("_")
        key = f"{slug}_version"
        alike = sum(
            1 for taken in keys.values() if re.fullmatch(rf"{key}(_\d+)?", taken)
        )
        keys[component.code] = key if not alike else f"{key}_{alike + 1}"
    return keys


def version_dimension(component: Component, key: str) -> Dimension:
    """The version of `component` a row's Launch ran with (DB 541)."""
    return Dimension(
        key=key,
        label=f"{component.name} version",
        group="attribute",
        line=f"The version of {component.name} the Call's Launch ran with",
        path=lambda row: row.to(version_join(component.code)).c.version,
        null="(No version)",
    )


def with_values(dimension: Dimension, values: Sequence[Value]) -> Dimension:
    """The dimension with a vocabulary's rows as its closed list."""
    return replace(dimension, values=tuple(values))
