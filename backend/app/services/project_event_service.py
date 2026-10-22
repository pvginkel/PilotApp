"""A project's live event on the browsers' SSE connections (F80.2; design 2
§6.2): once a change to what its timeline, head or tab shows commits, every
person's connections hear of it, as one event naming the project.

Every person sees every project (F105), so the event names every person by
their subject (SSE-2). A person is a user who has chosen a handle; before
that, the app shows no project.

Only the process that holds a connection delivers to it: an event sent from
another pod reaches nobody there (design 2 §8.1).
"""

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.bus import EngineBus, EngineEvent, ProjectChanged
from app.models import User
from app.models.reference import UserKind
from app.services.sse_connection_manager import SSEConnectionManager, Target

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

EVENT_NAME = "project_changed"
"""The SSE event a project's change travels as, `{"project_id": <id>}`."""


class ProjectEventService:
    """A subscriber of the engine's bus, from its construction on."""

    def __init__(
        self,
        container: "ServiceContainer",
        engine_bus: EngineBus,
        sse_connection_manager: SSEConnectionManager,
    ) -> None:
        self._container = container
        self._manager = sse_connection_manager
        engine_bus.subscribe(self.deliver)

    def deliver(self, event: EngineEvent) -> None:
        """Send a `ProjectChanged` to every person's connections."""
        if not isinstance(event, ProjectChanged):
            return
        with self._open_session() as db:
            subjects = db.scalars(
                select(User.subject)
                .where(User.kind_code == UserKind.PERSON)
                .order_by(User.subject)
            ).all()
        payload = {"project_id": str(event.project_id)}
        for subject in subjects:
            # A person's row has a subject (`ck_users_person`).
            assert subject is not None
            self._manager.send_event(
                Target.subject(subject), payload, EVENT_NAME, "project"
            )

    def _open_session(self) -> Session:
        # Not `scoped_session`: the bus delivers inside
        # `run_after_commit_callbacks()`, whose callbacks are still
        # registered, and its exit would run them again.
        session: Session = self._container.session_maker()()
        return session
