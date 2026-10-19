"""The shapes of the sync's testing endpoints."""

from pydantic import BaseModel, Field

from app.schemas.sync_schema import Sha256


class TestingSyncAnswerRequestSchema(BaseModel):
    """A person's answer to a block of a document of the store's tree."""

    path: str = Field(
        ...,
        description="The document's path, from the tree's root",
        examples=["recipe-box/items/3-which-oven.md"],
    )
    block: str = Field(..., description="The block's id", examples=["Q1"])
    answer: str = Field(
        ..., description="An option's label, or free words", examples=["Gas"]
    )
    user: str = Field(..., description="The handle of the person who answers")


class TestingSyncAnswerResponseSchema(BaseModel):
    """The document's path and the tree hash it holds once answered."""

    path: str = Field(..., description="The document's path, from the tree's root")
    hash: Sha256 = Field(..., description="The path's tree hash")
