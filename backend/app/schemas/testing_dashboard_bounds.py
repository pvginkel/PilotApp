"""Schema for the testing endpoint that sets the dashboard engine's bounds."""

from pydantic import BaseModel, Field


class DashboardBoundsSchema(BaseModel):
    """The dashboard engine's timeout (F154.5); left out or null, the one
    the app booted with. And its hold, for a spec that sees a task between
    its progress and its end."""

    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Seconds a read of the engine takes at most before it is refused, "
            "its wait for a slot and its statements together"
        ),
        examples=[1e-9, None],
    )
    hold: bool = Field(
        default=False,
        description=(
            "Whether the reads that may be held, By's counts after their first "
            "fact, wait until the bounds are set again or their deadline passes"
        ),
        examples=[True, False],
    )
