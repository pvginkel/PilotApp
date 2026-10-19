"""A Session's records: the one read function and the writer (design 2 §10,
§11.4).

`read_records` is the only query of `session_records` in the server; a test
pins it. The writer numbers a record under the Session row's lock, so a
Session's records run from 1 without a gap in the order written (DB assertion
217), and wakes the Session's hub once the record is committed.
"""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.exceptions import RecordNotFoundException
from app.models import Session as AgentSession
from app.models import SessionRecord, Turn, User
from app.models.reference import RecordKind, SessionState
from app.schemas.session_schema import (
    ClaudeRecordSchema,
    ResultRecordSchema,
    SendRecordSchema,
    ServerRecordSchema,
    SessionRecordSchema,
)
from app.utils.after_commit import after_commit

if TYPE_CHECKING:
    from app.services.session_stream_service import SessionStreamService

STREAM_ENDED_STATES = (SessionState.ENDED, SessionState.FAILED)
"""The states in which a Session's stream has ended after its last record
(§11.2)."""


@dataclass(frozen=True)
class StoredRecord:
    """A Session Record as the one read function reads it."""

    record: SessionRecord
    turn: int | None
    """The number of the record's Turn."""
    author: str | None
    """A `send`'s author, by handle."""
    message: str | None
    """A `send`'s words."""


@dataclass(frozen=True)
class RecordPage:
    records: list[StoredRecord]
    ended: bool


def read_records(
    db: Session,
    session_id: uuid.UUID,
    *,
    after: int = 0,
    limit: int,
    newest_first: bool = False,
) -> list[StoredRecord]:
    """The Session's records after the `seq` `after`, at most `limit`, in order,
    or newest first."""
    is_send = SessionRecord.kind_code == RecordKind.SEND
    statement = (
        select(
            SessionRecord,
            Turn.seq,
            case((is_send, User.handle)),
            case((is_send, Turn.message)),
        )
        .outerjoin(Turn, Turn.id == SessionRecord.turn_id)
        .outerjoin(User, User.id == Turn.author_user_id)
        .where(SessionRecord.session_id == session_id, SessionRecord.seq > after)
        .order_by(SessionRecord.seq.desc() if newest_first else SessionRecord.seq)
        .limit(limit)
    )
    return [
        StoredRecord(record, turn, author, message)
        for record, turn, author, message in db.execute(statement).tuples()
    ]


def last_record(db: Session, session_id: uuid.UUID) -> StoredRecord | None:
    """The Session's last record; None before its first."""
    return next(iter(read_records(db, session_id, limit=1, newest_first=True)), None)


def to_record_schema(stored: StoredRecord) -> SessionRecordSchema:
    """The record in its wire shape (§11.2)."""
    record = stored.record
    base: dict[str, Any] = {
        "seq": record.seq,
        "at": record.at,
        "turn": stored.turn,
        "kind": record.kind_code.value,
    }
    match record.kind_code:
        case RecordKind.CLAUDE:
            return ClaudeRecordSchema.model_validate(
                base | {"payload": record.payload, "raw_offset": record.raw_offset}
            )
        case RecordKind.RESULT:
            return ResultRecordSchema.model_validate(base | {"payload": record.payload})
        case RecordKind.SERVER:
            return ServerRecordSchema.model_validate(base | {"payload": record.payload})
        case RecordKind.SEND:
            return SendRecordSchema.model_validate(
                base | {"author": stored.author, "message": stored.message}
            )


class SessionRecordService:
    """Writes a Session's records and reads its pages, in the caller's
    transaction."""

    def __init__(self, db: Session, session_streams: "SessionStreamService") -> None:
        self.db = db
        self._streams = session_streams

    def require_session(self, session_id: uuid.UUID) -> AgentSession:
        """The Session.

        Raises:
            RecordNotFoundException: No Session has the id
        """
        session = self.db.get(AgentSession, session_id)
        if session is None:
            raise RecordNotFoundException("Session", str(session_id))
        return session

    def lock_session(self, session_id: uuid.UUID) -> AgentSession:
        """The Session row, `SELECT … FOR UPDATE`: locked, and read afresh, until
        the transaction ends.

        Raises:
            RecordNotFoundException: No Session has the id
        """
        session = self.db.get(
            AgentSession, session_id, with_for_update=True, populate_existing=True
        )
        if session is None:
            raise RecordNotFoundException("Session", str(session_id))
        return session

    def append(
        self,
        session_id: uuid.UUID,
        kind: RecordKind,
        *,
        payload: Any = None,
        turn_id: int | None = None,
        raw_offset: int | None = None,
        controller_session: str | None = None,
    ) -> SessionRecord:
        """Write the Session's next record, numbered under its row's lock.

        The lock is held until the transaction ends, so the caller commits one
        record per transaction. The Session's hub is woken once the
        transaction has committed; a rollback wakes nothing.

        Raises:
            RecordNotFoundException: No Session has the id
        """
        self.lock_session(session_id)
        last = last_record(self.db, session_id)
        record = SessionRecord(
            session_id=session_id,
            seq=(0 if last is None else last.record.seq) + 1,
            kind_code=kind,
            payload=payload,
            turn_id=turn_id,
            raw_offset=raw_offset,
            controller_session=controller_session,
        )
        self.db.add(record)
        self.db.flush()
        after_commit(self._streams.waker(session_id))
        return record

    def read_page(self, session_id: uuid.UUID, *, after: int, limit: int) -> RecordPage:
        """The Session's records after `after`, at most `limit`, and whether the
        page ends its stream.

        Raises:
            RecordNotFoundException: No Session has the id
        """
        # The state is read before the records: a stream that has ended has
        # every record committed before that.
        state = self.db.scalar(
            select(AgentSession.state_code).where(AgentSession.id == session_id)
        )
        if state is None:
            raise RecordNotFoundException("Session", str(session_id))
        records = read_records(self.db, session_id, after=after, limit=limit + 1)
        return RecordPage(
            records=records[:limit],
            ended=state in STREAM_ENDED_STATES and len(records) <= limit,
        )
