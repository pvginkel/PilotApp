"""Schemas for a person's overrule of the week's usage halt (F135.2; DB Quota
Overrule)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.reference import OverruleKind


class QuotaOverruleRequestSchema(BaseModel):
    """The overrule the signed-in person makes."""

    kind: OverruleKind = Field(
        description=(
            "Which overrule: `allowance`, a new target, the week's share plus "
            "the allowance and at most the second limit, offered under the "
            "second limit; `run_out`, the target the wall, offered at or over "
            "it and under the wall, where none is offered. It must be the one "
            "the week's halt offers (`offer`)"
        )
    )


class QuotaOverruleSchema(BaseModel):
    """An overrule as it was made."""

    id: int = Field(description="The overrule's id")
    kind: OverruleKind = Field(description="Which overrule: `allowance` or `run_out`")
    target: float | None = Field(
        description=(
            "The allowance's: the week's share at which it ends, a fraction; "
            "null for run-out, which ends at the wall"
        ),
        examples=[0.96],
    )
    made_at: datetime = Field(description="When it was made")
