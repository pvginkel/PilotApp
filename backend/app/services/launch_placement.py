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

A Launch a Turn started is placed once, and what it was placed under stands.
A Launch a driver started moves only to a Session created later than the one
it stands under, and before its own start, whose step names its Transcript:
its Session is the same whichever Pilot held first, the Launch or that
naming. A step that goes moves none.

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
    """Place each Launch of the conversation's main thread under the Session
    and the Turn that started it, or during which its driver did, where
    Pilot holds them: one a Turn started while it has no Session, one a
    driver started while a Session created later than its own names its
    thread. None while an adopted Project has adopted that thread, which is
    logged. The caller holds the conversation's turn."""
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
    launches = db.scalars(
        select(Launch)
        .join(Transcript, Transcript.id == Launch.transcript_id)
        .where(
            Transcript.session_id == conversation,
            Transcript.agent_id.is_(None),
            *([] if waited else [Launch.session_id.is_(None)]),
        )
    ).all()
    if waited:
        _place_rounds(db, launches, waited)
    else:
        for launch in launches:
            sent = _sent(turns, launch.started_at)
            if sent is not None:
                launch.session_id = sent.session_id
                launch.turn_seq = _in_flight(sent, launch.started_at)
    db.flush()


def _place_rounds(
    db: Session, launches: Sequence[Launch], waited: Sequence[_Run]
) -> None:
    """Each of `launches`, which a driver started, under the Session created
    last before its start among `waited`, in the order they were created,
    where it has no Session or one created before that one."""
    moved: list[tuple[Launch, uuid.UUID]] = []
    for launch in launches:
        created = [run for run in waited if run.created_at <= launch.started_at]
        if not created or created[-1].id == launch.session_id:
            continue
        run = created[-1]
        if launch.session_id is not None:
            under = db.get_one(AgentSession, launch.session_id)
            if (under.created_at, under.id) > (run.created_at, run.id):
                continue
        moved.append((launch, run.id))
    if not moved:
        return
    turns = _turns(db, Turn.session_id.in_(sorted({run for _, run in moved})))
    for launch, run_id in moved:
        sent = _sent(turns, launch.started_at, run_id)
        launch.session_id = run_id
        launch.turn_seq = None if sent is None else _in_flight(sent, launch.started_at)


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


def _in_flight(turn: _Turn, at: datetime) -> int | None:
    """The Turn's `seq` where it had not ended before `at`, none where it
    had."""
    return turn.seq if turn.ended_at is None or at <= turn.ended_at else None
