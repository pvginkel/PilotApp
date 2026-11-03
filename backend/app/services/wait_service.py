"""The waits (DB decision 46, F27): a card wait or a timed wait added by the
brain, fixed at add (F27.6), fired by the server (F136.2, F27.2), and closed by
its own `done` with a note (F27.4, DB 300) or by Finish's close of the open
items, which writes none.

A person's request fires an open wait too (F27.3), refused while a firing of
it is pending or a run of it is in flight, on a wait that is done, and in a
project finished or archived: one rule, which the timeline's read gives as
the wait's button (`refusals`). What the brain did with each firing is read
from the run that took it and the wait's close, never stored (`firings`).

A wait's pending firings become one run of the brain per batch (F136.4): the
batcher's tick (`WaitBatcher`) places a `wait_fired` job once its oldest
pending firing is a quiet window old and no run of the wait is in flight, and
the job takes every firing still pending at its brief (DB 196). That run
resumes the conversation of the wait's previous run when that run's turn ended
`idle` within `cache_expiration_ttl` (F136.5, DB 200).

Each write is of the caller's transaction, under its Project's row: a wait's
birth takes its `seq` under it (`DocumentService.next_seq`), its close locks
its run held before its brief, as a run's brief does before its take, then
holds the Wait's row, a firing, a person's request among them, holds the
Project's row shared, then the Wait's, and reads the wait open there, and the
batcher's placement and a run's take hold the Wait's row after the Project's.
"""

import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import (
    ColumnElement,
    SQLColumnExpression,
    and_,
    exists,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.orm import Session

from app.engine.documents import DocumentService
from app.engine.record import ARCHIVED, MARKED
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException
from app.models import CardTransition, Item, Project, User, Wait, WaitFiring, Work
from app.models import Session as AgentSession
from app.models.reference import FiringCause, ProjectState, SessionState, WorkTrigger
from app.schemas.timeline import FiringOutcome, RequestLabel

if TYPE_CHECKING:
    from app.services.job_service import JobService

CARD_WAIT = "card_wait"
TIMED_WAIT = "timed_wait"
WAITS = (CARD_WAIT, TIMED_WAIT)
"""The Item Kinds of form `wait` (DB assertion 185)."""

REQUESTS: dict[str, RequestLabel] = {CARD_WAIT: "Check now", TIMED_WAIT: "Skip wait"}
"""What a person's request is called on each kind of wait (F27.3)."""

CHECKING = "Pilot is checking"
"""Why a wait takes no request while a firing of it is pending or a run of it
is in flight (F27.3; UC's tooltip)."""

_IN_FLIGHT = (SessionState.HELD, SessionState.STARTING, SessionState.RUNNING)
"""The states of a wait's run that keep a second from being placed: held at
the gate or queued behind its project's jobs, briefed or not, starting, or
running, a follow-up turn included."""

_RESUMABLE = (SessionState.IDLE, SessionState.ENDED)
"""The states of a run whose turn ended neither failed nor stopped."""


@dataclass(frozen=True)
class ReportedTransition:
    """A card's change of state as its tracker posted it (F136): the card, as
    the tracker writes it; the state it left, none when the tracker gives
    none; the state it entered; when, by the tracker's clock; and by whom,
    none when the tracker names no one."""

    card: str
    from_state: str | None
    to_state: str
    at: datetime
    by: str | None


@dataclass(frozen=True)
class ShownFiring:
    """A firing of a wait, with the transition that caused it, if one did,
    and what the brain did with it, none where it did nothing."""

    firing: WaitFiring
    transition: CardTransition | None
    outcome: FiringOutcome | None


class WaitService:
    def __init__(
        self,
        db: Session,
        document_service: DocumentService,
        view_service: ViewService,
        ticket_id_pattern: re.Pattern[str],
        cache_expiration_ttl_seconds: float,
        jobs: Callable[[], "JobService"],
    ) -> None:
        self.db = db
        self.document_service = document_service
        self.view_service = view_service
        self.ticket_id_pattern = ticket_id_pattern
        self.cache_expiration_ttl = timedelta(seconds=cache_expiration_ttl_seconds)
        self.jobs = jobs

    def add_card_wait(
        self,
        project: Project,
        session: AgentSession,
        title: str,
        cards: Sequence[str],
        states: Sequence[str],
        plan_task_id: str | None,
    ) -> Item:
        """A card wait of `session`'s on `cards` entering one of `states`,
        each as given (F27.1), at the project's next place, on the plan's
        task `plan_task_id` when given.

        Raises:
            InvalidOperationException: a list is empty, a card is no ticket
                id (F91), or a list names a card or a state twice, a state
                case-insensitively (DB 194).
        """
        operation = f"add a {CARD_WAIT} item"
        _listed(cards, "cards", operation, lambda card: card)
        _listed(states, "states", operation, str.casefold)
        strays = [card for card in cards if not self.ticket_id_pattern.fullmatch(card)]
        if strays:
            raise InvalidOperationException(
                operation,
                f"{_names(strays)} {'is' if len(strays) == 1 else 'are'} no ticket"
                f" id, `{self.ticket_id_pattern.pattern}`",
            )
        item = self._item(project, session, CARD_WAIT, title, plan_task_id)
        self.db.add(
            Wait(
                id=item.id, kind_code=CARD_WAIT, cards=list(cards), states=list(states)
            )
        )
        self.db.flush()
        self.view_service.timeline_moved(project)
        return item

    def add_timed_wait(
        self,
        project: Project,
        session: AgentSession,
        title: str,
        due_at: datetime,
        plan_task_id: str | None,
    ) -> Item:
        """A timed wait of `session`'s due at `due_at` (F27.2), at the
        project's next place, on the plan's task `plan_task_id` when given.

        Raises:
            InvalidOperationException: `due_at` is not ahead (DB 198).
        """
        if due_at <= datetime.now(UTC):
            raise InvalidOperationException(
                f"add a {TIMED_WAIT} item",
                f"its due time, {due_at.astimezone(UTC).isoformat()}, is not ahead",
            )
        item = self._item(project, session, TIMED_WAIT, title, plan_task_id)
        self.db.add(Wait(id=item.id, kind_code=TIMED_WAIT, due_at=due_at))
        self.db.flush()
        self.view_service.timeline_moved(project)
        return item

    def close(
        self,
        project: Project,
        wait: Wait,
        pilot: User,
        session_id: uuid.UUID,
        note: str,
    ) -> None:
        """The open wait done by Pilot's own `done` in the Session
        `session_id`, with `note` (F27.4): Done Cause `marked`, consumed on
        the spot by that Session, so it offers no Undo (DB 199), and its
        note set with its `done_at` (DB 300). Its run held before its brief
        is withdrawn: a wait that is done gets no run. `project`'s row is the
        caller's to hold.

        Raises:
            InvalidOperationException: the project is archived, or the wait
                is done.
        """
        operation = f"mark item {wait.id} done"
        if project.archived:
            raise InvalidOperationException(operation, ARCHIVED)
        jobs = self.jobs()
        run = jobs.unbriefed(self.db.get_one(Item, wait.id))
        self.db.execute(select(Wait.id).where(Wait.id == wait.id).with_for_update())
        item = self.db.get_one(Item, wait.id, populate_existing=True)
        if item.done_at is not None:
            raise InvalidOperationException(operation, "the item is done")
        at = datetime.now(UTC).replace(microsecond=0)
        item.done_at = at
        item.done_cause_code = MARKED
        item.done_by_user_id = pilot.id
        item.consumed_at = at
        item.consumed_session_id = session_id
        wait.done_note = note
        if run is not None:
            jobs.withdraw(run, at)
        self.db.flush()
        self.view_service.timeline_moved(project)

    def fire_transition(self, transition: ReportedTransition) -> int:
        """Fire, once each, the open card waits of open, unarchived projects
        that watch `transition`'s card and, case-insensitively, the state it
        entered (F136.2, DB 197). The transition is recorded only when a wait
        fired; nothing is read from the tracker (F136.3).

        Returns:
            How many waits fired.
        """
        entered = transition.to_state.casefold()
        watching = self.db.execute(
            select(Item.project_id, Wait.id, Wait.states)
            .join(Item, Item.id == Wait.id)
            .join(Project, Project.id == Item.project_id)
            .where(Wait.cards.contains([transition.card]), _firable())
            .order_by(Item.project_id, Wait.id)
        ).all()
        held: list[tuple[Project, uuid.UUID]] = []
        for project_id, wait_id, states in watching:
            # A wait with cards has states (`ck_waits_halves`).
            assert states is not None
            if entered not in {state.casefold() for state in states}:
                continue
            project = self._hold(project_id, wait_id, skip_locked=False)
            if project is not None:
                held.append((project, wait_id))
        if not held:
            return 0
        at = datetime.now(UTC)
        recorded = CardTransition(
            card=transition.card,
            from_state=transition.from_state,
            to_state=transition.to_state,
            at=transition.at,
            by=transition.by,
            received_at=at,
        )
        self.db.add(recorded)
        self.db.flush()
        for _, wait_id in held:
            self._fire(
                wait_id,
                CARD_WAIT,
                FiringCause.TRANSITION,
                at,
                transition_id=recorded.id,
            )
        self._moved(project for project, _ in held)
        return len(held)

    def fire_due(self) -> int:
        """Fire `due` the open timed waits of open, unarchived projects whose
        due time has passed and that have not fired it (F27.2, DB 198), those
        that came due while no process ran included. A Wait's row another
        transaction holds is skipped, for the next call to read again: two
        processes at once fire a wait once.

        Returns:
            How many waits fired.
        """
        at = datetime.now(UTC)
        due = self.db.execute(
            select(Item.project_id, Wait.id)
            .join(Item, Item.id == Wait.id)
            .join(Project, Project.id == Item.project_id)
            .where(Wait.due_at <= at, _firable(), ~_due_fired(Wait.id))
            .order_by(Item.project_id, Wait.id)
        ).all()
        fired: list[Project] = []
        for project_id, wait_id in due:
            project = self._hold(project_id, wait_id, skip_locked=True)
            if project is None or self.db.scalar(select(_due_fired(wait_id))):
                continue
            self._fire(wait_id, TIMED_WAIT, FiringCause.DUE, at)
            fired.append(project)
        self._moved(fired)
        return len(fired)

    def request(self, item: Item, person: User) -> None:
        """`person`'s request of the wait `item` (F27.3; DB 190): a
        `requested` firing by them, pending for the wait's next run as any
        firing is (F136.4), read under the wait's Project's row, held shared,
        and the Wait's, by `refusals`' rule.

        Raises:
            InvalidOperationException: the item is no wait, or the wait takes
                no request now: why (`refusals`).
        """
        operation = f"request a firing of item {item.id}"
        if item.kind_code not in WAITS:
            raise InvalidOperationException(
                operation, f"a {item.kind_code} item takes no request"
            )
        locked = self._lock(item.project_id, item.id, skip_locked=False)
        # A Wait's row another transaction holds is waited for.
        assert locked is not None
        project, held = locked
        refusal = self.refusals(project, [held])[held.id]
        if refusal is not None:
            raise InvalidOperationException(operation, refusal)
        self._fire(
            held.id,
            held.kind_code,
            FiringCause.REQUESTED,
            datetime.now(UTC),
            requested_by_user_id=person.id,
        )
        self.view_service.timeline_moved(project)

    def refusals(
        self, project: Project, waits: Sequence[Item]
    ) -> dict[uuid.UUID, str | None]:
        """Why each of `project`'s `waits` takes no person's request now
        (F27.3), by its id, none for one that takes it: its project archived
        or finished, the wait done, or Pilot checking, a firing of it pending
        or a run of it in flight (`run_in_flight`)."""
        checking = set(
            self.db.scalars(
                select(Wait.id).where(
                    Wait.id.in_([wait.id for wait in waits]),
                    or_(_pending(Wait.id), run_in_flight(Wait.id)),
                )
            )
        )
        return {wait.id: _refusal(project, wait, wait.id in checking) for wait in waits}

    def firings(self, waits: Sequence[Item]) -> dict[uuid.UUID, list[ShownFiring]]:
        """Each wait's firings in order, by its id, a wait with none left out,
        each with what the brain did with it (`FiringOutcome`), read from the
        run that took it, followed through its Retries, and the wait's close
        (DB Wait Firing): closed where a run of that chain is the Session
        that marked the wait done (DB 199); else Pilot's turn while the
        chain's latest run is in flight (`run_in_flight`), left open once its
        turn ended neither failed nor stopped, and none once it failed or was
        stopped. A firing no run took is Pilot's turn on an open wait, none on
        a done one."""
        by_id = {wait.id: wait for wait in waits}
        runs = {
            row.id: row
            for row in self.db.execute(
                select(
                    Work.id,
                    Work.retried_by_id,
                    AgentSession.state_code,
                    AgentSession.nudge_owed_at,
                )
                .join(AgentSession, AgentSession.id == Work.id)
                .where(
                    Work.trigger_code == WorkTrigger.WAIT_FIRED,
                    Work.trigger_item_id.in_(list(by_id)),
                )
            )
        }
        shown: dict[uuid.UUID, list[ShownFiring]] = {}
        for firing, transition in self.db.execute(
            select(WaitFiring, CardTransition)
            .outerjoin(CardTransition, CardTransition.id == WaitFiring.transition_id)
            .where(WaitFiring.wait_id.in_(list(by_id)))
            .order_by(WaitFiring.wait_id, WaitFiring.seq)
        ):
            wait = by_id[firing.wait_id]
            outcome: FiringOutcome | None
            if firing.job_id is None:
                outcome = FiringOutcome.PILOTS_TURN if wait.done_at is None else None
            else:
                # A Retry of a wait's run is a run of the wait (`JobService`).
                chain = [runs[firing.job_id]]
                while chain[-1].retried_by_id is not None:
                    chain.append(runs[chain[-1].retried_by_id])
                latest = chain[-1]
                if wait.done_cause_code == MARKED and wait.consumed_session_id in {
                    run.id for run in chain
                }:
                    outcome = FiringOutcome.CLOSED
                elif (
                    latest.state_code in _IN_FLIGHT or latest.nudge_owed_at is not None
                ):
                    outcome = FiringOutcome.PILOTS_TURN
                elif latest.state_code in _RESUMABLE:
                    outcome = FiringOutcome.LEFT_OPEN
                else:
                    outcome = None
            shown.setdefault(firing.wait_id, []).append(
                ShownFiring(firing, transition, outcome)
            )
        return shown

    def batches_due(self, cutoff: datetime) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """The waits whose run is due (design 2 §8.2's batcher; F136.4), as
        their project's id and their own, read with no lock: open, of an open,
        unarchived project, with a firing pending since `cutoff` or before,
        and no run in flight (`run_in_flight`). `hold_batch` reads each again
        under its rows."""
        return [
            (project_id, wait_id)
            for project_id, wait_id in self.db.execute(
                select(Item.project_id, Wait.id)
                .join(Item, Item.id == Wait.id)
                .join(Project, Project.id == Item.project_id)
                .where(
                    _firable(),
                    _pending_since(Wait.id, cutoff),
                    ~run_in_flight(Wait.id),
                )
                .order_by(Item.project_id, Wait.id)
            )
        ]

    def hold_batch(
        self, project_id: uuid.UUID, wait_id: uuid.UUID, cutoff: datetime
    ) -> tuple[Project, Item] | None:
        """The wait's Project and Item while its run is due under their rows:
        the Project's held exclusively, as the run's placement takes it
        (`DocumentService.next_seq`), then the Wait's, and read there as
        `batches_due` reads them; else none. A second process reading the
        same batch waits for the first's commit, then finds its run in
        flight: one run per batch."""
        project = self.db.scalars(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        if project.state_code is not ProjectState.OPEN or project.archived:
            return None
        self.db.execute(select(Wait.id).where(Wait.id == wait_id).with_for_update())
        item = self.db.get_one(Item, wait_id, populate_existing=True)
        if item.done_at is not None:
            return None
        if not self.db.scalar(select(_pending_since(wait_id, cutoff))):
            return None
        if self.db.scalar(select(run_in_flight(wait_id))):
            return None
        return project, item

    def take(self, project: Project, work: Work) -> None:
        """Every firing of the wait the run `work` follows still pending, taken
        by it at its brief (DB 191, 196), under the Wait's row after the
        Project's, which the caller holds, so that a firing recorded before
        is taken and one after stays pending for the next run."""
        # A wait's run names its wait (DB 195).
        assert work.trigger_item_id is not None
        self.db.execute(
            select(Wait.id).where(Wait.id == work.trigger_item_id).with_for_update()
        )
        taken = self.db.scalars(
            update(WaitFiring)
            .where(
                WaitFiring.wait_id == work.trigger_item_id,
                WaitFiring.job_id.is_(None),
            )
            .values(job_id=work.id)
            .returning(WaitFiring.id)
        ).all()
        if taken:
            self.view_service.timeline_moved(project)

    def resumed(self, work: Work, at: datetime) -> AgentSession | None:
        """The run whose conversation the wait's run `work`, briefed at `at`,
        resumes (F136.5, DB 200): the wait's previous run, the latest other
        one briefed, while its turn ended `idle` on a conversation within
        `cache_expiration_ttl` before `at`. None past it, after a run that
        failed or was stopped, and for a Retry, a fresh job (D078)."""
        if self.db.scalar(select(exists().where(Work.retried_by_id == work.id))):
            return None
        previous = self.db.scalars(
            select(AgentSession)
            .join(Work, Work.id == AgentSession.id)
            .join(Item, Item.id == Work.id)
            .where(
                Work.trigger_code == WorkTrigger.WAIT_FIRED,
                Work.trigger_item_id == work.trigger_item_id,
                Work.id != work.id,
                AgentSession.turns > 0,
            )
            .order_by(Item.seq.desc())
            .limit(1)
        ).one_or_none()
        if (
            previous is None
            or previous.state_code not in _RESUMABLE
            or previous.conversation_id is None
            or previous.turn_ended_at is None
            or previous.turn_ended_at < at - self.cache_expiration_ttl
        ):
            return None
        return previous

    def _hold(
        self, project_id: uuid.UUID, wait_id: uuid.UUID, *, skip_locked: bool
    ) -> Project | None:
        """The wait's Project, under its rows (`_lock`), the project open and
        unarchived and the wait open there; else none."""
        locked = self._lock(project_id, wait_id, skip_locked=skip_locked)
        if locked is None:
            return None
        project, item = locked
        if (
            project.state_code is not ProjectState.OPEN
            or project.archived
            or item.done_at is not None
        ):
            return None
        return project

    def _lock(
        self, project_id: uuid.UUID, wait_id: uuid.UUID, *, skip_locked: bool
    ) -> tuple[Project, Item] | None:
        """The wait's Project, its row held shared, and its Item, read under
        the Wait's row after it. With `skip_locked`, a Wait's row another
        transaction holds is not taken, and none is returned."""
        project = self.db.scalars(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        ).one()
        taken = self.db.scalar(
            select(Wait.id)
            .where(Wait.id == wait_id)
            .with_for_update(skip_locked=skip_locked)
        )
        if taken is None:
            return None
        return project, self.db.get_one(Item, wait_id, populate_existing=True)

    def _fire(
        self,
        wait_id: uuid.UUID,
        kind: str,
        cause: FiringCause,
        at: datetime,
        *,
        transition_id: int | None = None,
        requested_by_user_id: uuid.UUID | None = None,
    ) -> None:
        """A pending Firing of the Wait, whose row the caller holds, next in
        its order."""
        last = self.db.scalar(
            select(func.max(WaitFiring.seq)).where(WaitFiring.wait_id == wait_id)
        )
        self.db.add(
            WaitFiring(
                wait_id=wait_id,
                wait_kind_code=kind,
                seq=(last or 0) + 1,
                cause_code=cause,
                transition_id=transition_id,
                requested_by_user_id=requested_by_user_id,
                fired_at=at,
            )
        )
        self.db.flush()

    def _moved(self, projects: Iterable[Project]) -> None:
        """Each project's timeline moved, once."""
        for project in {project.id: project for project in projects}.values():
            self.view_service.timeline_moved(project)

    def _item(
        self,
        project: Project,
        session: AgentSession,
        kind: str,
        title: str,
        plan_task_id: str | None,
    ) -> Item:
        item = Item(
            id=uuid.uuid4(),
            project_id=project.id,
            seq=self.document_service.next_seq(project),
            kind_code=kind,
            title=title,
            plan_task_id=plan_task_id,
            created_by_session_id=session.id,
        )
        self.db.add(item)
        self.db.flush()
        return item


def _listed(
    names: Sequence[str], field: str, operation: str, key: Callable[[str], str]
) -> None:
    """Refuses a list of the wait's that is empty, or that names one twice,
    two names the same by `key`."""
    if not names:
        raise InvalidOperationException(operation, f"its `{field}` list is empty")
    seen: set[str] = set()
    twice: list[str] = []
    for name in names:
        if key(name) in seen:
            twice.append(name)
        seen.add(key(name))
    if twice:
        raise InvalidOperationException(
            operation, f"its `{field}` list names {_names(twice)} twice"
        )


def _firable() -> ColumnElement[bool]:
    """A wait the server fires: open, of an open, unarchived project."""
    return and_(
        Item.done_at.is_(None),
        Project.state_code == ProjectState.OPEN,
        Project.archived.is_(False),
    )


def run_in_flight(
    wait_id: SQLColumnExpression[uuid.UUID] | uuid.UUID,
) -> ColumnElement[bool]:
    """Whether a run of the wait is placed and not ended (F136.4): held at the
    gate or queued, starting or running, or failed at the quota wall with its
    nudge owed, which continues it (D078)."""
    return exists().where(
        Work.trigger_code == WorkTrigger.WAIT_FIRED,
        Work.trigger_item_id == wait_id,
        AgentSession.id == Work.id,
        or_(
            AgentSession.state_code.in_(_IN_FLIGHT),
            AgentSession.nudge_owed_at.is_not(None),
        ),
    )


def _refusal(project: Project, wait: Item, checking: bool) -> str | None:
    if project.archived:
        return ARCHIVED
    # A wait is born in an open project (`add_item`), which Finish alone
    # leaves.
    if project.state_code is not ProjectState.OPEN:
        return "its project is finished"
    if wait.done_at is not None:
        return "the wait is done"
    return CHECKING if checking else None


def _pending(
    wait_id: SQLColumnExpression[uuid.UUID] | uuid.UUID,
) -> ColumnElement[bool]:
    """Whether a firing of the wait is pending: no run has taken it."""
    return exists().where(WaitFiring.wait_id == wait_id, WaitFiring.job_id.is_(None))


def _pending_since(
    wait_id: SQLColumnExpression[uuid.UUID] | uuid.UUID, cutoff: datetime
) -> ColumnElement[bool]:
    """Whether a firing of the wait recorded at `cutoff` or before is
    pending: its oldest pending firing is that old."""
    return exists().where(
        WaitFiring.wait_id == wait_id,
        WaitFiring.job_id.is_(None),
        WaitFiring.fired_at <= cutoff,
    )


def _due_fired(
    wait_id: SQLColumnExpression[uuid.UUID] | uuid.UUID,
) -> ColumnElement[bool]:
    """Whether the wait has fired `due` (DB 198)."""
    return exists().where(
        WaitFiring.wait_id == wait_id, WaitFiring.cause_code == FiringCause.DUE
    )


def _names(names: Sequence[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)
