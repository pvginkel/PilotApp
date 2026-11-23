"""The outlier rule (the prototype's `design.md`, `OUTLIER`): above Q3 +
1.5·IQR and at least twice the median, both; none among fewer than five
values or on a median of zero or less."""

import pytest

from app.dashboard.outliers import LEAST, outliers, quantile


class TestQuantile:
    @pytest.mark.parametrize(
        ("q", "expected"),
        [(0.0, 1.0), (0.25, 1.75), (0.5, 2.5), (0.75, 3.25), (1.0, 4.0)],
    )
    def test_it_reads_between_the_two_values_around_it(
        self, q: float, expected: float
    ) -> None:
        assert quantile([1.0, 2.0, 3.0, 4.0], q) == pytest.approx(expected)

    def test_one_value_is_every_quantile(self) -> None:
        assert quantile([7.0], 0.9) == 7.0


class TestOutliers:
    def test_above_the_fence_and_twice_the_median(self) -> None:
        values = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 2.0, "e": 2.0, "f": 9.0}

        assert outliers(values) == {"f"}

    def test_above_the_fence_but_under_twice_the_median_is_none(self) -> None:
        values = dict.fromkeys("abcde", 10.0) | {"f": 10.5, "g": 19.0}
        ordered = sorted(values.values())
        first, third = quantile(ordered, 0.25), quantile(ordered, 0.75)

        assert third + 1.5 * (third - first) < 19.0 < 2 * quantile(ordered, 0.5)
        assert outliers(values) == set()

    def test_twice_the_median_but_within_the_fence_is_none(self) -> None:
        values = dict.fromkeys("abcd", 1.0) | dict.fromkeys("efg", 4.0)
        ordered = sorted(values.values())
        first, third = quantile(ordered, 0.25), quantile(ordered, 0.75)

        assert 2 * quantile(ordered, 0.5) <= 4.0 < third + 1.5 * (third - first)
        assert outliers(values) == set()

    def test_among_fewer_than_the_least_none(self) -> None:
        values = dict.fromkeys("abcd"[: LEAST - 1], 1.0) | {"z": 100.0}

        assert len(values) == LEAST
        assert outliers(values) == {"z"}
        assert outliers({key: values[key] for key in list(values)[1:]}) == set()

    def test_on_a_median_of_none_or_less_none(self) -> None:
        values = dict.fromkeys("abcdef", 0.0) | {"z": 5.0}

        assert outliers(values) == set()
