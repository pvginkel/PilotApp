"""What Pilot is working on (F13.7, F21.6, F28.9, F52.3, F59.1, F94.5; DB 294
to 296), read from the rows at every read and never stored: whether a Work is
in flight, whether a Block is held and by which run, whether a registered
document is Pilot's, with what Pilot does on it, the work item to link and
whether its line pulses, and which of Pilot's jobs shows on an item.
`waiting()`, and through it the badge, the project's status and the standing
notification, reads it from here, and so does every other reader of what
Pilot does on an item.

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

A read takes what Pilot is working on from a `Reading` of its own, made
after its last write: every hold read at once, by one grouped query over the
standing namings and the Works of their runs (`_holding`), which no Block or
Item correlates, and then the Items that are Pilot's, each of
`Reading.pilots`'s states by a query of its own. A statement that reads a
Block held, or an Item Pilot's, takes the ids the reading found, never the
reading's own SQL.

A statement that a read of the timeline sends from here through aliases is
built once, when first sent, and each read binds its ids into it as
parameters, so that it holds no row it read: building one, its aliases'
columns among it, costs more than PostgreSQL's run of it.
"""

import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from functools import cache, cached_property
from typing import Any

from sqlalchemy import (
    BindParameter,
    ColumnElement,
    Select,
    Subquery,
    and_,
    bindparam,
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
from app.engine.record import CANCELLED, TURN_ENDED, WITHDRAWN
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


_HOLDING_LENGTH = 5_400
"""The longest `_holding()` compiles to for PostgreSQL: the one statement of
the reading over 2,000 characters, kept whole so that every hold is read at
once."""


@cache
def _holding() -> Select[int, uuid.UUID, bool, bool, bool, bool]:
    """Each standing naming that still applies, with what its run makes of
    its Block, one row per Block: `holding`, the run neither handing it back,
    nor done with it, nor ended by a Cancel (DB 299); `going_on`, something
    of the run in flight, a document of it awaiting its read among them, the
    job after its turn placed once it is read; `pulse`, a Session of the run,
    a Work's or the latest job's after one of their turns, queued or held,
    starting or running. Its length's bound rides on it as the execution
    option `max_statement_length`."""
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
        .execution_options(max_statement_length=_HOLDING_LENGTH)
    )


def unanswered() -> ColumnElement[bool]:
    """A Block unanswered (DB 154), as a query's condition on it: with no
    `done`, and no answer or a claim."""
    return and_(Block.done_at.is_(None), or_(Block.answer.is_(None), claimed()))


def _all_held(document: type[Item], held: ColumnElement[bool]) -> ColumnElement[bool]:
    """The document `document` has a Block unanswered, and every one is
    `held`, a condition on a Block."""
    open_ = (
        select(Block.id)
        .where(Block.document_id == document.id, unanswered())
        .correlate_except(Block)
    )
    return and_(open_.exists(), ~open_.where(~held).exists())


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


def _pass_over(document: type[Item], job: _Rows) -> Select[uuid.UUID]:
    """The jobs `job` of the pass over the registered document `document`:
    the job after the turn of the run that registered it, a Retry of it
    included (DB 296). Never a work item: its own Session creates its Item
    too, which the job after its turn would otherwise find."""
    return job.select(
        job.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED,
        job.work.trigger_item_id == document.created_by_session_id,
        _registered(document),
    )


def _passing(document: type[Item], job: _Rows) -> Select[uuid.UUID]:
    """The jobs `job` of the pass over the registered document `document`
    in flight."""
    return _pass_over(document, job).where(job.in_flight())


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


def _replied(document: type[Item], job: _Rows) -> Select[uuid.UUID]:
    """The jobs `job` after the turn of a clarification run that asked the
    writer about `document`, a Retry of one included (DB 256, 296): the pass
    after the writer's reply."""
    return _asked_about(
        job.select(job.work.trigger_code == WorkTrigger.WORKER_TURN_ENDED),
        job.work.trigger_item_id,
        document,
    )


def _after_reply(document: type[Item], job: _Rows) -> Select[uuid.UUID]:
    """The jobs `job` after the writer's reply about `document` in flight."""
    return _replied(document, job).where(job.in_flight())


@cache
def _awaiting_items() -> Select[uuid.UUID, uuid.UUID | None]:
    """The open Items that await their run's read (`_awaiting`), each with
    the Work that registered it."""
    return select(Item.id, Item.created_by_session_id).where(
        Item.done_at.is_(None), _awaiting(Item)
    )


_State = tuple[Doing, Select[uuid.UUID, uuid.UUID, SessionState], bool]


@cache
def _in_flight_states() -> tuple[_State, ...]:
    """`Reading.pilots`'s states of a Work in flight on an open Item, in its
    order: what Pilot does in each; its statement, of the Item's id, the
    Work's and its Session's state, in the Work's timeline order; and
    whether the Item's line links the Work."""
    states: list[_State] = []
    for doing, state, linked in (
        (Doing.PRE_RULING, _passing, True),
        (Doing.ASKING_WRITER, _asking, False),
        (Doing.PRE_RULING, _after_reply, True),
    ):
        rows = _Rows.new()
        states.append(
            (
                doing,
                state(Item, rows)
                .with_only_columns(Item.id, rows.work.id, rows.session.state_code)
                .where(Item.done_at.is_(None))
                .order_by(rows.item.seq),
                linked,
            )
        )
    return tuple(states)


@cache
def _all_held_items() -> Select[uuid.UUID]:
    """The open Items with a Block unanswered and every one held, the held
    Blocks' ids bound as `held`."""
    return select(Item.id).where(
        Item.done_at.is_(None),
        _all_held(Item, Block.id.in_(bindparam("held", expanding=True))),
    )


@dataclass(frozen=True)
class Naming:
    """A standing naming that still applies, with what its run makes of its
    Block (`_holding`)."""

    block_id: int
    work_id: uuid.UUID
    research: bool
    holding: bool
    going_on: bool
    pulse: bool


class Reading:
    """What Pilot is working on as the rows stand, read from them once, when
    first asked, and kept by the read that made it alone (DB decision 71):
    a read makes its own after its last write, so that it sees that write."""

    def __init__(self, db: Session) -> None:
        self.db = db

    @cached_property
    def namings(self) -> tuple[Naming, ...]:
        """Every standing naming that still applies, as its run makes of its
        Block."""
        return tuple(
            Naming(
                block_id=row.block_id,
                work_id=row.work_id,
                research=row.research,
                holding=row.holding,
                going_on=row.going_on,
                pulse=row.pulse,
            )
            for row in self.db.execute(_holding())
        )

    @cached_property
    def held_ids(self) -> frozenset[int]:
        """The ids of the held Blocks."""
        return frozenset(naming.block_id for naming in self.namings if naming.holding)

    def held(self) -> ColumnElement[bool]:
        """Whether a Block is held, as a query's condition on it, true or
        false and never null: its standing Claim Assignment's run holds the
        claimed action, or its standing Research Assignment's run holds the
        Block with neither an answer nor a `done` (DB 295, held through the
        run)."""
        return Block.id.in_(list(self.held_ids))

    @cached_property
    def found(self) -> Mapping[uuid.UUID, PilotsWork | None]:
        """Each Item that is Pilot's (DB 296), by its id, with what Pilot
        does on it as the first of `Reading.pilots`'s states that holds
        reads it; none for one Pilot's for its every open Block held alone,
        whose holds tell (`pilots_work`)."""
        found: dict[uuid.UUID, PilotsWork | None] = {}
        for item_id, run_id in self.db.execute(_awaiting_items()):
            found.setdefault(
                item_id, PilotsWork(Doing.AWAITING_RUN, run_id, False, None)
            )
        for doing, statement, linked in _in_flight_states():
            for item_id, work_id, state in self.db.execute(statement):
                found.setdefault(
                    item_id,
                    PilotsWork(
                        doing, work_id if linked else None, state in _PULSING, None
                    ),
                )
        if self.held_ids:
            for item_id in self.db.scalars(
                _all_held_items(), {"held": list(self.held_ids)}
            ):
                found.setdefault(item_id, None)
        return found

    def pilots(self, document: type[Item] = Item) -> ColumnElement[bool]:
        """Whether the Item `document` is Pilot's (DB 296), as a query's
        condition on it: open, and it or another document of its run
        awaiting its read; or a pass over it in flight, its Retry included;
        or the clarification run that asks its writer, or the job after that
        run's turn; or with a Block unanswered and every one held. Every
        other open Item is the person's."""
        return document.id.in_(list(self.found))


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


@cache
def _first_documents() -> Select[uuid.UUID, uuid.UUID | None]:
    """Each Work bound as `works`, with the first open registered document
    on the timeline of the run it begins, or none."""
    start = aliased(Work)
    return select(
        start.id,
        _documents_of(start.id, aliased(Item)).limit(1).scalar_subquery(),
    ).where(start.id.in_(bindparam("works", expanding=True)))


def _asked_in(
    db: Session, work_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """The first open registered document on the timeline of the run each
    Work of `work_ids` begins, by the Work's id, where it has one: while the
    run holds a Block with nothing of it in flight, the one the person
    answers."""
    return {
        work_id: document_id
        for work_id, document_id in db.execute(
            _first_documents(), {"works": list(work_ids)}
        )
        if document_id is not None
    }


def holds(reading: Reading, document_ids: Collection[uuid.UUID]) -> Holds:
    """The named Blocks of the documents `document_ids` as `reading` reads
    them: the held ones, each document's in its order, and the claimed
    actions handed back."""
    if not reading.namings or not document_ids:
        return Holds({}, frozenset())
    named = {naming.block_id: naming for naming in reading.namings}
    placed = reading.db.execute(
        select(Block.id, Block.document_id)
        .where(Block.id.in_(list(named)), Block.document_id.in_(list(document_ids)))
        .order_by(Block.document_id, Block.position)
    ).all()
    waiting = {
        named[block_id].work_id
        for block_id, _ in placed
        if named[block_id].holding and not named[block_id].going_on
    }
    asked = _asked_in(reading.db, waiting) if waiting else {}
    held: dict[int, Hold] = {}
    undone: set[int] = set()
    for block_id, document_id in placed:
        naming = named[block_id]
        if not naming.holding:
            if not naming.research:
                undone.add(block_id)
            continue
        held[block_id] = Hold(
            document_id=document_id,
            work_id=naming.work_id,
            research=naming.research,
            going_on=naming.going_on,
            pulse=naming.pulse,
            asked_in=None if naming.going_on else asked.get(naming.work_id),
        )
    return Holds(held, frozenset(undone))


def pilots_work(
    reading: Reading, item_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, PilotsWork]:
    """What Pilot does on each of the Items `item_ids` that is Pilot's (DB
    296), by its id, read from `Reading.pilots`'s own states in its order, as
    `reading` reads them; an Item that is the person's is left out."""
    found: dict[uuid.UUID, PilotsWork] = {}
    held_documents: list[uuid.UUID] = []
    for item_id in item_ids:
        if item_id not in reading.found:
            continue
        work = reading.found[item_id]
        if work is None:
            held_documents.append(item_id)
        else:
            found[item_id] = work
    if held_documents:
        held = holds(reading, held_documents).held.values()
        for document_id in held_documents:
            mine = [hold for hold in held if hold.document_id == document_id]
            first = ([hold for hold in mine if hold.going_on] or mine)[0]
            found[document_id] = PilotsWork(
                first.doing, first.work_id, first.pulse, first.asked_in
            )
    return found


@dataclass(frozen=True)
class JobsOn:
    """Pilot's jobs on items (F59.1), by the jobs' ids."""

    shown: Mapping[uuid.UUID, uuid.UUID]
    """The job each item shows, by the item's id."""
    after_turn: Mapping[uuid.UUID, uuid.UUID]
    """The job after each worker's run's turn, by the run's id."""


def _not_withdrawn(job: _Rows) -> ColumnElement[bool]:
    """The job `job` was not withdrawn before its brief (`JobService.withdraw`)."""
    return job.item.done_cause_code.is_distinct_from(WITHDRAWN)


@cache
def _passes_on() -> tuple[Select[uuid.UUID, uuid.UUID, int], ...]:
    """The jobs of the passes not withdrawn, `_pass_over`'s and
    `_replied`'s, on the Items bound as `wanted` or triggered by them: each
    the Item's id, the job's and its timeline place."""
    wanted: BindParameter[Any] = bindparam("wanted", expanding=True)
    statements: list[Select[uuid.UUID, uuid.UUID, int]] = []
    for over in (_pass_over, _replied):
        rows = _Rows.new()
        statements.append(
            over(Item, rows)
            .with_only_columns(Item.id, rows.work.id, rows.item.seq)
            .where(
                or_(Item.id.in_(wanted), rows.work.trigger_item_id.in_(wanted)),
                _not_withdrawn(rows),
            )
        )
    return tuple(statements)


@cache
def _triggered_by() -> Select[uuid.UUID | None, WorkTrigger | None, uuid.UUID, int]:
    """The jobs not withdrawn that the Items bound as `wanted` triggered:
    each its trigger item's id, its trigger, its id and its timeline
    place."""
    job = _Rows.new()
    return job.select(
        job.work.trigger_code.is_not(None),
        job.work.trigger_item_id.in_(bindparam("wanted", expanding=True)),
        _not_withdrawn(job),
    ).with_only_columns(
        job.work.trigger_item_id, job.work.trigger_code, job.work.id, job.item.seq
    )


def jobs_on(db: Session, item_ids: Collection[uuid.UUID]) -> JobsOn:
    """Which of Pilot's jobs each of the Items `item_ids` shows (F59.1),
    whatever its state: a pass on every registered document its trigger run
    registered, and the pass after the writer's reply on every document the
    pass before it asked the writer about, as `Reading.pilots` reads them; any
    other job on its trigger item, the worker's run whose turn ended, the
    item of Pilot's that was closed or the wait that fired; the setup, which
    has none, on no item. Where several stand on one item, the latest placed
    shows, a Retry over the job it retries; a withdrawn job shows nowhere.
    And for each worker's run among them, the job after its turn, the latest
    of it and its Retries, wherever it shows."""
    wanted = list(item_ids)
    among = set(wanted)
    shown: dict[uuid.UUID, tuple[int, uuid.UUID]] = {}
    after_turn: dict[uuid.UUID, tuple[int, uuid.UUID]] = {}

    def latest(
        found: dict[uuid.UUID, tuple[int, uuid.UUID]],
        item_id: uuid.UUID,
        seq: int,
        job_id: uuid.UUID,
    ) -> None:
        if item_id not in found or found[item_id][0] < seq:
            found[item_id] = (seq, job_id)

    passes: set[uuid.UUID] = set()
    for statement in _passes_on():
        for document_id, job_id, seq in db.execute(statement, {"wanted": wanted}):
            passes.add(job_id)
            if document_id in among:
                latest(shown, document_id, seq, job_id)
    for trigger_id, trigger, job_id, seq in db.execute(
        _triggered_by(), {"wanted": wanted}
    ):
        assert trigger_id is not None
        if trigger is WorkTrigger.WORKER_TURN_ENDED:
            latest(after_turn, trigger_id, seq, job_id)
        if job_id not in passes:
            latest(shown, trigger_id, seq, job_id)
    return JobsOn(
        {item_id: job_id for item_id, (_, job_id) in shown.items()},
        {run_id: job_id for run_id, (_, job_id) in after_turn.items()},
    )


def flying(db: Session, work_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """Which of the Works `work_ids` are in flight (DB 294), as their rows
    stand."""
    rows = _Rows.new()
    return set(
        db.scalars(rows.select(rows.in_flight(), rows.work.id.in_(list(work_ids))))
    )


def holding_work(reading: Reading, document_id: uuid.UUID) -> list[uuid.UUID]:
    """The Works in flight that make the Item `document_id` Pilot's, which
    its Stop and take over stops (F28.9): the jobs of the pass over it, a
    Retry's included, the clarification runs that ask its writer and the
    jobs after their turns; and while every open Block is held, as
    `reading` reads the holds, what of each holding run is in flight, a Work
    of it or a job after one of their turns. In id order. A document
    awaiting its read, or with its every Block held by a run that waits on
    the person, has none."""
    db = reading.db
    found: set[uuid.UUID] = set()
    for states in (_passing, _asking, _after_reply):
        found.update(
            db.scalars(states(Item, _Rows.new()).where(Item.id == document_id))
        )
    if reading.held_ids and db.scalar(
        select(Item.id).where(Item.id == document_id, _all_held(Item, reading.held()))
    ):
        for work_id in {
            hold.work_id for hold in holds(reading, [document_id]).held.values()
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


@cache
def _runs_named() -> Select[uuid.UUID, uuid.UUID | None, uuid.UUID | None]:
    """Each Item bound as `items` that is an open registered document of a
    worker's run and not among the Items bound as `pilots`, with the Work
    that registered it, once with each Work of its run among the Works bound
    as `named`, or once with none."""
    creator = aliased(AgentSession)
    member = aliased(Work)
    return (
        select(Item.id, Item.created_by_session_id, member.id.label("work_id"))
        .join(Document, Document.id == Item.id)
        .join(creator, creator.id == Item.created_by_session_id)
        .outerjoin(
            member,
            and_(
                member.id.in_(bindparam("named", expanding=True)),
                member.id.in_(run_of(Item.created_by_session_id)),
            ),
        )
        .where(
            Item.id.in_(bindparam("items", expanding=True)),
            Item.done_at.is_(None),
            Document.source_path.is_not(None),
            creator.kind_code == WORK_KIND,
            ~Item.id.in_(bindparam("pilots", expanding=True)),
        )
    )


def cancels(
    reading: Reading, item_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, Cancel]:
    """What a Cancel reads on each of the Items `item_ids` that is an open
    registered document of a worker's run and the person's (DB 296, 297), by
    its id, whether it is offered or not, as `reading` reads them; every
    other Item is left out."""
    db = reading.db
    runs: dict[uuid.UUID, uuid.UUID] = {}
    works: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in db.execute(
        _runs_named(),
        {
            "items": list(item_ids),
            "named": list({naming.work_id for naming in reading.namings}),
            "pilots": list(reading.found),
        },
    ):
        runs[row.id] = row.created_by_session_id
        named = works.setdefault(row.id, set())
        if row.work_id is not None:
            named.add(row.work_id)
    if not runs:
        return {}
    of_runs = set().union(*works.values())
    by_block = {
        naming.block_id: naming
        for naming in reading.namings
        if naming.work_id in of_runs
    }
    held = [block_id for block_id, naming in by_block.items() if naming.holding]
    placed = (
        db.execute(
            select(Block.id, Block.document_id)
            .join(Item, Item.id == Block.document_id)
            .where(Block.id.in_(held))
            .order_by(Item.seq, Block.position)
        ).all()
        if held
        else []
    )
    pilots_in = _pilots_in_runs(reading, set(runs.values()))
    return {
        item_id: Cancel(
            run_id,
            tuple(
                TakenBack(block_id, document_id, by_block[block_id].research)
                for block_id, document_id in placed
                if by_block[block_id].work_id in works[item_id]
            ),
            any(
                naming.going_on
                for naming in by_block.values()
                if naming.work_id in works[item_id]
            ),
            run_id in pilots_in,
        )
        for item_id, run_id in runs.items()
    }


@cache
def _runs_with_pilots() -> Select[uuid.UUID]:
    """The Works bound as `runs` whose run has an open registered document
    among the Items bound as `pilots`, or with a Block among those bound as
    `held`."""
    run = aliased(AgentSession)
    held_blocks = (
        select(Block.id)
        .where(
            Block.document_id == Item.id,
            Block.id.in_(bindparam("held", expanding=True)),
        )
        .correlate_except(Block)
    )
    return select(run.id).where(
        run.id.in_(bindparam("runs", expanding=True)),
        _documents_of(run.id, Item)
        .where(
            or_(Item.id.in_(bindparam("pilots", expanding=True)), held_blocks.exists())
        )
        .exists(),
    )


def _pilots_in_runs(reading: Reading, run_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """Which of the runs the Works `run_ids` begin have an open registered
    document that is Pilot's, or with a Block held (DB 295, 296), as
    `reading` reads them: one that a Cancel's close would take from Pilot's
    work, another run's claim or research."""
    return set(
        reading.db.scalars(
            _runs_with_pilots(),
            {
                "runs": list(run_ids),
                "pilots": list(reading.found),
                "held": list(reading.held_ids),
            },
        )
    )


def run_documents(db: Session, run_id: uuid.UUID) -> list[uuid.UUID]:
    """The open registered documents of the run of the work item `run_id`,
    in timeline order: what its Cancel closes (DB 298)."""
    return list(db.scalars(_documents_of(literal(run_id), aliased(Item))))


def handed_back_in(
    reading: Reading, run_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, str]]:
    """The Blocks whose standing naming names a Work of the run of the work
    item `run_id` and which that run no longer holds, as `reading` reads
    them, a claim's `done` unwritten or a research's Block unanswered: each
    its document's id and path and its local id, in timeline order."""
    handed = {
        naming.block_id: naming.work_id
        for naming in reading.namings
        if not naming.holding
    }
    if not handed:
        return []
    db = reading.db
    run = set(
        db.scalars(
            select(Work.id).where(
                Work.id.in_(list(set(handed.values()))),
                Work.id.in_(run_of(literal(run_id))),
            )
        )
    )
    blocks = [block_id for block_id, work_id in handed.items() if work_id in run]
    if not blocks:
        return []
    return [
        (document_id, path, local_id)
        for document_id, path, local_id in db.execute(
            select(Document.id, Document.path, Block.local_id)
            .join(Block, Block.document_id == Document.id)
            .join(Item, Item.id == Document.id)
            .where(Block.id.in_(blocks))
            .order_by(Item.seq, Block.position)
        )
    ]
