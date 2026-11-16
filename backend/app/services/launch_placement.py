"""A Launch placed under the Session and the Turn of Pilot's that started it
(DB decision 79 point 7; assertions 537 and 538; F152.4).

A Launch a Turn of Pilot's started continues the Transcript whose
`session_id` is its Session's `conversation_id`. Its Session is the one whose
Turn was sent last before the Launch's start, among the Sessions of that
conversation, and its Turn is that Turn where it was in flight at the
Launch's start. A Launch started after that Turn's end, between two Turns,
has the Session and no Turn; one started before every Turn of the
conversation has neither. A Launch is placed once, and what it was placed
under stands.

The two facts a placement reads arrive in either order, a publication's
Launch and a Session's `conversation_id`, each in a transaction of its own.
Both writers place under the conversation's turn (`conversation_turn`), the
publication's from its start and the Session's in `conversation_named`, so
that the later of the two sees what the earlier committed.

A Launch a driver started under a loop session continues another Transcript,
one no Session's `conversation_id` names, and is not placed here (DB 538).
"""

from sqlalchemy import Integer, cast, func, literal, select
from sqlalchemy.orm import Session

from app.models import Launch, Transcript, Turn
from app.models import Session as AgentSession
from app.services.advisory_turn import turn_key

PUBLICATION_LOCK = 247
"""The first key of a conversation's turn (`advisory_turn`); the second is
drawn from Claude Code's id of its main thread."""


def conversation_turn(db: Session, conversation: str) -> None:
    """Take the turn of the conversation of that id of Claude Code's, held
    until `db`'s transaction ends: the writes of one conversation's
    Transcripts, and of the Session that names it, follow one another."""
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                cast(literal(PUBLICATION_LOCK), Integer),
                cast(literal(turn_key(conversation.encode())), Integer),
            )
        )
    )


def conversation_named(db: Session, conversation: str) -> None:
    """A Session took the conversation's id, written or pending on `db`:
    place the Launches Pilot holds of that conversation, under its turn."""
    conversation_turn(db, conversation)
    place_launches(db, conversation)


def place_launches(db: Session, conversation: str) -> None:
    """Place each Launch of the conversation's main thread that has no
    Session under the Session and the Turn that started it, where Pilot
    holds them. The caller holds the conversation's turn."""
    turns = db.execute(
        select(Turn.session_id, Turn.seq, Turn.started_at, Turn.ended_at)
        .join(AgentSession, AgentSession.id == Turn.session_id)
        .where(AgentSession.conversation_id == conversation)
        .order_by(Turn.started_at, Turn.id)
    ).all()
    if not turns:
        return
    unplaced = db.scalars(
        select(Launch)
        .join(Transcript, Transcript.id == Launch.transcript_id)
        .where(
            Transcript.session_id == conversation,
            Transcript.agent_id.is_(None),
            Launch.session_id.is_(None),
        )
    )
    for launch in unplaced:
        sent = [turn for turn in turns if turn.started_at <= launch.started_at]
        if not sent:
            continue
        last = sent[-1]
        launch.session_id = last.session_id
        if last.ended_at is None or launch.started_at <= last.ended_at:
            launch.turn_seq = last.seq
    db.flush()
