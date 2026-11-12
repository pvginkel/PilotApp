"""Schema for the testing endpoint that sets the usage halts' settings."""

from pydantic import BaseModel, Field

from app.app_config import HaltSetting


class HaltSettingsSchema(BaseModel):
    """What each usage halt does to the work items (F135.6); a setting left
    out or null is the one the app booted with."""

    week_halt: HaltSetting | None = Field(
        default=None,
        description="What the week's halt does to the work items",
        examples=["no_new_work", None],
    )
    five_hour_halt: HaltSetting | None = Field(
        default=None,
        description="What the five-hour halt does to the work items",
        examples=["hard_stop", None],
    )
