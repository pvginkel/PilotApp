"""The waits (DB decision 46, F27): a card wait or a timed wait added by the
brain, fixed at add (F27.6), and closed by its own `done` with a note (F27.4,
DB 300) or by Finish's close of the open items, which writes none.

Each write is of the caller's transaction, under its Project's row: a wait's
birth takes its `seq` under it (`DocumentService.next_seq`), and its close
holds the Wait's row after it.
"""

import re
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.documents import DocumentService
from app.engine.record import ARCHIVED, MARKED
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException
from app.models import Item, Project, User, Wait
from app.models import Session as AgentSession

CARD_WAIT = "card_wait"
TIMED_WAIT = "timed_wait"
WAITS = (CARD_WAIT, TIMED_WAIT)
"""The Item Kinds of form `wait` (DB assertion 185)."""


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


def _names(names: Sequence[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)
