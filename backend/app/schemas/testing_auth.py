"""Schemas for testing authentication endpoints."""

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class TestSessionCreateSchema(BaseModel):
    """Request schema for creating a test authentication session."""

    model_config = ConfigDict(from_attributes=True)

    subject: str = Field(..., description="User subject identifier (sub claim)")
    name: str | None = Field(None, description="User display name")
    email: str | None = Field(None, description="User email address")
    roles: list[str] = Field(default_factory=list, description="User roles")


class TestSessionResponseSchema(BaseModel):
    """Response schema for test session creation."""

    model_config = ConfigDict(from_attributes=True)

    subject: str = Field(..., description="User subject identifier")
    name: str | None = Field(None, description="User display name")
    email: str | None = Field(None, description="User email address")
    roles: list[str] = Field(..., description="User roles")


class ForceErrorQuerySchema(BaseModel):
    """Query parameters for force-error endpoint."""

    model_config = ConfigDict(from_attributes=True)

    status: int = Field(..., description="HTTP status code to return on next /api/auth/self request")


def _coerce_status_int(value: object) -> object:
    """Coerce numeric query-string values to int before Literal validation.

    Flask passes query parameters as strings (e.g. ``"401"``); Pydantic v2's
    Literal validator does not auto-coerce strings to ints, so we widen the
    accepted input shape with a BeforeValidator. Anything that is not a
    digit-only string (or already an int) is passed through unchanged so
    Literal validation produces the expected error message.
    """
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return value


class ForceSSECallbackErrorQuerySchema(BaseModel):
    """Query parameters for /api/testing/sse/force-callback-error."""

    model_config = ConfigDict(from_attributes=True)

    status: Annotated[Literal[401, 403], BeforeValidator(_coerce_status_int)] = Field(
        ...,
        description="HTTP status code to return on the next SSE connect callback (401 or 403 only).",
    )
