"""A project's chats written as the server writes them, for the tests that read
them: the Chat and its Session, then its records through the one writer, a
person's message as its Turn and `send`, Pilot's lines as the relay records
them, and an effect as a tool's call places it."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session as DbSession

from app import models
from app.models import Chat, SessionRecord, Turn, User
from app.models.reference import ChatKind, CloseCause, RecordKind, SessionState
from app.services.session_record_service import SessionRecordService


def open_chat(
    db: DbSession,
    project: models.Project,
    *,
    kind: ChatKind = ChatKind.PROJECT,
    opened_at: datetime | None = None,
) -> models.Session:
    """A chat of `project`, its Session in the store, idle, opened at
    `opened_at`, the database's now by default."""
    run = models.Session(
        project_id=project.id,
        kind_code="chat",
        cwd="/work/PilotProjects",
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.IDLE,
    )
    if opened_at is not None:
        run.created_at = opened_at
    db.add(run)
    db.flush()
    db.add(
        Chat(id=run.id, project_id=project.id, session_kind_code="chat", kind_code=kind)
    )
    db.flush()
    return run


def close_chat(
    db: DbSession, run: models.Session, at: datetime, cause: CloseCause
) -> None:
    chat = db.get_one(Chat, run.id)
    chat.closed_at, chat.close_cause_code = at, cause
    db.flush()


class ChatWriter:
    """Writes one chat's records, each through the one writer, as the server
    writes them: a Turn in flight from each message on."""

    def __init__(
        self, db: DbSession, records: SessionRecordService, run: models.Session
    ) -> None:
        self.db = db
        self.records = records
        self.run = run
        self.turn: Turn | None = None
        self._offset = 0

    def message(self, person: User, words: str) -> SessionRecord:
        """`person`'s message: a Turn of theirs, the brief before the words on
        the first, and its `send`."""
        self.turn = self._turn(person, words)
        return self.records.append(self.run.id, RecordKind.SEND, turn_id=self.turn.id)

    def server_turn(self, message: str) -> None:
        """A Turn of the server's, no author and no `send`."""
        self.turn = self._turn(None, message)

    def text(self, *texts: str, parent: str | None = None) -> SessionRecord:
        """An `assistant` line of text blocks; a sub-agent's under `parent`."""
        return self.assistant(
            [{"type": "text", "text": text} for text in texts], parent=parent
        )

    def call(self, tool_use_id: str, name: str = "mcp__pilot__answer") -> SessionRecord:
        """An `assistant` line of one tool call."""
        return self.assistant(
            [{"type": "tool_use", "id": tool_use_id, "name": name, "input": {}}]
        )

    def assistant(
        self, content: list[dict[str, Any]], *, parent: str | None = None
    ) -> SessionRecord:
        return self.line(
            {
                "type": "assistant",
                "parent_tool_use_id": parent,
                "message": {"role": "assistant", "content": content},
            }
        )

    def line(self, payload: Any) -> SessionRecord:
        """A line of the raw stream, in the Turn in flight."""
        assert self.turn is not None
        self._offset += 100
        return self.records.append(
            self.run.id,
            RecordKind.CLAUDE,
            payload=payload,
            turn_id=self.turn.id,
            raw_offset=self._offset,
            controller_session="session-1",
        )

    def effect(self, tool_use_id: str | None, verb: str, label: str) -> SessionRecord:
        """A tool call's effect line, as its call places it; no Effect row,
        which `chat.md` does not read."""
        assert self.turn is not None
        return self.records.append(
            self.run.id,
            RecordKind.SERVER,
            payload={
                "type": "effect",
                "toolUseId": tool_use_id,
                "effect": {"verb": verb, "label": label},
            },
            turn_id=self.turn.id,
        )

    def _turn(self, author: User | None, words: str) -> Turn:
        if self.turn is not None:
            self.turn.ended_at = self.turn.started_at
        seq = 1 if self.turn is None else self.turn.seq + 1
        turn = Turn(
            session_id=self.run.id,
            seq=seq,
            author_user_id=None if author is None else author.id,
            message=f"/chat\n\n{words}" if author is not None and seq == 1 else words,
            words=None if author is None else words,
            started_at=datetime.now(UTC),
        )
        self.db.add(turn)
        self.db.flush()
        return turn
