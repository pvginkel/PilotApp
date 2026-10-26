"""A project's chats as a person reads them (F40.3, F43; DB Chat, Chat Read,
decision 13, assertion 158): the list, the definition chat first, each chat's
records read through the records route as any Session's are; and a person's
place in the project's chat, one per person and project, written once they
have seen it to its end, with whether a reply of Pilot's came after it.

A reply is Pilot's text in a chat, the main thread's `assistant` text blocks
`chat.md` shows (`pilot_text`), at the time its record was written. Chat Read
is per project, not per chat, so a rotation keeps it.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.engine.views import ListedChat, pilot_text, project_chats
from app.exceptions import RecordNotFoundException
from app.models import ChatRead, Project, User
from app.models.reference import RecordKind
from app.services.session_record_service import read_records

_RECORD_PAGE = 32
"""The `assistant` records one read of a chat's takes, newest first."""


@dataclass(frozen=True)
class ReadPlace:
    """A person's place in a project's chat: when they last saw it to its
    end, none before they first did, and whether a reply came after it."""

    read_at: datetime | None
    unread: bool


@dataclass(frozen=True)
class ChatList:
    """A project's chats in their order, and the reader's place in them."""

    chats: list[ListedChat]
    place: ReadPlace


class ChatReadService:
    """Reads a project's chats and writes a person's place in them, in the
    caller's transaction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def chats(self, project_id: uuid.UUID, reader: User | None) -> ChatList:
        """The project's chats, the definition chat first where one exists,
        then the project's chats in the order they opened; and `reader`'s
        place in them, none for a caller who is not a person yet.

        Raises:
            RecordNotFoundException: No project has the id
        """
        self._require(project_id)
        read_at = None
        if reader is not None:
            read_at = self.db.scalar(
                select(ChatRead.read_at).where(
                    ChatRead.user_id == reader.id, ChatRead.project_id == project_id
                )
            )
        return ChatList(
            project_chats(self.db, project_id), self._place(project_id, read_at)
        )

    def read(self, project_id: uuid.UUID, person: User) -> ReadPlace:
        """`person` saw the project's chat to its end now: their Chat Read
        written, the one of the person and the project, overwritten.

        Raises:
            RecordNotFoundException: No project has the id
        """
        self._require(project_id)
        read_at = self.db.scalars(
            insert(ChatRead)
            .values(user_id=person.id, project_id=project_id, read_at=func.now())
            .on_conflict_do_update(
                index_elements=[ChatRead.user_id, ChatRead.project_id],
                set_={"read_at": func.now()},
            )
            .returning(ChatRead.read_at)
        ).one()
        return self._place(project_id, read_at)

    def _place(self, project_id: uuid.UUID, read_at: datetime | None) -> ReadPlace:
        replied = self._last_reply_at(project_id)
        return ReadPlace(
            read_at,
            replied is not None and (read_at is None or replied > read_at),
        )

    def _last_reply_at(self, project_id: uuid.UUID) -> datetime | None:
        """When Pilot's latest reply in the project's chats was written: the
        newest chat's latest, or the one before's while it has none; None
        before the first."""
        for listed in reversed(project_chats(self.db, project_id)):
            before = None
            while True:
                page = read_records(
                    self.db,
                    listed.chat.id,
                    before=before,
                    kind=RecordKind.CLAUDE,
                    payload_type="assistant",
                    limit=_RECORD_PAGE,
                    newest_first=True,
                )
                for stored in page:
                    if pilot_text(stored.record.payload):
                        return stored.record.at
                if len(page) < _RECORD_PAGE:
                    break
                before = page[-1].record.seq
        return None

    def _require(self, project_id: uuid.UUID) -> None:
        if self.db.get(Project, project_id) is None:
            raise RecordNotFoundException("Project", str(project_id))
