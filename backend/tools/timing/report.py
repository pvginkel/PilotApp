"""The timing's tables (F154.9), from the parts' results at two sizes.

    uv run python -m tools.timing.report results/630000.json results/3000000.json

Each part's time at both sizes, over all time and over a quota week, the
size at which it passes two seconds, and the statements that went to disk;
the record's size on disk at both against production's 10 Gi volume; the
burst, where the timing read one (a timing of some parts alone, `--only`,
reads none); and one walk, what the walk's event has one page read again:
the rows of the view in view and the quick filters' counts, summed, against
the walk's 30 s, and an open filter's pane's values beside them, where the
timing timed them. A table with no row is not printed. A part passes two
seconds where the line through its two times, taken as growing in step with
the Calls, reaches it: "beyond" where it grows by less than it would need to
within ten times the larger size, "—" where it does not grow.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

BOUND_MS = 2_000.0
"""API-2's two seconds."""

VOLUME = 10 * 1024**3
"""Production's volume, 10 Gi, which every database of the cluster shares."""

WALK_MS = 30_000.0
"""The collector's walk, every 30 s on both stages
(`COLLECTOR_WALK_INTERVAL_SECONDS`)."""

VIEWS = ("rows", "projects", "work_types", "medians", "threshold", "each_item")
"""The parts that are a view's rows, each what the view in view reads again
at a walk beside the quick filters' counts."""

COUNTS = "quick_filters"
"""The quick filters' counts, which a walk reads again with every view."""

PANES = ("values_call", "values_conversation")
"""A filter's pane's values, which a walk reads again while the pane is open."""


def passes(small: tuple[int, float], large: tuple[int, float]) -> str:
    """The Calls at which a part's time passes `BOUND_MS`, on the line
    through its times at two sizes."""
    (n1, t1), (n2, t2) = small, large
    if t1 > BOUND_MS:
        return f"below {n1:,}"
    if t2 > BOUND_MS:
        return f"{round(n1 + (BOUND_MS - t1) * (n2 - n1) / (t2 - t1), -4):,.0f}"
    if t2 <= t1:
        return "—"
    at = n1 + (BOUND_MS - t1) * (n2 - n1) / (t2 - t1)
    return "beyond" if at > 10 * n2 else f"{round(at, -5):,.0f}"


def _calls(found: dict[str, Any]) -> int:
    return int(found["record"]["rows"]["calls"])


def _timed(found: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(part["key"], part["range"]): part for part in found["parts"]}


def _ms(part: dict[str, Any] | None) -> str:
    if part is None:
        return ""
    if part["error"]:
        return "refused"
    return f"{part['ms']:,.0f}"


def _gib(size: int) -> str:
    return f"{size / 1024**3:.2f} GiB"


def record(results: Sequence[dict[str, Any]]) -> list[str]:
    head = "| | " + " | ".join(f"{_calls(r):,} calls" for r in results) + " |"
    lines = [head, "|---|" + "---:|" * len(results)]
    rows = results[0]["record"]["rows"]
    for table in rows:
        lines.append(
            f"| {table} | "
            + " | ".join(f"{r['record']['rows'][table]:,}" for r in results)
            + " |"
        )
    lines.append(
        "| On disk | "
        + " | ".join(
            f"{_gib(r['record']['database_bytes'])}, "
            f"{r['record']['database_bytes'] / VOLUME:.0%} of 10 Gi"
            for r in results
        )
        + " |"
    )
    lines.append(
        "| Calls from | "
        + " | ".join(r["record"]["first_call"][:10] for r in results)
        + " |"
    )
    return lines


def parts(small: dict[str, Any], large: dict[str, Any]) -> list[str]:
    n1, n2 = _calls(small), _calls(large)
    first, second = _timed(small), _timed(large)
    lines = [
        f"| Part | Range | {n1:,}, ms | {n2:,}, ms | Passes 2 s at | "
        f"Slowest statement at {n2:,}, ms | Gone to disk at {n2:,} |",
        "|---|---|---:|---:|---|---:|---|",
    ]
    labels = {part["key"]: part["label"] for part in large["parts"]}
    for key, range_ in second:
        one, other = first.get((key, range_)), second[(key, range_)]
        crossing = (
            passes((n1, one["ms"]), (n2, other["ms"]))
            if one is not None and not one["error"] and not other["error"]
            else ""
        )
        if other["error"]:
            slowest, gone = "refused", "refused"
        else:
            slowest = f"{max((s['ms'] for s in other['statements']), default=0):,.0f}"
            gone = "; ".join(
                sorted(
                    {
                        s.split(",")[0]
                        for st in other["statements"]
                        for s in st["spills"]
                    }
                )
            )
        lines.append(
            f"| {labels[key]} | {range_} | {_ms(one)} | {_ms(other)} | {crossing} | "
            f"{slowest} | {gone or 'none'} |"
        )
    return lines


def burst(results: Sequence[dict[str, Any]]) -> list[str]:
    if not results[0]["burst"]:
        return []
    lines = [
        "| At once | " + " | ".join(f"{_calls(r):,} calls, ms" for r in results) + " |"
    ]
    lines.append("|---:|" + "---|" * len(results))
    for index, one in enumerate(results[0]["burst"]):
        cells = []
        for r in results:
            reads = r["burst"][index]["reads_ms"]
            cells.append(
                f"each {min(reads):,.0f} to {max(reads):,.0f}, all {r['burst'][index]['wall_ms']:,.0f}"
            )
        lines.append(f"| {one['at_once']} | " + " | ".join(cells) + " |")
    return lines


def walk(small: dict[str, Any], large: dict[str, Any]) -> list[str]:
    """One walk for one page: each view's rows and the quick filters' counts
    over the same range, each to the millisecond, their sum, and the sum's
    share of the walk's 30 s."""
    n1, n2 = _calls(small), _calls(large)
    first, second = _timed(small), _timed(large)
    lines = [
        f"| The view | Range | {n1:,} calls: rows + counts, ms | "
        f"{n2:,} calls: rows + counts, ms | Of 30 s at {n1:,} | Of 30 s at {n2:,} |",
        "|---|---|---|---|---:|---:|",
    ]
    for key, range_ in second:
        if key not in VIEWS:
            continue
        sums = [
            (round(found[(key, range_)]["ms"]), round(found[(COUNTS, range_)]["ms"]))
            for found in (first, second)
        ]
        cells = [f"{rows:,} + {counts:,} = {rows + counts:,}" for rows, counts in sums]
        shares = [f"{(rows + counts) / WALK_MS:.0%}" for rows, counts in sums]
        lines.append(
            f"| {second[(key, range_)]['label']} | {range_} | "
            + " | ".join(cells + shares)
            + " |"
        )
    return lines


def panes(small: dict[str, Any], large: dict[str, Any]) -> list[str]:
    """What an open filter's pane adds to one walk: its values' time."""
    n1, n2 = _calls(small), _calls(large)
    first, second = _timed(small), _timed(large)
    lines = [
        f"| An open filter's pane | Range | {n1:,} calls, ms | {n2:,} calls, ms |",
        "|---|---|---:|---:|",
    ]
    for key, range_ in second:
        if key in PANES:
            lines.append(
                f"| {second[(key, range_)]['label']} | {range_} | "
                f"{_ms(first.get((key, range_)))} | {_ms(second[(key, range_)])} |"
            )
    return lines


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("small", type=Path)
    parser.add_argument("large", type=Path)
    args = parser.parse_args(argv)
    small = json.loads(args.small.read_text())
    large = json.loads(args.large.read_text())
    for table in (
        record([small, large]),
        parts(small, large),
        burst([small, large]),
        walk(small, large),
        panes(small, large),
    ):
        if table[2:]:
            print("\n".join(table), end="\n\n")


if __name__ == "__main__":
    main()
