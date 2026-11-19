"""A debriefed Work beside the others of its slice (DB decisions 82 and 85):
the Works one Debrief Notice carries, and the time a Work's stage took."""

import uuid
from collections.abc import Collection

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import Item, Turn, Work
from app.models import Session as AgentSession


def awaiting_notice(work: Work) -> ColumnElement[bool]:
    """Over a Work and its Item: a done Work of `work`'s Project that named
    `work`'s subject, whose debrief does not complete it and that no Debrief
    Notice carries yet, which the notice of that subject takes with it (DB
    609)."""
    return and_(
        Work.project_id == work.project_id,
        Work.debrief_subject == work.debrief_subject,
        Work.debrief_notice_id.is_(None),
        Work.debrief_completes.is_(False),
        Item.done_at.is_not(None),
    )


def of_notice(db: Session, work: Work) -> list[Item]:
    """The work items of the Debrief Notice of the debriefed Work `work`, in
    their order on the timeline: those the notice that carries it carries;
    before one does, `work` and, where it names a subject, every Work that
    waits on that subject's notice (`awaiting_notice`)."""
    if work.debrief_notice_id is not None:
        carried = Work.debrief_notice_id == work.debrief_notice_id
    elif work.debrief_subject is None:
        carried = Work.id == work.id
    else:
        carried = or_(Work.id == work.id, awaiting_notice(work))
    return list(
        db.scalars(
            select(Item)
            .join(Work, Work.id == Item.id)
            .where(Work.project_id == work.project_id, carried)
            .order_by(Item.seq)
        )
    )


def stage_times(db: Session, work_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, int]:
    """The time the stage of each of the debriefed Works `work_ids` took, in
    whole seconds (F26.17; DB 637): the Turns that have ended of the Work and
    of every Work of its Project on its conversation placed before it, a
    hand-back's continuations and its clarification runs, each from its start
    to its end, summed. The time between two Turns counts nothing, nor does a
    Turn still running. Read from the record at each call and stored
    nowhere."""
    if not work_ids:
        return {}
    own, own_item = aliased(AgentSession), aliased(Item)
    part, part_item = aliased(AgentSession), aliased(Item)
    took = {
        work_id: round(seconds)
        for work_id, seconds in db.execute(
            select(
                own.id,
                func.sum(func.extract("epoch", Turn.ended_at - Turn.started_at)),
            )
            .select_from(own)
            .join(own_item, own_item.id == own.id)
            .join(Work, Work.project_id == own_item.project_id)
            .join(part_item, part_item.id == Work.id)
            .join(part, part.id == Work.id)
            .join(Turn, Turn.session_id == part.id)
            .where(
                own.id.in_(list(work_ids)),
                part_item.seq <= own_item.seq,
                or_(part.id == own.id, part.conversation_id == own.conversation_id),
                Turn.ended_at.is_not(None),
            )
            .group_by(own.id)
        )
    }
    return {work_id: took.get(work_id, 0) for work_id in work_ids}
