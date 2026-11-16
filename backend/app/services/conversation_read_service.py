"""A calling session's conversations as their caller reads them (F150.10,
F150.11; DB Conversation, assertion 337): the one a call names, and the list
of those its environment opened.

A Conversation answers to its opener alone: the User its first Turn's author
is, calling from the Environment it was opened from. A call about it from any
other User or Environment, one that names no environment among them, is
answered as for an id that never was, and lists none of it.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.exceptions import RecordNotFoundException
from app.models import Conversation, Turn, User
from app.models import Session as AgentSession
from app.services.conversation_service import in_flight


@dataclass(frozen=True)
class ListedConversation:
    """A Conversation, when it opened, its Session's creation, the count of
    its Turns, and whether one is in flight, when it takes no message."""

    conversation: Conversation
    opened_at: datetime
    turns: int
    in_flight: bool


class ConversationReadService:
    """Reads a caller's conversations, in the caller's transaction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def owned(
        self, conversation_id: uuid.UUID, caller: User, environment_id: str | None
    ) -> ListedConversation:
        """The Conversation, for `caller` calling from the environment
        `environment_id`, none where the call named none.

        Raises:
            RecordNotFoundException: No Conversation has the id, or another
                User or Environment opened it
        """
        if environment_id is not None:
            row = self.db.execute(
                _opened_by(caller, environment_id).where(
                    Conversation.id == conversation_id
                )
            ).one_or_none()
            if row is not None:
                return _listed(*row)
        raise RecordNotFoundException("Conversation", str(conversation_id))

    def opened(
        self,
        caller: User,
        environment_id: str | None,
        project_id: uuid.UUID | None = None,
    ) -> list[ListedConversation]:
        """The Conversations `caller` opened from the environment
        `environment_id`, open and closed, in the order they opened, whatever
        session there opened each; of the project `project_id` alone where
        one is given. None for a call that named no environment."""
        if environment_id is None:
            return []
        opened = _opened_by(caller, environment_id)
        if project_id is not None:
            opened = opened.where(Conversation.project_id == project_id)
        return [
            _listed(conversation, session)
            for conversation, session in self.db.execute(
                opened.order_by(AgentSession.created_at, Conversation.id)
            )
        ]


def _opened_by(caller: User, environment_id: str) -> Select[Conversation, AgentSession]:
    """The Conversations `caller` opened from the environment, each with its
    Session, read afresh."""
    return (
        select(Conversation, AgentSession)
        .join(AgentSession, AgentSession.id == Conversation.id)
        .join(Turn, (Turn.session_id == Conversation.id) & (Turn.seq == 1))
        .where(
            Turn.author_user_id == caller.id,
            Conversation.caller_environment_id == environment_id,
        )
        .execution_options(populate_existing=True)
    )


def _listed(conversation: Conversation, session: AgentSession) -> ListedConversation:
    return ListedConversation(
        conversation, session.created_at, session.turns, in_flight(session)
    )
