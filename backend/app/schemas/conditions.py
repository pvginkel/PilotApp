"""Schemas for the conditions that hold all work, which the gold bar shows (UC
*The gold bar*; F125, F135.7; DB Condition)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.reference import OverruleKind


class ConditionCode(StrEnum):
    """Condition's codes (DB §2.4; decision 66): the controller unreachable
    (design 2 §13.4), the week's usage halt and the five-hour one (F135.1,
    F135.4)."""

    OUTAGE = "outage"
    WEEK_HALT = "week_halt"
    FIVE_HOUR_HALT = "five_hour_halt"


class ConditionSchema(BaseModel):
    """A condition that holds now."""

    code: ConditionCode = Field(
        description=(
            "Which condition: `outage`, the controller unreachable; `week_halt` "
            "or `five_hour_halt`, the work items halted at the week's or the "
            "five-hour usage limit"
        )
    )
    since: datetime = Field(description="When it began to hold")
    share: float | None = Field(
        description=(
            "A halt's: its window's used share of the subscription's quota in "
            "the latest reading, a fraction, unclamped; null for the outage"
        ),
        examples=[0.92],
    )
    taken_at: datetime | None = Field(
        description=(
            "A halt's: when the latest reading's figures were taken, the age "
            'its line shows, "as of"; null for the outage'
        ),
    )
    offer: OverruleKind | None = Field(
        description=(
            "The week's halt's: the overrule it offers now, one at a time, "
            "`allowance` under the second limit, `run_out` at or over it and "
            "under the wall; null at the wall, where none is offered, and for "
            "the outage and the five-hour halt, which has none"
        ),
    )
    target: float | None = Field(
        description=(
            "The offered allowance's: the week's share at which it would end, "
            "the share plus the allowance and at most the second limit, a "
            "fraction; null for run-out, whose target is the wall, and for the "
            "other conditions"
        ),
        examples=[0.97],
    )


class ConditionsSchema(BaseModel):
    """The conditions that hold now, which the gold bar shows."""

    conditions: list[ConditionSchema] = Field(
        description=(
            "Each condition that holds, the outage first, then the week's halt, "
            "then the five-hour halt; empty while none does"
        )
    )
