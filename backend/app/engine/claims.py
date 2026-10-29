"""A claimed action (F21.6; DB decision 64): an action Block the pre-ruling
pass answered `Pilot does it`, `by: agent`, open and Pilot's until its `done`,
and the Claim Assignments naming the Work that does it, the latest standing."""

import uuid

import pilot_dsl as dsl
from sqlalchemy import ColumnElement, Select, and_, select
from sqlalchemy.dialects.postgresql import distinct_on

from app.models import Block, ClaimAssignment, Item, User
from app.models.reference import BlockKind, UserKind


def claimed() -> ColumnElement[bool]:
    """`pilot_dsl.Block.claimed` as a query's condition on a Block (DB 262)."""
    pilot = select(User.id).where(User.kind_code == UserKind.AGENT).scalar_subquery()
    return and_(
        Block.kind_code == BlockKind.ACTION,
        Block.answer == dsl.CLAIM,
        Block.answered_by_user_id == pilot,
        Block.done_at.is_(None),
    )


def standing() -> Select[int, uuid.UUID]:
    """Each named Block's standing Claim Assignment (DB 260), as the Block's id
    and the Work's: the one whose Work's Item has the highest `seq`."""
    return (
        select(ClaimAssignment.block_id, ClaimAssignment.work_id)
        .join(Item, Item.id == ClaimAssignment.work_id)
        .ext(distinct_on(ClaimAssignment.block_id))
        .order_by(ClaimAssignment.block_id, Item.seq.desc())
    )
