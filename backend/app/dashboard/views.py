"""Pilot's own system views (F155.3): the views the dashboard ships with that
name nothing of a workflow, changed by a release of Pilot. Each deploy makes
the stored ones what this release holds, matched by key
(`DashboardStoreService.ship`).

A view's state is held in its normal form (`state.write`), without the
address's `#dash/`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemView:
    """A system view as its source names it: `key` matches it to its stored
    row, so that a renamed one keeps its row and its stars."""

    key: str
    name: str
    state: str
    note: str | None = None


VIEWS = (
    SystemView(
        key="projects",
        name="Projects",
        state=(
            "t=all&by=project&m=cost.sum&m=tokens.sum&m=misses.sum&m=ctx.max"
            "&col=work_type"
        ),
        note=(
            "Each project's cost, tokens, cache misses and largest context, "
            "over all time, colored by work type"
        ),
    ),
    SystemView(
        key="work_types",
        name="Work types",
        state=(
            "t=all&by=work_type&m=cost.sum&m=tokens.sum&m=misses.sum&m=ctx.max"
            "&col=model"
        ),
        note=(
            "Each work type's cost, tokens, cache misses and largest context, "
            "over all time, colored by model"
        ),
    ),
    SystemView(
        key="where_the_week_went",
        name="Where the week went",
        state="t=l8&by=project&p=time,qweek&m=cost.sum&m=r:overhead&col=source",
        note=(
            "The cost of each of the last eight quota weeks, and the overhead "
            "ratio, colored by source"
        ),
    ),
)
