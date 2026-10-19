"""The sync protocol's JSON shapes (design 1 §5.1)."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A hash the protocol speaks: the sha256 of a file's bytes, lowercase hex."""


class SyncProtocolRangeSchema(BaseModel):
    """The protocol versions the server accepts, both ends included: a 426's
    body."""

    min: int = Field(..., description="The oldest protocol version accepted")
    max: int = Field(..., description="The newest protocol version accepted")


class SyncManifestRequestSchema(BaseModel):
    """The store's tree as its sidecar sees it, posted for the reconcile; the
    paths from the tree's root."""

    tree: dict[str, Sha256] = Field(
        ..., description="Each file on disk, with the hash of its bytes"
    )
    shadow: dict[str, Sha256] = Field(
        ..., description="Each path the sidecar has synced, with the hash it synced"
    )


class SyncManifestEntrySchema(BaseModel):
    """A path the store syncs."""

    path: str = Field(..., description="The path, from the tree's root")
    hash: str = Field(..., description="The tree hash: what the file must hold")
    readonly: bool = Field(..., description="Whether the path is a read-only view")


class SyncManifestResponseSchema(BaseModel):
    """The manifest, and what the sidecar does to its tree to match it, each
    list in path order."""

    manifest: list[SyncManifestEntrySchema] = Field(
        ..., description="Every path the store syncs"
    )
    send_up: list[str] = Field(
        ...,
        description="Paths of the manifest changed on disk since they were synced",
    )
    write_down: list[SyncManifestEntrySchema] = Field(
        ..., description="Paths of the manifest the file on disk does not hold"
    )
    delete: list[str] = Field(
        ..., description="Paths synced that the manifest no longer lists"
    )


class SyncHelloSchema(BaseModel):
    """The change stream's first event."""

    protocol: SyncProtocolRangeSchema = Field(
        ..., description="The protocol versions the server accepts"
    )
    manifest_hash: Sha256 = Field(
        ..., description="The hash of the manifest as the stream opened"
    )


class SyncChangeSchema(BaseModel):
    """A change event: the tree hash of a path moved."""

    path: str = Field(..., description="The path, from the tree's root")
    hash: Sha256 = Field(..., description="The tree hash it moved to")
