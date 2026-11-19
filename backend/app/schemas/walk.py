"""The event a walk of the collector's raises where it wrote a row (F152.14,
F154.8)."""

from pydantic import AwareDatetime, BaseModel, Field


class CollectionChangedSchema(BaseModel):
    """The payload of `collection_changed`: Pilot holds other facts of the
    fleet's transcripts than it did when the walk before ended."""

    as_of: AwareDatetime = Field(
        description="When the walk that wrote them ended: the latest Walk's end"
    )
