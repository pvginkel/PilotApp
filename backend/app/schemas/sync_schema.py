"""The sync protocol's JSON shapes (design 1 §5.1)."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.reference import ErrorKind

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A hash the protocol speaks: the sha256 of a file's bytes, lowercase hex."""

Folder = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+$")]
"""A project folder the protocol speaks: a name at the tree's root, a slug
or `draft-<number>` (DB decision 1)."""


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


class SyncCheckRequestSchema(BaseModel):
    """The hook's check of a project folder, as the store's sidecar posts it
    once it has flushed the folder."""

    folder: Folder = Field(
        ..., description="The project folder the hook names, from the tree's root"
    )
    wait_seconds: float = Field(
        ..., ge=0, description="How long the sidecar's flush of the folder took"
    )


class SyncSaveErrorSchema(BaseModel):
    """A Save Error of the store's tree."""

    path: str = Field(..., description="The path, from the tree's root")
    kind: ErrorKind = Field(
        ...,
        description="`parse`: the save is held; `reverted`: a record-owned line"
        " was restored",
    )
    line: int | None = Field(..., description="The line of the save it is on")
    message: str = Field(..., description="What is wrong")


class SyncHomelessDeferralSchema(BaseModel):
    """A deferral without a home: a deferred block no plan note names."""

    block: str = Field(
        ..., description="The block as a note's `refs` names it, `<item id>/<local id>`"
    )
    document: str = Field(..., description="Its document's path, from the tree's root")
    title: str | None = Field(
        ..., description="Its item's title; null while its text gives none"
    )
    to: str = Field(..., description="The task it is deferred to, or `plan`")


class SyncCheckResponseSchema(BaseModel):
    """What the hook prints after a tool call that can write the folder."""

    errors: list[SyncSaveErrorSchema] = Field(
        ...,
        description="The Save Errors under the folder, in path order; the"
        " `reverted` ones are reported once",
    )
    homeless_deferrals: list[SyncHomelessDeferralSchema] = Field(
        ...,
        description="The deferrals without a home of the folder's project; none"
        " for a folder of no syncing project",
    )
