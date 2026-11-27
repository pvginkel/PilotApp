"""The figures, the aggregates, the built-in ratios and the time ranges
Pilot's code declares (F154.4, F155.3), and a figure per Unit Measure the
labeller declares. A ratio here names nothing of a workflow; one that names
a declared kind or value is a stored row."""

from typing import Any

from sqlalchemy import ColumnElement, Integer, case, cast, extract, literal

from app.dashboard.catalogue import (
    COUNT,
    Aggregate,
    Figure,
    Path,
    Ratio,
    Row,
    TimeRange,
)
from app.dashboard.facts import measure_join
from app.models import UnitMeasure

TOKEN_KINDS = ("input", "cache_write", "cache_read", "output")
"""The Token Kinds within none (DB 547), which a Turn counts and a Call's
finer ones add up to: the kinds a figure of tokens splits by."""


def _number(path: Path) -> Path:
    """A flag as a number to sum, 1 where it holds."""
    return lambda row: cast(path(row), Integer)


def _tokens(row: Row) -> ColumnElement[Any]:
    total = row[f"{TOKEN_KINDS[0]}_tokens"]
    for kind in TOKEN_KINDS[1:]:
        total = total + row[f"{kind}_tokens"]
    return total


def _kind(kind: str) -> Path:
    return lambda row: row[f"{kind}_tokens"]


FIGURES = (
    Figure(
        key="cost",
        label="Cost",
        fact="call",
        line=(
            "A Call's tokens of each kind at the Price in force when it ran, "
            "in US dollars; an estimate's is its Turn's own reported cost"
        ),
        format="usd",
        path=lambda row: row["cost"],
    ),
    Figure(
        key="tokens",
        label="Tokens",
        fact="call",
        line="The tokens a Call counts: read fresh, written to the cache, read from it and written by the model",
        format="tokens",
        path=_tokens,
        kinds={kind: _kind(kind) for kind in TOKEN_KINDS},
    ),
    Figure(
        key="calls",
        label="Calls",
        fact="call",
        line="The Calls, an estimate counting as one",
        format="count",
        path=lambda row: literal(1),
        aggregate=COUNT,
    ),
    Figure(
        key="misses",
        label="Cache misses",
        fact="call",
        line="The Calls that wrote again what their predecessor left cached",
        format="count",
        path=_number(lambda row: row["cache_miss"]),
    ),
    Figure(
        key="miss_cost",
        label="Miss cost",
        fact="call",
        line="The cost of the Calls that are cache misses",
        format="usd",
        path=lambda row: case((row["cache_miss"], row["cost"])),
    ),
    Figure(
        key="past_ttl",
        label="Waits past the cache's lifetime",
        fact="call",
        line="The Calls that waited longer than the cache their predecessor wrote lives",
        format="count",
        path=_number(lambda row: row["past_ttl"]),
    ),
    Figure(
        key="compactions",
        label="Compactions",
        fact="call",
        line="The Calls that follow a compaction of their thread's context",
        format="count",
        path=_number(lambda row: row["compaction_id"].is_not(None)),
    ),
    Figure(
        key="rewinds",
        label="Rewinds",
        fact="call",
        line="The Calls whose predecessor is an older Call than the one before them",
        format="count",
        path=_number(lambda row: row["rewind"]),
    ),
    Figure(
        key="ctx",
        label="Peak context",
        fact="call",
        line="The largest context a Call carried: its input and cache tokens",
        format="tokens",
        path=lambda row: row["context_tokens"],
        within="max",
        aggregate="max",
        stacks=False,
    ),
    Figure(
        key="waited",
        label="Waited",
        fact="call",
        line=(
            "From a Call's predecessor's completion to its own sending, or to "
            "its completion where it has no sending time"
        ),
        format="seconds",
        path=lambda row: row["waited_seconds"],
    ),
    Figure(
        key="took",
        label="Took",
        fact="call",
        line="From a Call's sending to its completion, none where it has no sending time",
        format="seconds",
        path=lambda row: extract("epoch", row["completed_at"] - row["sent_at"]),
    ),
    Figure(
        key="turns",
        label="Pilot turns",
        fact="turn",
        line="The Turns of Pilot's Sessions",
        format="count",
        path=lambda row: literal(1),
        aggregate=COUNT,
    ),
    Figure(
        key="turn_time",
        label="Turn wall-clock",
        fact="turn",
        line="From a Turn's start to its end",
        format="seconds",
        path=lambda row: row["seconds"],
    ),
    Figure(
        key="failed_turns",
        label="Failed turns",
        fact="turn",
        line="The Turns that ended on an error",
        format="count",
        path=_number(lambda row: row["failed"]),
    ),
    Figure(
        key="reported_cost",
        label="Pilot's reported cost",
        fact="turn",
        line=(
            "A Turn's own cost as its result reported it, the cross-check of "
            "the computed cost: it reads low by what a killed process spent"
        ),
        format="usd",
        path=lambda row: row["reported_cost"],
    ),
    Figure(
        key="events",
        label="Events",
        fact="event",
        line="The events: those stored, and the occurrences other facts record",
        format="count",
        path=lambda row: literal(1),
        aggregate=COUNT,
    ),
    Figure(
        key="error_events",
        label="Error events",
        fact="event",
        line="The events whose kind counts as an error",
        format="count",
        path=_number(lambda row: row["is_error"]),
    ),
    Figure(
        key="units",
        label="Work units",
        fact="work_unit",
        line="The Work Units the labeller recognised",
        format="count",
        path=lambda row: literal(1),
        aggregate=COUNT,
    ),
)

AGGREGATES = (
    Aggregate("sum", "Sum", "The items' figures added up"),
    Aggregate("median", "Median", "The middle item's figure"),
    Aggregate("mean", "Mean", "The items' figures added up, over their number"),
    Aggregate("max", "Max", "The largest item's figure"),
    Aggregate("p90", "P90", "The figure nine items in ten stay at or under"),
    Aggregate(COUNT, "Count", "The number of items, on a fact's counting figure alone"),
)

RATIOS = (
    Ratio(
        key="overhead",
        label="Overhead ratio",
        line=(
            "The cost of Pilot's chats, jobs and runs over the cost of its "
            "work items; what ran outside Pilot is in neither"
        ),
        format="share",
        numerator="cost.sum(source=chat|pilot)",
        denominator="cost.sum(source=work)",
    ),
    Ratio(
        key="miss_share",
        label="Miss-cost share",
        line="The cost of the cache misses over the cost of all",
        format="share",
        numerator="miss_cost.sum",
        denominator="cost.sum",
    ),
    Ratio(
        key="per_call",
        label="Cost per call",
        line="The cost over the number of Calls",
        format="usd",
        numerator="cost.sum",
        denominator="calls.count",
    ),
)

RANGES = (
    TimeRange("today", "Today", "Today, from midnight", "day"),
    TimeRange("d2", "Last 2 days", "Yesterday and today", "day", count=2),
    TimeRange(
        "d7", "Last 7 days", "The last seven days, today among them", "day", count=7
    ),
    TimeRange("qw", "This quota week", "The running quota week", "quota_week"),
    TimeRange(
        "lqw",
        "Last quota week",
        "The quota week before the running one",
        "quota_week",
        back=1,
    ),
    TimeRange(
        "l2",
        "Last 2 quota weeks",
        "The running quota week and the one before",
        "quota_week",
        count=2,
    ),
    TimeRange(
        "l4",
        "Last 4 quota weeks",
        "The running quota week and the three before",
        "quota_week",
        count=4,
    ),
    TimeRange(
        "l8",
        "Last 8 quota weeks",
        "The running quota week and the seven before",
        "quota_week",
        count=8,
    ),
    TimeRange("all", "All time", "Everything the record holds"),
)


def measure_figure(measure: UnitMeasure, key: str) -> Figure:
    """The figure of a Unit Measure, under `key`: a Work Unit's figure of it.
    Its path holds the measure's code, never the row, which the session that
    read it lets go while the process keeps the catalogue."""
    join = measure_join(measure.code)
    return Figure(
        key=key,
        label=measure.name,
        fact="work_unit",
        line=measure.description,
        format="count",
        path=lambda row: row.to(join).c.amount,
    )
