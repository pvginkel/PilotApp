"""When a Block became a person's to answer (DB §2.2, Block's `handed_at`;
decision 79): the record of a Block's last move from Pilot's side to the
person's.

Whose a Block is stays read from the rows at every read (`working_on`): a
Block to answer, unanswered and of an open Item, is Pilot's while its Item is
Pilot's or a run holds it (DB 295, 296), and a person's otherwise. A
transaction that may move a Block between the two reads the Blocks of its
project that are Pilot's before it writes (`sides`) and compares them once it
has written (`hand_over`):

- a Block that was Pilot's and is a person's to answer now is handed at the
  move's instant, the latest move kept;
- a Block that is Pilot's has no `handed_at`, so one Pilot answers has none;
- any other Block keeps what it has: one a person's from its put has none, and
  one answered or closed keeps the instant it was handed at.

The moves to a person: the end of a work item's turn or a job's, a pass's or
the job's after a run's turn among them, done, failed or interrupted; a start
that failed; a Stop, a Close, a Stop and take over; the stops of an Archive;
the lift of a Store Update that leaves a job it stopped to a person's Retry;
the quota wall's settle; a Cancel; and the turn-end read, whose last read,
where no job follows it after a Close for good or an Archive, leaves the
person the Blocks of the run's documents read before it, Pilot's while
another document of the run awaited its read. The moves back to Pilot: a
Resume, a Retry, a work item added with its claims and researches, and a
clarification run placed.

Nothing reads `handed_at` to decide anything.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models import Block, Item
from app.services.working_on import Reading, unanswered


@dataclass(frozen=True)
class Sides:
    """The Blocks of one project that are Pilot's, as one reading read them."""

    project_id: uuid.UUID
    pilots: frozenset[int]
    """The ids of the Blocks to answer whose Item is Pilot's, or that a run
    holds."""


def _to_answer(project_id: uuid.UUID) -> Select[Block]:
    """The project's Blocks to answer: unanswered, of an open Item."""
    return (
        select(Block)
        .join(Item, Item.id == Block.document_id)
        .where(Item.project_id == project_id, Item.done_at.is_(None), unanswered())
    )


def sides(db: Session, project_id: uuid.UUID) -> Sides:
    """The project's Blocks that are Pilot's as the rows stand, read before
    a move's writes and, by `hand_over`, after them."""
    reading = Reading(db)
    return Sides(
        project_id,
        frozenset(
            db.scalars(
                _to_answer(project_id)
                .with_only_columns(Block.id)
                .where(or_(reading.pilots(), reading.held()))
            )
        ),
    )


def hand_over(db: Session, before: Sides, at: datetime) -> None:
    """The move written since `before` was read, at `at`, in the caller's
    transaction: each Block that was Pilot's then and is a person's to answer
    now handed at `at`, and no Block that is Pilot's now with a `handed_at`."""
    now = sides(db, before.project_id)
    handed = before.pilots - now.pilots
    if handed:
        for block in db.scalars(
            _to_answer(before.project_id).where(Block.id.in_(handed)).order_by(Block.id)
        ):
            block.handed_at = at
    if now.pilots:
        for block in db.scalars(
            select(Block)
            .where(Block.id.in_(now.pilots), Block.handed_at.is_not(None))
            .order_by(Block.id)
        ):
            block.handed_at = None
    db.flush()
