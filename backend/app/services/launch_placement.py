"""A Launch placed under the Session and the Turn of Pilot's that started it
(DB decision 79 point 7; assertions 537 and 538; F152.4, F152.9).

A Launch a Turn of Pilot's started continues the Transcript whose
`session_id` is its Session's `conversation_id`. Its Session is the one whose
Turn was sent last before the Launch's start, among the Sessions of that
conversation, and its Turn is that Turn where it was in flight at the
Launch's start. A Launch started after that Turn's end, between two Turns,
has the Session and no Turn; one started before every Turn of the
conversation has neither.

A Launch a driver started under a loop session continues another Transcript,
one no Session's `conversation_id` names and a step of the Session that
waited on its loop does (`StepTranscript`). Its Session is the one created
last before the Launch's start, among the Sessions whose steps name the
Transcript: a continuation's list names it again, and the round stays on the
work item that was running when its process started. Its Turn is that
Session's Turn in flight at the Launch's start, none between two of them. A
Launch started before every such Session was created has neither.

A Launch is placed once, and what it was placed under stands: a step that
goes, or a later Session that names its Transcript, moves none.

A Transcript an adopted Project has adopted has no Launch run by a Session
(DB 539): where a Session's `conversation_id` or a step names one, its
Launches stay unplaced for as long as it is adopted, and the server logs it.
The other way round, a group named for a Transcript a Session ran, is the
publication's to refuse.

The two facts a placement reads arrive in either order, a publication's
Launch and the naming of its conversation, a Session's `conversation_id` or
a step's Step Transcript, each in a transaction of its own. Each writer
places under the conversation's turn (`conversation_turn`), the
publication's from its start and the naming's in `conversation_named`, so
that the later of the two sees what the earlier committed.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, Integer, Row, cast, func, literal, select
from sqlalchemy.orm import Session

from app.models import Launch, StepTranscript, Transcript, Turn
from app.models import Session as AgentSession
from app.services.advisory_turn import turn_key

logger = logging.getLogger(__name__)

type _Turn = Row[uuid.UUID, int, datetime, datetime | None]
"""A Turn as a placement reads it: its Session's id, its `seq`, and when it
was sent and ended."""

type _Run = Row[uuid.UUID, datetime]
"""A Session whose step names a conversation: its id and when it was
created."""

PUBLICATION_LOCK = 247
"""The first key of a conversation's turn (`advisory_turn`); the second is
drawn from Claude Code's id of its main thread."""


def conversation_turn(db: Session, conversation: str) -> None:
    """Take the turn of the conversation of that id of Claude Code's, held
    until `db`'s transaction ends: the writes of one conversation's
    Transcripts, and of the Session and the steps that name it, follow one
    another."""
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                cast(literal(PUBLICATION_LOCK), Integer),
                cast(literal(turn_key(conversation.encode())), Integer),
            )
        )
    )


def conversation_named(db: Session, conversation: str) -> None:
    """A Session took the conversation's id, or a step of one named it,
    written or pending on `db`: place the Launches Pilot holds of that
    conversation, under its turn."""
    conversation_turn(db, conversation)
    place_launches(db, conversation)


def place_launches(db: Session, conversation: str) -> None:
    """Place each Launch of the conversation's main thread that has no
    Session under the Session and the Turn that started it, or during which
    its driver did, where Pilot holds them; none while an adopted Project
    has adopted that thread, which is logged. The caller holds the
    conversation's turn."""
    turns = _turns(db, AgentSession.conversation_id == conversation)
    waited: Sequence[_Run] = []
    if not turns:
        waited = db.execute(
            select(AgentSession.id, AgentSession.created_at)
            .where(
                AgentSession.id.in_(
                    select(StepTranscript.work_id).where(
                        StepTranscript.session_id == conversation
                    )
                )
            )
            .order_by(AgentSession.created_at, AgentSession.id)
        ).all()
        if not waited:
            return
    adopted_by = db.scalar(
        select(Transcript.adopted_project_id).where(
            Transcript.session_id == conversation, Transcript.agent_id.is_(None)
        )
    )
    if adopted_by is not None:
        logger.warning(
            "Transcript %s is adopted by project %s, and %s of Pilot's names it:"
            " its launches stay off that Session",
            conversation,
            adopted_by,
            "a Session" if turns else "a step of a Session",
        )
        return
    unplaced = db.scalars(
        select(Launch)
        .join(Transcript, Transcript.id == Launch.transcript_id)
        .where(
            Transcript.session_id == conversation,
            Transcript.agent_id.is_(None),
            Launch.session_id.is_(None),
        )
    ).all()
    if not unplaced:
        return
    if waited:
        turns = _turns(db, Turn.session_id.in_([run.id for run in waited]))
    for launch in unplaced:
        if waited:
            created = [run for run in waited if run.created_at <= launch.started_at]
            if not created:
                continue
            launch.session_id = created[-1].id
            sent = _sent(turns, launch.started_at, created[-1].id)
        else:
            sent = _sent(turns, launch.started_at)
            if sent is None:
                continue
            launch.session_id = sent.session_id
        if sent is not None and (
            sent.ended_at is None or launch.started_at <= sent.ended_at
        ):
            launch.turn_seq = sent.seq
    db.flush()


def _turns(db: Session, of: ColumnElement[bool]) -> Sequence[_Turn]:
    """The Turns of the Sessions `of` holds for, in the order they were
    sent."""
    return db.execute(
        select(Turn.session_id, Turn.seq, Turn.started_at, Turn.ended_at)
        .join(AgentSession, AgentSession.id == Turn.session_id)
        .where(of)
        .order_by(Turn.started_at, Turn.id)
    ).all()


def _sent(
    turns: Sequence[_Turn], at: datetime, session_id: uuid.UUID | None = None
) -> _Turn | None:
    """The Turn sent last before `at` among `turns`, which are in the order
    they were sent: of the Session of that id, of any where none is given."""
    sent = [
        turn
        for turn in turns
        if turn.started_at <= at and session_id in (None, turn.session_id)
    ]
    return sent[-1] if sent else None
