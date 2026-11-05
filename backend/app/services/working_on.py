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
a Resume or a Retry holds it again. A person's Cancel on a document of the
run ends it (DB 297 to 299): once one of its documents is closed `cancelled`
it holds nothing. Until then the Block is held, whether something of the run
is in flight or the run waits on the person's answer to a document it
registered.

Every hold is read by one grouped query over the standing namings and the
Works of their runs (`_holding`), which no Block or Item correlates: a query
of many items plans and runs it once.
"""

import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    Subquery,
    and_,
    false,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.orm import QueryableAttribute, Session, aliased

from app.engine import claims, researches
from app.engine.claims import claimed
from app.engine.documents import awaiting_read
from app.engine.record import CANCELLED, TURN_ENDED
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
from app.schemas.timeline import Doing
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

    @property
    def doing(self) -> Doing:
        """What Pilot does on the Block."""
        if not self.going_on:
            return Doing.WAITING_ON_ANSWER
        return Doing.RESEARCHING if self.research else Doing.DOING


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
    """DB 294 on one Work's rows, aliases of one id, true or false on a row
    that has them: its Item open, and its Session `held`, `starting`,
    `running` or `idle`, or owed its nudge (DB 232, 269; the quota wall's
    `failed` among them), or a job the Store Update not lifted yet stopped,
    which its lift retries (DB 281)."""
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

    def down(self) -> ColumnElement[bool]:
        """These rows `failed` or `stopped` and not in flight: a person's
        Stop, the take-over's, an interrupted turn, a failure (DB 294)."""
        return and_(self.session.state_code.in_(_DOWN), ~self.in_flight())


def run_of(
    work_id: ColumnElement[uuid.UUID] | QueryableAttribute[uuid.UUID | None],
) -> Select[uuid.UUID]:
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


def _researchable() -> ColumnElement[bool]:
    """A Block with neither an answer, a claim included, nor a `done`: one a
    standing research holds (DB 293)."""
    return and_(Block.answer.is_(None), Block.done_at.is_(None))


def _standing() -> Subquery:
    """The standing namings that still apply, one per Block: a claimed
    action's standing Claim Assignment (DB 260), and the standing Research
    Assignment of a Block with neither an answer nor a `done` (DB 292); the
    Block's id, the Work's and whether it is a research."""
    claim = claims.standing().subquery()
    research = researches.standing().subquery()
    return union_all(
        select(claim.c.block_id, claim.c.work_id, literal(False).label("research"))
        .join(Block, Block.id == claim.c.block_id)
        .where(claimed()),
        select(
            research.c.block_id,
            research.c.work_id,
            literal(True).label("research"),
        )
        .join(Block, Block.id == research.c.block_id)
        .where(_researchable()),
    ).subquery()


def _any(condition: ColumnElement[bool]) -> ColumnElement[bool]:
    """Whether `condition` holds on a row of the group, false where no row
    has the columns it reads."""
    return func.coalesce(func.bool_or(condition), false())


def _holding() -> Subquery:
    """Each standing naming that still applies, with what its run makes of
    its Block, one row per Block: `holding`, the run neither handing it back,
    nor done with it, nor ended by a Cancel (DB 299); `going_on`, something
    of the run in flight, a document of it awaiting its read among them, the
    job after its turn placed once it is read; `pulse`, a Session of the run,
    a Work's or the latest job's after one of their turns, queued or held,
    starting or running."""
    standing = _standing()
    named = aliased(AgentSession)
    member = _Rows.new()
    job = _Rows.new()
    clarification = aliased(ClarificationRun)
    asked = aliased(Block)
    registered = aliased(Item)
    document = aliased(Document)
    unread = aliased(Item)
    closed = aliased(Item)
    asked_nothing = ~(
        select(asked.id)
        .join(registered, registered.id == asked.document_id)
        .where(registered.created_by_session_id == member.work.id)
        .correlate_except(asked, registered)
        .exists()
    )
    awaiting = (
        select(document.id)
        .join(unread, unread.id == document.id)
        .where(
            unread.created_by_session_id == member.work.id,
            awaiting_read(unread, document),
        )
        .correlate_except(document, unread)
        .exists()
    )
    done_with = and_(
        member.item.done_cause_code == TURN_ENDED,
        clarification.id.is_(None),
        job.item.done_at.is_not(None),
        asked_nothing,
    )
    cancelled = (
        select(closed.id)
        .where(
            closed.created_by_session_id == member.work.id,
            closed.done_cause_code == CANCELLED,
        )
        .correlate_except(closed)
        .exists()
    )
    return (
        select(
            standing.c.block_id,
            standing.c.work_id,
            standing.c.research,
            and_(
                ~_any(member.down()),
                ~_any(job.down()),
                ~_any(done_with),
                ~_any(cancelled),
            ).label("holding"),
            or_(_any(member.in_flight()), _any(job.in_flight()), _any(awaiting)).label(
                "going_on"
            ),
            or_(
                _any(member.session.state_code.in_(_PULSING)),
                _any(job.session.state_code.in_(_PULSING)),
            ).label("pulse"),
        )
        .select_from(standing)
        .join(named, named.id == standing.c.work_id)
        .join(
            member.session,
            and_(
                member.session.kind_code == WORK_KIND,
                or_(
                    member.session.id == standing.c.work_id,
                    member.session.conversation_id == named.conversation_id,
                ),
            ),
        )
        .join(member.work, member.work.id == member.session.id)
        .join(member.item, member.item.id == member.session.id)
        .outerjoin(
            job.work,
            and_(
                job.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED,
                job.work.trigger_item_id == member.work.id,
                job.work.retried_by_id.is_(None),
            ),
        )
        .outerjoin(job.item, job.item.id == job.work.id)
        .outerjoin(job.session, job.session.id == job.work.id)
        .outerjoin(clarification, clarification.id == member.work.id)
        .group_by(standing.c.block_id, standing.c.work_id, standing.c.research)
        .subquery()
    )


def held() -> ColumnElement[bool]:
    """Whether a Block is held, as a query's condition on it, true or false
    and never null: its standing Claim Assignment's run holds the claimed
    action, or its standing Research Assignment's run holds the Block with
    neither an answer nor a `done` (DB 295, held through the run)."""
    holding = _holding()
    return Block.id.in_(select(holding.c.block_id).where(holding.c.holding))


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


def _registered(document: type[Item]) -> ColumnElement[bool]:
    """The Item `document` is a registered document (`source_path` set),
    never a work item, which its own Session creates too."""
    own = aliased(Document)
    return (
        select(own.id)
        .where(own.id == document.id, own.source_path.is_not(None))
        .correlate_except(own)
        .exists()
    )


def _awaiting(document: type[Item]) -> ColumnElement[bool]:
    """The registered document `document`, or another its run registered,
    awaits its read (DB 246): the pass over them is placed only once none
    does (`TurnEndReadService`)."""
    row = aliased(Document)
    unread = aliased(Item)
    return and_(
        _registered(document),
        document.created_by_session_id.in_(
            select(unread.created_by_session_id)
            .join(row, row.id == unread.id)
            .where(awaiting_read(unread, row))
            .correlate_except(unread, row)
        ),
    )


def _passing(document: type[Item], job: _Rows) -> Select[uuid.UUID]:
    """The jobs `job` of the pass over the registered document `document`
    in flight: the job after the turn of the run that registered it, a Retry
    of it included (DB 296). Never a work item: its own Session creates its
    Item too, which the job after its turn would otherwise find."""
    return job.select(
        job.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED,
        job.work.trigger_item_id == document.created_by_session_id,
        _registered(document),
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


@cache
def pilots(document: type[Item] = Item) -> ColumnElement[bool]:
    """Whether the Item `document` is Pilot's (DB 296), as a query's
    condition on it: open, and it or another document of its run awaiting
    its read; or a pass over it in
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


def _documents_of(
    work_id: ColumnElement[uuid.UUID] | QueryableAttribute[uuid.UUID | None],
    registered: type[Item],
) -> Select[uuid.UUID]:
    """The open registered documents `registered` of the run the Work
    `work_id` begins, in timeline order."""
    document = aliased(Document)
    return (
        select(registered.id)
        .join(document, document.id == registered.id)
        .where(
            registered.created_by_session_id.in_(run_of(work_id)),
            registered.done_at.is_(None),
            document.source_path.is_not(None),
        )
        .order_by(registered.seq)
        .correlate_except(registered, document)
    )


def _asked_in(work_id: ColumnElement[uuid.UUID]) -> ColumnElement[uuid.UUID]:
    """The first open registered document of the run `work_id` begins on the
    timeline: while the run holds a Block with nothing of it in flight, the
    one the person answers."""
    return _documents_of(work_id, aliased(Item)).limit(1).scalar_subquery()


def holds(db: Session, document_ids: Collection[uuid.UUID]) -> Holds:
    """The named Blocks of the documents `document_ids` as the reading reads
    them: the held ones, each document's in its order, and the claimed
    actions handed back."""
    holding = _holding()
    rows = db.execute(
        select(
            Block.id.label("block_id"),
            Block.document_id.label("document_id"),
            holding.c.work_id,
            holding.c.research,
            holding.c.holding,
            holding.c.going_on,
            holding.c.pulse,
            _asked_in(holding.c.work_id).label("asked_in"),
        )
        .join(holding, holding.c.block_id == Block.id)
        .where(Block.document_id.in_(list(document_ids)))
        .order_by(Block.document_id, Block.position)
    ).all()
    held: dict[int, Hold] = {}
    undone: set[int] = set()
    for row in rows:
        if not row.holding:
            if not row.research:
                undone.add(row.block_id)
            continue
        held[row.block_id] = Hold(
            document_id=row.document_id,
            work_id=row.work_id,
            research=row.research,
            going_on=row.going_on,
            pulse=row.pulse,
            asked_in=None if row.going_on else row.asked_in,
        )
    return Holds(held, frozenset(undone))


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
            first = ([hold for hold in mine if hold.going_on] or mine)[0]
            take(
                document_id,
                PilotsWork(first.doing, first.work_id, first.pulse, first.asked_in),
            )
    return found


def flying(db: Session, work_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """Which of the Works `work_ids` are in flight (DB 294), as their rows
    stand."""
    rows = _Rows.new()
    return set(
        db.scalars(rows.select(rows.in_flight(), rows.work.id.in_(list(work_ids))))
    )


def holding_work(db: Session, document_id: uuid.UUID) -> list[uuid.UUID]:
    """The Works in flight that make the Item `document_id` Pilot's, which
    its Stop and take over stops (F28.9): the jobs of the pass over it, a
    Retry's included, the clarification runs that ask its writer and the
    jobs after their turns; and while every open Block is held, what of each
    holding run is in flight, a Work of it or a job after one of their
    turns. In id order. A document awaiting its read, or with its every
    Block held by a run that waits on the person, has none."""
    found: set[uuid.UUID] = set()
    for states in (_passing, _asking, _after_reply):
        found.update(
            db.scalars(states(Item, _Rows.new()).where(Item.id == document_id))
        )
    if db.scalar(select(Item.id).where(Item.id == document_id, _all_held(Item))):
        for work_id in {
            hold.work_id for hold in holds(db, [document_id]).held.values()
        }:
            run = run_of(literal(work_id))
            rows = _Rows.new()
            found.update(
                db.scalars(
                    rows.select(
                        rows.in_flight(),
                        or_(
                            rows.work.id.in_(run),
                            and_(
                                rows.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED,
                                rows.work.trigger_item_id.in_(run),
                            ),
                        ),
                    )
                )
            )
    return sorted(found)


@dataclass(frozen=True)
class TakenBack:
    """A Block a Cancel gives back to the person: one the run of the
    document it is pressed on holds (DB 297)."""

    block_id: int
    document_id: uuid.UUID
    research: bool
    """A research's naming, else a claim's."""


@dataclass(frozen=True)
class Cancel:
    """What a Cancel on an open registered document of a worker's run that
    is the person's reads (F28.9; DB 297): what the run holds, whether
    something of it is in flight, and whether Pilot works on one of its
    documents."""

    run_id: uuid.UUID
    """The work item that registered the document, of the run it ends."""
    takes_back: tuple[TakenBack, ...]
    """The Blocks the run holds, in timeline order."""
    going_on: bool
    """Something of the run in flight, a document of it awaiting its read
    among them."""
    pilots_in_run: bool
    """An open document of the run is Pilot's, or has a Block held: every
    document a Cancel closes is the person's, with no Block held (DB 295,
    297)."""

    @property
    def offered(self) -> bool:
        """The run holds a Block, nothing of it is in flight, and Pilot works
        on none of its documents."""
        return bool(self.takes_back) and not self.going_on and not self.pilots_in_run


def cancels(db: Session, item_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, Cancel]:
    """What a Cancel reads on each of the Items `item_ids` that is an open
    registered document of a worker's run and the person's (DB 296, 297), by
    its id, whether it is offered or not; every other Item is left out."""
    holding = _holding()
    creator = aliased(AgentSession)
    named = aliased(Block)
    owner = aliased(Item)
    rows = db.execute(
        select(
            Item.id,
            Item.created_by_session_id,
            holding.c.block_id,
            named.document_id,
            holding.c.research,
            holding.c.holding,
            holding.c.going_on,
        )
        .join(Document, Document.id == Item.id)
        .join(creator, creator.id == Item.created_by_session_id)
        .outerjoin(holding, holding.c.work_id.in_(run_of(Item.created_by_session_id)))
        .outerjoin(named, named.id == holding.c.block_id)
        .outerjoin(owner, owner.id == named.document_id)
        .where(
            Item.id.in_(list(item_ids)),
            Item.done_at.is_(None),
            Document.source_path.is_not(None),
            creator.kind_code == WORK_KIND,
            ~pilots(),
        )
        .order_by(Item.id, owner.seq, named.position)
    ).all()
    runs: dict[uuid.UUID, uuid.UUID] = {}
    taken: dict[uuid.UUID, list[TakenBack]] = {}
    going: set[uuid.UUID] = set()
    for row in rows:
        runs[row.id] = row.created_by_session_id
        mine = taken.setdefault(row.id, [])
        if row.holding:
            mine.append(TakenBack(row.block_id, row.document_id, row.research))
        if row.going_on:
            going.add(row.id)
    pilots_in = _pilots_in_runs(db, set(runs.values()))
    return {
        item_id: Cancel(
            run_id, tuple(taken[item_id]), item_id in going, run_id in pilots_in
        )
        for item_id, run_id in runs.items()
    }


def _pilots_in_runs(db: Session, run_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """Which of the runs the Works `run_ids` begin have an open registered
    document that is Pilot's, or with a Block held (DB 295, 296): one that a
    Cancel's close would take from Pilot's work, another run's claim or
    research."""
    run = aliased(AgentSession)
    held_blocks = (
        select(Block.id)
        .where(Block.document_id == Item.id, held())
        .correlate_except(Block)
    )
    return set(
        db.scalars(
            select(run.id).where(
                run.id.in_(list(run_ids)),
                _documents_of(run.id, Item)
                .where(or_(pilots(), held_blocks.exists()))
                .exists(),
            )
        )
    )


def run_documents(db: Session, run_id: uuid.UUID) -> list[uuid.UUID]:
    """The open registered documents of the run of the work item `run_id`,
    in timeline order: what its Cancel closes (DB 298)."""
    return list(db.scalars(_documents_of(literal(run_id), aliased(Item))))


def handed_back_in(db: Session, run_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
    """The Blocks whose standing naming names a Work of the run of the work
    item `run_id` and which that run no longer holds, a claim's `done`
    unwritten or a research's Block unanswered: each its document's id and
    path and its local id, in timeline order."""
    holding = _holding()
    return [
        (document_id, path, local_id)
        for document_id, path, local_id in db.execute(
            select(Document.id, Document.path, Block.local_id)
            .join(Block, Block.document_id == Document.id)
            .join(Item, Item.id == Document.id)
            .join(holding, holding.c.block_id == Block.id)
            .where(holding.c.work_id.in_(run_of(literal(run_id))), ~holding.c.holding)
            .order_by(Item.seq, Block.position)
        )
    ]
