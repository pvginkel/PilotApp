"""The outliers among a set of values, the screen's one rule (the prototype's
`design.md`, `OUTLIER`): a value above Q3 + 1.5·IQR and at least twice the
median, both. The outlier rows' chip judges the By's rows by their first
measure with it.

- Among fewer than `LEAST` values none is one.
- None is one where the median is zero or less: where most values are none,
  every value that has some would pass.
- A quartile is read between the two values around it, by linear
  interpolation.
"""

from collections.abc import Mapping, Sequence

LEAST = 5
"""The values the rule needs before any of them is an outlier."""


def outliers[Key](values: Mapping[Key, float]) -> set[Key]:
    """The keys whose value is an outlier among `values`."""
    ordered = sorted(values.values())
    if len(ordered) < LEAST:
        return set()
    first, median, third = (quantile(ordered, q) for q in (0.25, 0.5, 0.75))
    if median <= 0:
        return set()
    fence = third + 1.5 * (third - first)
    return {
        key for key, value in values.items() if value > fence and value >= 2 * median
    }


def quantile(ordered: Sequence[float], q: float) -> float:
    """The `q` quantile of values in their order, between the two around it."""
    at = q * (len(ordered) - 1)
    below = int(at)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (at - below)
