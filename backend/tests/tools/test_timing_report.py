"""The timing's tables (`tools/timing/report.py`): where a part's time passes
two seconds, on the line through its times at two sizes; one walk, a view's
rows and the quick filters' counts summed against the walk's 30 s; and what an
open filter's pane adds to it; a table with no row not printed."""

import json
from pathlib import Path
from typing import Any

import pytest

from tools.timing.report import burst, main, panes, parts, passes, walk


@pytest.mark.parametrize(
    ("small", "large", "found"),
    [
        pytest.param(
            (630_000, 500.0), (3_000_000, 1_500.0), "4,200,000", id="beyond the larger"
        ),
        pytest.param(
            (630_000, 1_000.0), (3_000_000, 3_000.0), "1,820,000", id="between the two"
        ),
        pytest.param(
            (630_000, 2_500.0),
            (3_000_000, 9_000.0),
            "below 630,000",
            id="past it already",
        ),
        pytest.param((630_000, 40.0), (3_000_000, 38.0), "—", id="not growing"),
        pytest.param(
            (630_000, 40.0), (3_000_000, 41.0), "beyond", id="growing too slowly"
        ),
    ],
)
def test_where_a_part_passes_two_seconds(
    small: tuple[int, float], large: tuple[int, float], found: str
) -> None:
    assert passes(small, large) == found


def _part(ms: float, error: str | None) -> dict[str, object]:
    return {
        "key": "attributes",
        "label": "By's counts",
        "range": "all",
        "ms": ms,
        "error": error,
        "statements": [],
    }


def test_a_refused_part_reads_refused_in_every_cell_it_has_no_figure_for() -> None:
    small = {"record": {"rows": {"calls": 630_000}}, "parts": [_part(19_472.0, None)]}
    large = {
        "record": {"rows": {"calls": 3_000_000}},
        "parts": [_part(0, "a statement needed more temporary disk")],
    }

    assert parts(small, large)[2] == (
        "| By's counts | all | 19,472 | refused |  | refused | refused |"
    )


def test_a_timing_of_some_parts_alone_has_no_burst_table() -> None:
    timed = {"record": {"rows": {"calls": 630_000}}, "parts": [], "burst": []}

    assert burst([timed, timed]) == []


def _timed(calls: int, *parts: tuple[str, str, float]) -> dict[str, Any]:
    return {
        "record": {"rows": {"calls": calls}},
        "parts": [
            {
                "key": key,
                "label": key.capitalize(),
                "range": range_,
                "ms": ms,
                "error": None,
            }
            for key, range_, ms in parts
        ],
    }


def test_one_walk_sums_each_views_rows_and_the_counts_over_its_range() -> None:
    small = _timed(
        630_000,
        ("rows", "all", 1_890.9),
        ("quick_filters", "all", 3_531.4),
        ("rows", "lqw", 282.5),
        ("quick_filters", "lqw", 1_949.0),
        ("values_call", "all", 1_511.7),
    )
    large = _timed(
        3_000_000,
        ("rows", "all", 9_106.0),
        ("quick_filters", "all", 27_556.0),
        ("rows", "lqw", 494.0),
        ("quick_filters", "lqw", 15_408.0),
        ("values_call", "all", 9_700.0),
    )

    assert walk(small, large)[2:] == [
        "| Rows | all | 1,891 + 3,531 = 5,422 | 9,106 + 27,556 = 36,662 | 18% | 122% |",
        "| Rows | lqw | 282 + 1,949 = 2,231 | 494 + 15,408 = 15,902 | 7% | 53% |",
    ]
    assert panes(small, large)[2:] == ["| Values_call | all | 1,512 | 9,700 |"]


def test_a_timing_that_timed_no_views_rows_prints_no_walk_and_no_pane(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = []
    for calls in (630_000, 3_000_000):
        timed = _timed(calls, ("lanes", "all", 2_000.0))
        timed["record"].update(
            database_bytes=2**30, first_call="2026-09-18T00:00:00+00:00"
        )
        timed["parts"][0]["statements"] = []
        timed["burst"] = []
        file = tmp_path / f"{calls}.json"
        file.write_text(json.dumps(timed))
        files.append(str(file))

    main(files)

    printed = capsys.readouterr().out
    assert "| Lanes | all |" in printed
    assert "The view" not in printed
    assert "An open filter's pane" not in printed
    assert "At once" not in printed
