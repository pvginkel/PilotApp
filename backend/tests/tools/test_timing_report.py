"""The timing's tables (`tools/timing/report.py`): where a part's time passes
two seconds, on the line through its times at two sizes."""

import pytest

from tools.timing.report import passes


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
