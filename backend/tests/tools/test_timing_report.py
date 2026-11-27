"""The timing's tables (`tools/timing/report.py`): where a part's time passes
two seconds, on the line through its times at two sizes."""

import pytest

from tools.timing.report import burst, parts, passes


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
