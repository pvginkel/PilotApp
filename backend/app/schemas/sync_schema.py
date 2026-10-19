"""The sync protocol's JSON shapes (design 1 §5.1)."""

from pydantic import BaseModel, Field


class SyncProtocolRangeSchema(BaseModel):
    """The protocol versions the server accepts, both ends included: a 426's
    body."""

    min: int = Field(..., description="The oldest protocol version accepted")
    max: int = Field(..., description="The newest protocol version accepted")
