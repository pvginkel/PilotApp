"""The tracker-events endpoint's reply (F136.1)."""

from pydantic import BaseModel, Field


class TrackerEventReplySchema(BaseModel):
    """What a delivery the endpoint took did: how many card waits it fired,
    none for one it dropped."""

    fired: int = Field(..., ge=0, description="How many card waits the delivery fired")
