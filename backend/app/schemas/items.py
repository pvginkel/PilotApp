"""Schemas for /api/items: what a person writes to an item's block."""

from pydantic import BaseModel, ConfigDict, Field


class AnswerRequestSchema(BaseModel):
    """A person's answer to a block."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(
        description=(
            "An option's label, `Agree` to a proposal, `Yes` or `No` to a "
            "confirmation, or free words"
        ),
        examples=["Dome"],
    )
    note: str | None = Field(
        default=None,
        description=(
            "The note under the answer: an action's paste-back, or a No's reason"
        ),
        examples=["Too much rain"],
    )


class ActionDoneRequestSchema(BaseModel):
    """Done on an action, with what the person pasted back."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(
        default=None,
        description="The paste-back, the note under the Done",
        examples=["Key stored under kv/camp"],
    )
