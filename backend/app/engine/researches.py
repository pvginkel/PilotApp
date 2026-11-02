"""A researched Block (F52.3; DB decision 71): a Block of a registered
document the pre-ruling pass left unanswered while a work item checks a fact
its answer rests on, and the Research Assignments naming that Work, the latest
standing."""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import distinct_on

from app.models import Item, ResearchAssignment


def standing() -> Select[int, uuid.UUID]:
    """Each named Block's standing Research Assignment (DB 292), as the
    Block's id and the Work's: the one whose Work's Item has the highest
    `seq`."""
    return (
        select(ResearchAssignment.block_id, ResearchAssignment.work_id)
        .join(Item, Item.id == ResearchAssignment.work_id)
        .ext(distinct_on(ResearchAssignment.block_id))
        .order_by(ResearchAssignment.block_id, Item.seq.desc())
    )
