"""What Pilot's inventory hands the labeller with each conversation (F152.2;
`labeller.md` § What Pilot hands with a conversation): the Sessions of
Pilot's that ran it, with their Holds and Turns, and the Documents they put.

A conversation is one a Session names by its `conversation_id`, the
`session_id` of its main thread's Transcript, whether or not Pilot holds that
Transcript. Every list is read in an order its rows' own columns fix, so that
what is handed of a conversation changes only where its rows do: the
labeller's stamp covers the lists and their order.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from pilot_collection.inventory import (
    HeldConversationSchema,
    HeldDocumentSchema,
    HeldSessionSchema,
    SessionHoldSchema,
    SessionTurnSchema,
)
from sqlalchemy import Result, Row, Select, func, select
from sqlalchemy.orm import Session

from app.models import ClarificationRun, Document, Hold, Item, Project, Turn, Work
from app.models import Session as AgentSession

BRIEF_LENGTH = 400
"""How many characters of a Session's first Turn no person wrote are its
brief."""


def _on_a_conversation[*Columns](
    statement: Select[*Columns], session_id: Any
) -> Select[*Columns]:
    """`statement` over the rows of Sessions that ran a conversation."""
    return statement.join(AgentSession, AgentSession.id == session_id).where(
        AgentSession.conversation_id.is_not(None)
    )


def conversations(db: Session) -> list[HeldConversationSchema]:
    """Every conversation a Session of Pilot's ran, by `session_id`, with
    its Sessions in `created_at` order and the Documents they put in the
    order they were made: four reads, however many there are."""
    brief = (
        select(func.left(Turn.message, BRIEF_LENGTH))
        .where(Turn.session_id == AgentSession.id, Turn.author_user_id.is_(None))
        .order_by(Turn.seq)
        .limit(1)
        .scalar_subquery()
    )
    sessions = db.execute(
        select(
            AgentSession.id,
            AgentSession.conversation_id,
            AgentSession.kind_code,
            AgentSession.created_at,
            brief.label("brief"),
            func.coalesce(Work.repo, Project.repo).label("repo"),
            ClarificationRun.id.is_not(None).label("clarification"),
        )
        .join(Project, Project.id == AgentSession.project_id)
        .outerjoin(Work, Work.id == AgentSession.id)
        .outerjoin(ClarificationRun, ClarificationRun.id == AgentSession.id)
        .where(AgentSession.conversation_id.is_not(None))
        .order_by(
            AgentSession.conversation_id, AgentSession.created_at, AgentSession.id
        )
    ).all()
    holds = _by_session(
        db.execute(
            _on_a_conversation(
                select(Hold.session_id, Hold.kind_code, Hold.started_at, Hold.ended_at),
                Hold.session_id,
            ).order_by(Hold.session_id, Hold.started_at, Hold.id)
        ),
        lambda row: SessionHoldSchema(
            kind=row.kind_code, started_at=row.started_at, ended_at=row.ended_at
        ),
    )
    turns = _by_session(
        db.execute(
            _on_a_conversation(
                select(Turn.session_id, Turn.started_at, Turn.cause_code),
                Turn.session_id,
            ).order_by(Turn.session_id, Turn.seq)
        ),
        lambda row: SessionTurnSchema(started_at=row.started_at, cause=row.cause_code),
    )
    documents: dict[str, list[HeldDocumentSchema]] = defaultdict(list)
    for row in db.execute(
        _on_a_conversation(
            select(
                Document.id,
                Item.created_by_session_id,
                AgentSession.conversation_id,
                Document.source_path,
            ).join(Item, Item.id == Document.id),
            Item.created_by_session_id,
        ).order_by(AgentSession.conversation_id, Document.created_at, Document.id)
    ):
        documents[row.conversation_id].append(
            HeldDocumentSchema(
                id=row.id,
                session=row.created_by_session_id,
                source_path=row.source_path,
            )
        )
    held: dict[str, list[HeldSessionSchema]] = {}
    for row in sessions:
        held.setdefault(row.conversation_id, []).append(
            HeldSessionSchema(
                id=row.id,
                kind=row.kind_code,
                created_at=row.created_at,
                brief=row.brief,
                repo=row.repo,
                clarification=row.clarification,
                holds=holds.get(row.id, []),
                turns=turns.get(row.id, []),
            )
        )
    return [
        HeldConversationSchema(
            session_id=conversation,
            sessions=on_it,
            documents=documents.get(conversation, []),
        )
        for conversation, on_it in held.items()
    ]


def _by_session[Held](
    rows: Result[Any], held: Callable[[Row[Any]], Held]
) -> dict[uuid.UUID, list[Held]]:
    """Each row as `held` makes it, under its Session's id, in the rows'
    order."""
    by_session: dict[uuid.UUID, list[Held]] = defaultdict(list)
    for row in rows:
        by_session[row.session_id].append(held(row))
    return by_session
