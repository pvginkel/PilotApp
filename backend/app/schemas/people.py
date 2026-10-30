"""Schemas for /api/people: the signed-in person, their handle, their
notification token and their alarms switch."""

from pydantic import BaseModel, Field


class SelfResponseSchema(BaseModel):
    """The signed-in person, as the app's shell and the handle step draw them."""

    handle: str | None = Field(
        description="The person's handle; null at their first sign-in, until they choose it",
        examples=["ada", None],
    )
    handle_prefill: str | None = Field(
        description=(
            "What the handle step's field starts with while the handle is null: the "
            "name's first word made to fit a handle, empty when the token carries no "
            "name; null once the handle is chosen"
        ),
        examples=[None, "ada"],
    )
    name: str | None = Field(
        description=(
            "The full name: the record's once the handle is chosen (the handle when "
            "the token carried none), the token's before, null when it carries none"
        ),
        examples=["Ada Example"],
    )
    initials: str | None = Field(
        description="The avatar's initials, from the name (F106); null with no name",
        examples=["AE"],
    )
    avatar_slot: int | None = Field(
        description=(
            "The avatar's palette slot, from 1, the same on every screen (F132); "
            "null until the handle is chosen"
        ),
        examples=[1, None],
    )
    notification_token_set: bool | None = Field(
        description=(
            "Whether the person saved a notification token (F134); the token itself "
            "is never answered; null until the handle is chosen"
        ),
        examples=[True, None],
    )
    alarms: bool | None = Field(
        description=(
            "The alarms switch (F142.1): on, the alarms of the conditions that hold "
            "reach the person's phone; on by default; null until the handle is chosen"
        ),
        examples=[True, None],
    )


class HandleChoiceSchema(BaseModel):
    """The handle a person chooses at their first sign-in."""

    handle: str = Field(
        description=(
            "Lower-case letters, digits and hyphens; unique; not `agent`; never "
            "changed after"
        ),
        examples=["ada"],
    )


class NotificationTokenSchema(BaseModel):
    """The notification token a person saves (F134)."""

    token: str = Field(
        description=(
            "The bearer token of the person's bridge registration: visible ASCII, "
            "with no spaces or line breaks; never shown back once saved"
        ),
        examples=["registration-token-of-ada"],
    )


class AlarmsSwitchSchema(BaseModel):
    """Where a person turns their alarms switch (F142.1)."""

    alarms: bool = Field(
        description=(
            "On: the alarms of the conditions that hold are submitted to the "
            "person's phone; off: those standing are dismissed"
        ),
        examples=[False],
    )
