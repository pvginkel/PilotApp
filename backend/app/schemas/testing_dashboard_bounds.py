"""Schema for the testing endpoint that sets the dashboard engine's bounds."""

from pydantic import BaseModel, Field


class DashboardBoundsSchema(BaseModel):
    """The dashboard engine's timeout (F154.5); left out or null, the one
    the app booted with."""

    timeout_seconds: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Seconds a read of the engine takes at most before it is refused, "
            "its wait for a slot and its statements together"
        ),
        examples=[1e-9, None],
    )
