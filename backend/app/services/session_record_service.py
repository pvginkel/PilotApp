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

from prometheus_client import Counter
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
    from app.engine.views import ViewService
    from app.services.session_stream_service import SessionStreamService

STREAM_ENDED_STATES = (SessionState.ENDED, SessionState.FAILED)
"""The states in which a Session's stream has ended after its last record
(§11.2)."""

RECORDS_WRITTEN_TOTAL = Counter(
    "pilot_records_written_total",
    "Session Records written, by kind",
    ["kind"],
)

# A backwards search reads the last record alone first, then pages of this.
_SEARCH_PAGE = 32


@dataclass(frozen=True)
class StoredRecord:
    """A Session Record as the one read function reads it."""

    record: SessionRecord
    turn: int | None
    """The number of the record's Turn."""
    author: str | None
    """A `send`'s author, by handle."""
    words: str | None
    """A `send`'s words, its Turn's (DB assertion 219)."""


@dataclass(frozen=True)
class RecordPage:
    records: list[StoredRecord]
    ended: bool


@dataclass(frozen=True)
class StreamPosition:
    """Where a Session's records stand in a controller session's raw file."""

    controller_session: str
    raw_offset: int


def read_records(
    db: Session,
    session_id: uuid.UUID,
    *,
    after: int = 0,
    before: int | None = None,
    turn_id: int | None = None,
    kind: RecordKind | None = None,
    payload_type: str | None = None,
    limit: int,
    newest_first: bool = False,
) -> list[StoredRecord]:
    """The Session's records after the `seq` `after`, and before `before` when
    given, of the Turn `turn_id` when given, of `kind` when given, whose
    payload's `type` is `payload_type` when given, at most `limit`, in order,
    or newest first."""
    is_send = SessionRecord.kind_code == RecordKind.SEND
    bounds = [SessionRecord.session_id == session_id, SessionRecord.seq > after]
    if before is not None:
        bounds.append(SessionRecord.seq < before)
    if turn_id is not None:
        bounds.append(SessionRecord.turn_id == turn_id)
    if kind is not None:
        bounds.append(SessionRecord.kind_code == kind)
    if payload_type is not None:
        bounds.append(SessionRecord.payload["type"].astext == payload_type)
    statement = (
        select(
            SessionRecord,
            Turn.seq,
            case((is_send, User.handle)),
            case((is_send, Turn.words)),
        )
        .outerjoin(Turn, Turn.id == SessionRecord.turn_id)
        .outerjoin(User, User.id == Turn.author_user_id)
        .where(*bounds)
        .order_by(SessionRecord.seq.desc() if newest_first else SessionRecord.seq)
        .limit(limit)
    )
    return [
        StoredRecord(record, turn, author, words)
        for record, turn, author, words in db.execute(statement).tuples()
    ]


def last_record(db: Session, session_id: uuid.UUID) -> StoredRecord | None:
    """The Session's last record; None before its first."""
    return next(iter(read_records(db, session_id, limit=1, newest_first=True)), None)


def stream_position(db: Session, session_id: uuid.UUID) -> StreamPosition | None:
    """The controller session and raw offset of the Session's last `claude` or
    `result` record; None before its first."""
    before, limit = None, 1
    while True:
        page = read_records(
            db, session_id, before=before, limit=limit, newest_first=True
        )
        for stored in page:
            record = stored.record
            if record.raw_offset is not None and record.controller_session is not None:
                return StreamPosition(record.controller_session, record.raw_offset)
        if len(page) < limit:
            return None
        before, limit = page[-1].record.seq, _SEARCH_PAGE


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
                base | {"author": stored.author, "message": stored.words}
            )


class SessionRecordService:
    """Writes a Session's records and reads its pages, in the caller's
    transaction. A record a chat's `chat.md` shows moves the file's hash
    (`ViewService.recorded`)."""

    def __init__(
        self,
        db: Session,
        session_streams: "SessionStreamService",
        view_service: "ViewService",
    ) -> None:
        self.db = db
        self._streams = session_streams
        self._views = view_service

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
        session = self.lock_session(session_id)
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
        RECORDS_WRITTEN_TOTAL.labels(kind=kind.value).inc()
        after_commit(self._streams.waker(session_id))
        self._views.recorded(session, kind, payload)
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
