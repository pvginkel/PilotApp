"""What Pilot is working on (F13.7, F21.6, F28.9, F52.3, F94.5; DB 294 to
296), read from the rows at every read and never stored: whether a Work is in
flight, whether a Block is held and by which run, and whether a registered
document is Pilot's, with what Pilot does on it, the work item to link and
whether its line pulses. `waiting()`, and through it the badge, the project's
status and the standing notification, reads it from here, and so does every
other reader of what Pilot does on an item.

A hold lasts through the run (the rulings of slice 036's planning, over DB 262
and 295): the Work a Block's standing Claim Assignment or Research Assignment
names and the Works on its conversation (DB 183), the clarification runs
among them, each with the job after its turn, a Retry of it included. The run
is done with the Block once the job after the turn of one of its Works, a
clarification run's never, has ended and that turn registered no document
with a Block in it: it asked the person nothing. It hands the Block back at
once while one of its Works, or the latest job after one of their turns,
stands failed or stopped otherwise than by the server's own resumable stops;
a Resume or a Retry holds it again. Until then the Block is held, whether
something of the run is in flight or the run waits on the person's answer to
a document it registered.
"""

import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, literal, or_, select
from sqlalchemy.orm import QueryableAttribute, Session, aliased

from app.engine import claims, researches
from app.engine.claims import claimed
from app.engine.documents import awaiting_read
from app.engine.record import TURN_ENDED
from app.models import (
    Block,
    ClarificationRun,
    Document,
    Item,
    Turn,
    Work,
    WriterQuestion,
)
from app.models import Session as AgentSession
from app.models.reference import SessionState, WorkTrigger
from app.services.start_gate import WORK_KIND
from app.services.store_update_service import stopped_for_unlifted

_GOING = (
    SessionState.HELD,
    SessionState.STARTING,
    SessionState.RUNNING,
    SessionState.IDLE,
)
"""The states of a Session the server goes on with by itself while its Item
is open (DB 294)."""

_PULSING = (SessionState.HELD, SessionState.STARTING, SessionState.RUNNING)
"""The states in which the line of what Pilot does pulses: queued or held,
starting, or running (F13.7)."""

_DOWN = (SessionState.FAILED, SessionState.STOPPED)
"""The states of a Work that hand its run's Blocks back unless it is in
flight all the same: owed its nudge, or the store update's retry."""


class Doing(StrEnum):
    """What Pilot does on an item that is Pilot's (DB 296)."""

    AWAITING_RUN = "awaiting_run"
    """Its read awaited at the end of the run that registered it."""
    PRE_RULING = "pre_ruling"
    """Its pass in flight, or the pass after the writer's reply."""
    ASKING_WRITER = "asking_writer"
    """Its pass asked the writer, the clarification run in flight."""
    DOING = "doing"
    """Its every open Block held, a claim's run going on."""
    RESEARCHING = "researching"
    """Its every open Block held, a research's run going on."""
    WAITING_ON_ANSWER = "waiting_on_answer"
    """Its every open Block held, the run holding them waiting on the
    person's answer to a document it registered."""


@dataclass(frozen=True)
class Hold:
    """A held Block (DB 295, held through the run)."""

    document_id: uuid.UUID
    work_id: uuid.UUID
    """The work item its standing naming names (DB 260, 292)."""
    research: bool
    """A research's naming, else a claim's."""
    going_on: bool
    """Something of its run in flight; else the run waits on the person."""
    pulse: bool
    """A Session of its run, a Work's or a job's after a turn, queued or
    held, starting or running."""
    asked_in: uuid.UUID | None
    """While the run waits on the person: the open document it registered
    that they answer, the first on the timeline; else none."""


@dataclass(frozen=True)
class Holds:
    """The named Blocks of some documents as the reading reads them."""

    held: Mapping[int, Hold]
    """The held Blocks by their ids, each document's in its order."""
    undone: frozenset[int]
    """The claimed actions whose standing Claim Assignment's run handed
    them back to the person, their `done` unwritten (DB 262; F21.6)."""


@dataclass(frozen=True)
class PilotsWork:
    """What Pilot does on an item that is Pilot's, the work item its line
    links, and whether that line pulses (F13.7)."""

    doing: Doing
    work_id: uuid.UUID | None
    """The registering work item, the pass's job, or the work item the
    standing naming of its first held Block names; none while its writer is
    asked, whose words stand still."""
    pulse: bool
    asked_in: uuid.UUID | None
    """While the run holding its Blocks waits on the person: the run's open
    document; else none."""


def in_flight(
    item: type[Item], session: type[AgentSession], work: type[Work]
) -> ColumnElement[bool]:
    """DB 294 on one Work's rows, aliases of one id: its Item open, and its
    Session `held`, `starting`, `running` or `idle`, or owed its nudge (DB
    232, 269; the quota wall's `failed` among them), or a job the Store
    Update not lifted yet stopped, which its lift retries (DB 281)."""
    return and_(
        item.done_at.is_(None),
        or_(
            session.state_code.in_(_GOING),
            session.nudge_owed_at.is_not(None),
            and_(
                session.state_code == SessionState.STOPPED,
                work.retried_by_id.is_(None),
                stopped_for_unlifted(session),
            ),
        ),
    )


@dataclass(frozen=True)
class _Rows:
    """One Work's rows, aliased: its Item, its Session and its Work."""

    item: type[Item]
    session: type[AgentSession]
    work: type[Work]

    @staticmethod
    def new() -> "_Rows":
        return _Rows(aliased(Item), aliased(AgentSession), aliased(Work))

    def select(self, *where: ColumnElement[bool]) -> Select[uuid.UUID]:
        """The Works' ids `where` selects, joined to their Items and
        Sessions, every other FROM correlated to an enclosing select at any
        depth."""
        return (
            select(self.work.id)
            .join(self.item, self.item.id == self.work.id)
            .join(self.session, self.session.id == self.work.id)
            .where(*where)
            .correlate_except(self.work, self.item, self.session)
        )

    def in_flight(self) -> ColumnElement[bool]:
        return in_flight(self.item, self.session, self.work)

    def after(self, run: Select[uuid.UUID]) -> ColumnElement[bool]:
        """These rows a job after the turn of a Work of `run`, a Retry of it
        included: the trigger the Retry keeps."""
        return and_(
            self.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED,
            self.work.trigger_item_id.in_(run),
        )


def run_of(work_id: ColumnElement[uuid.UUID]) -> Select[uuid.UUID]:
    """The Works of the run the Work `work_id` begins: it and every worker's
    Work on its conversation (DB 183), its continuations and its
    clarification runs."""
    named = aliased(AgentSession)
    each = _Rows.new()
    conversation = (
        select(named.conversation_id)
        .where(named.id == work_id)
        .correlate_except(named)
        .scalar_subquery()
    )
    return each.select(
        each.session.kind_code == WORK_KIND,
        or_(each.work.id == work_id, each.session.conversation_id == conversation),
    )


def going_on(work_id: ColumnElement[uuid.UUID]) -> ColumnElement[bool]:
    """Whether something of the run `work_id` begins is in flight: one of its
    Works, the job after one of their turns, or a document one of them
    registered awaiting its read, the job after its turn placed once it is
    read."""
    run = run_of(work_id)
    each, job = _Rows.new(), _Rows.new()
    document = aliased(Document)
    registered = aliased(Item)
    return or_(
        each.select(each.work.id.in_(run), each.in_flight()).exists(),
        job.select(job.after(run), job.in_flight()).exists(),
        select(document.id)
        .join(registered, registered.id == document.id)
        .where(
            registered.created_by_session_id.in_(run),
            awaiting_read(registered, document),
        )
        .correlate_except(document, registered)
        .exists(),
    )


def pulsing(work_id: ColumnElement[uuid.UUID]) -> ColumnElement[bool]:
    """Whether a Session of the run `work_id` begins, a Work's or a job's
    after one of their turns, is queued or held, starting or running."""
    run = run_of(work_id)
    each, job = _Rows.new(), _Rows.new()
    return or_(
        each.select(
            each.work.id.in_(run), each.session.state_code.in_(_PULSING)
        ).exists(),
        job.select(job.after(run), job.session.state_code.in_(_PULSING)).exists(),
    )


def handed_back(work_id: ColumnElement[uuid.UUID]) -> ColumnElement[bool]:
    """Whether the run `work_id` begins hands its Blocks back at once: one of
    its Works, or the latest job after one of their turns, stands failed or
    stopped and is not in flight — a person's Stop, the take-over's, an
    interrupted turn, a failure (DB 294) — for as long as it stands so."""
    run = run_of(work_id)
    each, job = _Rows.new(), _Rows.new()
    return or_(
        each.select(
            each.work.id.in_(run),
            each.session.state_code.in_(_DOWN),
            ~each.in_flight(),
        ).exists(),
        job.select(
            job.after(run),
            job.work.retried_by_id.is_(None),
            job.session.state_code.in_(_DOWN),
            ~job.in_flight(),
        ).exists(),
    )


def done_with(work_id: ColumnElement[uuid.UUID]) -> ColumnElement[bool]:
    """Whether the run `work_id` begins is done with its Blocks: the latest
    job after the turn of one of its Works, a clarification run's never, has
    ended, and that turn asked the person nothing, registering no document
    with a Block in it."""
    each, job = _Rows.new(), _Rows.new()
    clarification = aliased(ClarificationRun)
    asked = aliased(Block)
    registered = aliased(Item)
    return each.select(
        each.work.id.in_(run_of(work_id)),
        each.item.done_cause_code == TURN_ENDED,
        ~select(clarification.id)
        .where(clarification.id == each.work.id)
        .correlate_except(clarification)
        .exists(),
        job.select(
            job.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED,
            job.work.trigger_item_id == each.work.id,
            job.work.retried_by_id.is_(None),
            job.item.done_at.is_not(None),
        ).exists(),
        ~select(asked.id)
        .join(registered, registered.id == asked.document_id)
        .where(registered.created_by_session_id == each.work.id)
        .correlate_except(asked, registered)
        .exists(),
    ).exists()


def holds_its_blocks(work_id: ColumnElement[uuid.UUID]) -> ColumnElement[bool]:
    """Whether the run `work_id` begins holds the Blocks the work item
    `work_id` is named for: it has neither handed them back nor is done with
    them."""
    return and_(~handed_back(work_id), ~done_with(work_id))


def _asked_in(work_id: ColumnElement[uuid.UUID]) -> ColumnElement[uuid.UUID]:
    """The first open registered document of the run `work_id` begins on the
    timeline: while the run holds a Block with nothing of it in flight, the
    one the person answers."""
    document = aliased(Document)
    registered = aliased(Item)
    return (
        select(registered.id)
        .join(document, document.id == registered.id)
        .where(
            registered.created_by_session_id.in_(run_of(work_id)),
            registered.done_at.is_(None),
            document.source_path.is_not(None),
        )
        .order_by(registered.seq)
        .limit(1)
        .correlate_except(registered, document)
        .scalar_subquery()
    )


def _researchable() -> ColumnElement[bool]:
    """A Block with neither an answer, a claim included, nor a `done`: one a
    standing research holds (DB 293)."""
    return and_(Block.answer.is_(None), Block.done_at.is_(None))


def held() -> ColumnElement[bool]:
    """Whether a Block is held, as a query's condition on it, true or false
    and never null, so that its negation holds too: a claimed action whose
    standing Claim Assignment's run holds it, or one with neither an answer
    nor a `done` whose standing Research Assignment's run does (DB 295, held
    through the run)."""
    claim = claims.standing().subquery()
    research = researches.standing().subquery()
    return or_(
        select(claim.c.work_id)
        .where(
            claim.c.block_id == Block.id,
            claimed(),
            holds_its_blocks(claim.c.work_id),
        )
        .correlate_except(claim)
        .exists(),
        select(research.c.work_id)
        .where(
            research.c.block_id == Block.id,
            _researchable(),
            holds_its_blocks(research.c.work_id),
        )
        .correlate_except(research)
        .exists(),
    )


def unanswered() -> ColumnElement[bool]:
    """A Block unanswered (DB 154), as a query's condition on it: with no
    `done`, and no answer or a claim."""
    return and_(Block.done_at.is_(None), or_(Block.answer.is_(None), claimed()))


def _all_held(document: type[Item]) -> ColumnElement[bool]:
    """The document `document` has a Block unanswered, and every one is
    held."""
    open_ = (
        select(Block.id)
        .where(Block.document_id == document.id, unanswered())
        .correlate_except(Block)
    )
    return and_(open_.exists(), ~open_.where(~held()).exists())


def _awaiting(document: type[Item]) -> ColumnElement[bool]:
    """The registered document `document` awaits its read (DB 246)."""
    row = aliased(Document)
    return (
        select(row.id)
        .where(row.id == document.id, awaiting_read(document, row))
        .correlate_except(row)
        .exists()
    )


def _passing(document: type[Item], job: _Rows) -> Select[uuid.UUID]:
    """The jobs `job` of the pass over `document` in flight: the job after
    the turn of the run that registered it, a Retry of it included (DB
    296)."""
    return job.select(
        job.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED,
        job.work.trigger_item_id == document.created_by_session_id,
        job.in_flight(),
    )


def _asked_about(
    query: Select[uuid.UUID],
    clarification_id: QueryableAttribute[Any],
    document: type[Item],
) -> Select[uuid.UUID]:
    """`query` narrowed to where `clarification_id` is the clarification run
    of a pass that asked the writer about a Block of `document` (DB 254,
    296)."""
    clarification = aliased(ClarificationRun)
    turn = aliased(Turn)
    question = aliased(WriterQuestion)
    asked = aliased(Block)
    return (
        query.join(clarification, clarification.id == clarification_id)
        .join(turn, turn.session_id == clarification.pass_id)
        .join(question, question.turn_id == turn.id)
        .join(asked, asked.id == question.block_id)
        .where(asked.document_id == document.id)
    )


def _asking(document: type[Item], run: _Rows) -> Select[uuid.UUID]:
    """The clarification runs `run` in flight that ask the writer about
    `document`."""
    return _asked_about(run.select(run.in_flight()), run.work.id, document)


def _after_reply(document: type[Item], job: _Rows) -> Select[uuid.UUID]:
    """The jobs `job` in flight after the turn of a clarification run that
    asked the writer about `document`, a Retry of one included (DB 256,
    296)."""
    return _asked_about(
        job.select(
            job.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED, job.in_flight()
        ),
        job.work.trigger_item_id,
        document,
    )


def pilots(document: type[Item] = Item) -> ColumnElement[bool]:
    """Whether the Item `document` is Pilot's (DB 296), as a query's
    condition on it: open, and awaiting its read; or a pass over it in
    flight, its Retry included; or the clarification run that asks its
    writer, or the job after that run's turn; or with a Block unanswered and
    every one held. Every other open Item is the person's."""
    return and_(
        document.done_at.is_(None),
        or_(
            _awaiting(document),
            _passing(document, _Rows.new()).exists(),
            _asking(document, _Rows.new()).exists(),
            _after_reply(document, _Rows.new()).exists(),
            _all_held(document),
        ),
    )


def holds(db: Session, document_ids: Collection[uuid.UUID]) -> Holds:
    """The named Blocks of the documents `document_ids` as the reading reads
    them: the held ones, each document's in its order, and the claimed
    actions handed back."""
    claim = claims.standing().subquery()
    research = researches.standing().subquery()
    found: dict[int, tuple[int, Hold]] = {}
    undone: set[int] = set()
    for standing, is_research, named in (
        (claim, False, claimed()),
        (research, True, _researchable()),
    ):
        work_id = standing.c.work_id
        rows = db.execute(
            select(
                Block.id.label("block_id"),
                Block.document_id.label("document_id"),
                Block.position.label("position"),
                work_id.label("work_id"),
                holds_its_blocks(work_id).label("holding"),
                going_on(work_id).label("going_on"),
                pulsing(work_id).label("pulse"),
                _asked_in(work_id).label("asked_in"),
            )
            .join(standing, standing.c.block_id == Block.id)
            .where(Block.document_id.in_(list(document_ids)), named)
        ).all()
        for row in rows:
            if not row.holding:
                if not is_research:
                    undone.add(row.block_id)
                continue
            found[row.block_id] = (
                row.position,
                Hold(
                    document_id=row.document_id,
                    work_id=row.work_id,
                    research=is_research,
                    going_on=row.going_on,
                    pulse=row.pulse,
                    asked_in=None if row.going_on else row.asked_in,
                ),
            )
    ordered = sorted(found.items(), key=lambda each: each[1][0])
    return Holds({block_id: hold for block_id, (_, hold) in ordered}, frozenset(undone))


def pilots_work(
    db: Session, item_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, PilotsWork]:
    """What Pilot does on each of the Items `item_ids` that is Pilot's (DB
    296), by its id, read from `pilots()`'s own states in its order; an Item
    that is the person's is left out."""
    wanted = list(item_ids)
    found: dict[uuid.UUID, PilotsWork] = {}

    def take(item_id: uuid.UUID, work: PilotsWork) -> None:
        found.setdefault(item_id, work)

    open_ = and_(Item.id.in_(wanted), Item.done_at.is_(None))
    for item_id, run_id in db.execute(
        select(Item.id, Item.created_by_session_id).where(open_, _awaiting(Item))
    ):
        take(item_id, PilotsWork(Doing.AWAITING_RUN, run_id, False, None))
    for doing, states, linked in (
        (Doing.PRE_RULING, _passing, True),
        (Doing.ASKING_WRITER, _asking, False),
        (Doing.PRE_RULING, _after_reply, True),
    ):
        rows = _Rows.new()
        for item_id, work_id, state in db.execute(
            states(Item, rows)
            .with_only_columns(Item.id, rows.work.id, rows.session.state_code)
            .where(open_)
            .order_by(rows.item.seq)
        ):
            take(
                item_id,
                PilotsWork(doing, work_id if linked else None, state in _PULSING, None),
            )
    held_documents = list(
        db.scalars(select(Item.id).where(open_, _all_held(Item)).order_by(Item.seq))
    )
    if held_documents:
        reading = holds(db, held_documents)
        for document_id in held_documents:
            mine = [
                hold
                for hold in reading.held.values()
                if hold.document_id == document_id
            ]
            going = [hold for hold in mine if hold.going_on]
            first = (going or mine)[0]
            doing = (
                Doing.WAITING_ON_ANSWER
                if not going
                else Doing.RESEARCHING
                if first.research
                else Doing.DOING
            )
            take(
                document_id,
                PilotsWork(doing, first.work_id, first.pulse, first.asked_in),
            )
    return found


def handed_back_in(db: Session, run_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
    """The Blocks whose standing naming names a Work of the run of the work
    item `run_id` and which that run no longer holds, a claim's `done`
    unwritten or a research's Block unanswered: each its document's id and
    path and its local id, in timeline order."""
    found: list[tuple[int, int, uuid.UUID, str, str]] = []
    for standing, named in (
        (claims.standing().subquery(), claimed()),
        (researches.standing().subquery(), _researchable()),
    ):
        work_id = standing.c.work_id
        found.extend(
            (seq, position, document_id, path, local_id)
            for seq, position, document_id, path, local_id in db.execute(
                select(
                    Item.seq, Block.position, Document.id, Document.path, Block.local_id
                )
                .join(Block, Block.document_id == Document.id)
                .join(Item, Item.id == Document.id)
                .join(standing, standing.c.block_id == Block.id)
                .where(
                    work_id.in_(run_of(literal(run_id))),
                    named,
                    ~holds_its_blocks(work_id),
                )
            )
        )
    return [
        (document_id, path, local_id)
        for *_, document_id, path, local_id in sorted(found)
    ]
