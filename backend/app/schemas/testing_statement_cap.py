"""Schema for the testing endpoint that sends a statement through the
statement cap (app/utils/statement_cap.py)."""

from pydantic import BaseModel, Field


class StatementSendSchema(BaseModel):
    """A statement to send: its length before SQLAlchemy expands it, and
    the ids of its IN list."""

    length: int = Field(
        description="The statement's length in characters, its IN list's ids "
        "not filled in",
        examples=[2001],
    )
    ids: int = Field(ge=1, description="How many ids its IN list holds", examples=[1])
