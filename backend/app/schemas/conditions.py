"""Schemas for the conditions that hold all work, which the gold bar shows (UC
*The gold bar*; F125; DB Condition)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConditionCode(StrEnum):
    """Condition's codes (DB §2.4) this build has: the controller unreachable
    (design 2 §13.4). The usage halt is slice 016's."""

    OUTAGE = "outage"


class ConditionSchema(BaseModel):
    """A condition that holds now."""

    code: ConditionCode = Field(
        description="Which condition: `outage`, the controller unreachable"
    )
    since: datetime = Field(description="When it began to hold")


class ConditionsSchema(BaseModel):
    """The conditions that hold now, which the gold bar shows."""

    conditions: list[ConditionSchema] = Field(
        description="Each condition that holds; empty while none does"
    )
