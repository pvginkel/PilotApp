"""Pilot's notes and alerts as they stand (DB 625, 628, 631): of each place's
Pilot Notes and of each Prose Item's Send Alerts the latest, unless it is
withdrawn, read for the page, the tree and the Done."""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

import pilot_dsl as dsl
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models import Block, Document, Item, PilotNote, SendAlert


@dataclass(frozen=True)
class StandingNote:
    """A Pilot Note standing in its place (DB 625)."""

    note: PilotNote
    block: str | None
    """The local id of the Block it is on; none on its Prose Item as a
    whole."""
    handed_at: datetime | None
    """Its Block's `handed_at`; none on the Prose Item as a whole."""


@dataclass(frozen=True)
class StandingAlert:
    """A Send Alert standing on its Prose Item (DB 631), with the Block it
    awaits."""

    alert: SendAlert
    item_id: uuid.UUID
    """The awaited Block's Prose Item."""
    title: str
    """That Prose Item's title, as its line shows it: its text's, else its
    file's name (F35)."""
    block: str
    """The awaited Block's local id."""
    open: bool
    """Whether the awaited Block's Prose Item is open: the alert shows while
    it is, and its own Prose Item too (DB 631)."""


def standing_notes(
    db: Session, item_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, list[StandingNote]]:
    """The Pilot Notes standing on the Prose Items `item_ids`, by the item's
    id, each item's in its order: the one on the item as a whole first, then
    its Blocks' in the text's order. An item with none is left out."""
    if not item_ids:
        return {}
    rows = db.execute(
        select(PilotNote, Block.local_id, Block.position, Block.handed_at)
        .outerjoin(Block, Block.id == PilotNote.block_id)
        .where(PilotNote.item_id.in_(list(item_ids)))
        .ext(distinct_on(PilotNote.item_id, PilotNote.block_id))
        .order_by(PilotNote.item_id, PilotNote.block_id, PilotNote.id.desc())
    ).all()
    standing: dict[uuid.UUID, list[StandingNote]] = {}
    for note, local_id, _, handed_at in sorted(
        (row for row in rows if row[0].withdrawn_at is None),
        key=lambda row: -1 if row[2] is None else row[2],
    ):
        standing.setdefault(note.item_id, []).append(
            StandingNote(note, local_id, handed_at)
        )
    return standing


def differs(note: PilotNote, block: dsl.Block) -> bool:
    """Whether `note`, standing on `block`, differs (DB 628): it suggests an
    answer, and the block has a recommendation that would record another,
    compared exactly. A differing note takes the recommendation away at the
    Done."""
    if note.suggested_answer is None:
        return False
    recommended = dsl.recommendation(block)
    return recommended is not None and note.suggested_answer != recommended


def standing_alerts(
    db: Session, item_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, StandingAlert]:
    """The Send Alert standing on each of the Prose Items `item_ids`, by the
    item's id. An item with none is left out."""
    if not item_ids:
        return {}
    standing: dict[uuid.UUID, StandingAlert] = {}
    for alert, item_id, local_id, title, done_at, source_path in db.execute(
        select(
            SendAlert,
            Block.document_id,
            Block.local_id,
            Item.title,
            Item.done_at,
            Document.source_path,
        )
        .join(Block, Block.id == SendAlert.awaits_block_id)
        .join(Item, Item.id == Block.document_id)
        .join(Document, Document.id == Item.id)
        .where(SendAlert.item_id.in_(list(item_ids)))
        .ext(distinct_on(SendAlert.item_id))
        .order_by(SendAlert.item_id, SendAlert.id.desc())
    ):
        if alert.withdrawn_at is not None:
            continue
        if title is None:
            # An untitled document is a registered one, named by its file
            # (F35).
            assert source_path is not None
            title = PurePosixPath(source_path).name
        standing[alert.item_id] = StandingAlert(
            alert, item_id, title, local_id, done_at is None
        )
    return standing
