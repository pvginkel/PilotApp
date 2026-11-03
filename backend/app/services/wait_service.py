"""The waits (DB decision 46, F27): a card wait or a timed wait added by the
brain, fixed at add (F27.6), fired by the server (F136.2, F27.2), and closed by
its own `done` with a note (F27.4, DB 300) or by Finish's close of the open
items, which writes none.

Each write is of the caller's transaction, under its Project's row: a wait's
birth takes its `seq` under it (`DocumentService.next_seq`), its close holds
the Wait's row after it, and a firing holds the Project's row shared, then the
Wait's, and reads the wait open there.
"""

import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, SQLColumnExpression, and_, exists, func, select
from sqlalchemy.orm import Session

from app.engine.documents import DocumentService
from app.engine.record import ARCHIVED, MARKED
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException
from app.models import CardTransition, Item, Project, User, Wait, WaitFiring
from app.models import Session as AgentSession
from app.models.reference import FiringCause, ProjectState

CARD_WAIT = "card_wait"
TIMED_WAIT = "timed_wait"
WAITS = (CARD_WAIT, TIMED_WAIT)
"""The Item Kinds of form `wait` (DB assertion 185)."""


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


class WaitService:
    def __init__(
        self,
        db: Session,
        document_service: DocumentService,
        view_service: ViewService,
        ticket_id_pattern: re.Pattern[str],
    ) -> None:
        self.db = db
        self.document_service = document_service
        self.view_service = view_service
        self.ticket_id_pattern = ticket_id_pattern

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
        note set with its `done_at` (DB 300). `project`'s row is the
        caller's to hold.

        Raises:
            InvalidOperationException: the project is archived, or the wait
                is done.
        """
        operation = f"mark item {wait.id} done"
        if project.archived:
            raise InvalidOperationException(operation, ARCHIVED)
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

    def _hold(
        self, project_id: uuid.UUID, wait_id: uuid.UUID, *, skip_locked: bool
    ) -> Project | None:
        """The wait's Project, its row held shared and the Wait's after it,
        when both are taken and read there, the project open and unarchived
        and the wait open; else none. With `skip_locked`, a Wait's row
        another transaction holds is not taken."""
        project = self.db.scalars(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        ).one()
        if project.state_code is not ProjectState.OPEN or project.archived:
            return None
        taken = self.db.scalar(
            select(Wait.id)
            .where(Wait.id == wait_id)
            .with_for_update(skip_locked=skip_locked)
        )
        if taken is None:
            return None
        item = self.db.get_one(Item, wait_id, populate_existing=True)
        return project if item.done_at is None else None

    def _fire(
        self,
        wait_id: uuid.UUID,
        kind: str,
        cause: FiringCause,
        at: datetime,
        *,
        transition_id: int | None = None,
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


def _due_fired(
    wait_id: SQLColumnExpression[uuid.UUID] | uuid.UUID,
) -> ColumnElement[bool]:
    """Whether the wait has fired `due` (DB 198)."""
    return exists().where(
        WaitFiring.wait_id == wait_id, WaitFiring.cause_code == FiringCause.DUE
    )


def _names(names: Sequence[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)
