"""The hub: a Session's live frames on the browsers' SSE connections (design 2
§11.1, §11.3; F40.3's stream).

A browser's view of a Session subscribes its one connection to the Session's
channel; its history it reads by REST. There is one hub per Session with a
view on this process: it holds the views per connection and a cursor, the last
`seq` it pushed. A wake carries no record: the hub reads the records after its
cursor through the one read function and pushes them in order, so a record is
pushed once and after its commit, whichever writer's wake comes first.

Only the process that holds a connection delivers to it (§11.1): a subscribe
for a connection this process does not hold is refused, and the browser
retries.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from prometheus_client import Gauge
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import AuthorizationException, InvalidOperationException
from app.models import Session as AgentSession
from app.services.session_record_service import (
    STREAM_ENDED_STATES,
    last_record,
    read_records,
    to_record_schema,
)
from app.services.sse_connection_manager import SSEConnectionManager, Target

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)

EVENT_NAME = "session"
"""The SSE event every frame of a session stream travels as."""

_PAGE = 200

STREAM_VIEWS = Gauge(
    "pilot_stream_views",
    "Open views of session streams on this process's SSE connections",
)


def session_channel(session_id: uuid.UUID) -> str:
    """The SSE channel a Session's live frames go out on."""
    return f"session:{session_id}"


class StreamNotConnectedException(InvalidOperationException):
    """This process holds no SSE connection under the request id: the browser's
    stream is on another pod, or has just dropped (409 not-connected)."""

    def __init__(self, request_id: str) -> None:
        super().__init__(
            f"subscribe SSE connection {request_id} to a session stream",
            "this process holds no SSE connection under that request id",
        )
        self.error_code = "NOT_CONNECTED"


class _Hub:
    """One Session's views and cursor. The views change under the service's
    lock; the passes run under the hub's own."""

    def __init__(self, session_id: uuid.UUID) -> None:
        self.session_id = session_id
        self.views: dict[str, set[str]] = {}
        self.lock = threading.Lock()
        # None until the first pass or subscribe reads the Session's last record
        self.cursor: int | None = None
        self.end_pushed = False


@dataclass(frozen=True)
class _Wake:
    # `after_commit()` runs a callback equal to one it holds once.
    streams: "SessionStreamService"
    session_id: uuid.UUID

    def __call__(self) -> None:
        self.streams.wake(self.session_id)


class SessionStreamService:
    """The hubs of this process, and the views browsers subscribe."""

    def __init__(
        self,
        container: "ServiceContainer",
        sse_connection_manager: SSEConnectionManager,
    ) -> None:
        """Drop a connection's views when it goes, or is replaced.

        Args:
            container: Gives each pass a database session of its own
            sse_connection_manager: The browsers' connections
        """
        self._container = container
        self._manager = sse_connection_manager
        self._lock = threading.Lock()
        self._hubs: dict[uuid.UUID, _Hub] = {}
        # A replaced connection fires the connect observer alone (§11.1).
        sse_connection_manager.register_on_connect(self._drop_connection)
        sse_connection_manager.register_on_disconnect(self._drop_connection)

    def subscribe(
        self, session_id: uuid.UUID, request_id: str, view: str, subject: str | None
    ) -> None:
        """Add the view on the caller's connection, which then receives the
        Session's live frames until its last view of the Session goes.

        Args:
            subject: The caller's subject

        Raises:
            StreamNotConnectedException: This process holds no connection under
                `request_id`
            AuthorizationException: The connection is another user's (SSE-6)
        """
        self._check_connection(request_id, subject)
        with self._lock:
            hub = self._hubs.get(session_id)
            if hub is None:
                hub = self._hubs[session_id] = _Hub(session_id)
            hub.views.setdefault(request_id, set()).add(view)
            # Under the lock that the observers take: a connection that goes
            # after this drops the view, one gone before it is refused here.
            subscribed = self._manager.subscribe(
                request_id, session_channel(session_id)
            )
            if not subscribed:
                self._discard(session_id, request_id, view)
            self._count_views()
        if not subscribed:
            raise StreamNotConnectedException(request_id)
        with hub.lock:
            if hub.cursor is None:
                with self._open_session() as db:
                    self._prime(db, hub)

    def unsubscribe(
        self, session_id: uuid.UUID, request_id: str, view: str, subject: str | None
    ) -> None:
        """Drop the view; once the connection holds no view of the Session, it
        leaves the Session's channel. Idempotent.

        Args:
            subject: The caller's subject

        Raises:
            AuthorizationException: The connection is another user's (SSE-6)
        """
        info = self._manager.get_connection_info(request_id)
        if info is not None:
            self._check_owner(request_id, info.subject, info.local_admin, subject)
        with self._lock:
            self._discard(session_id, request_id, view)
            hub = self._hubs.get(session_id)
            if hub is None or request_id not in hub.views:
                self._manager.unsubscribe(request_id, session_channel(session_id))
            self._count_views()

    def waker(self, session_id: uuid.UUID) -> Callable[[], None]:
        """The `after_commit()` callback that wakes the Session's hub; the
        writers of a transaction share one.

        The record writer registers it. A transaction that ends a Session's
        stream without writing a record must register it too, or the views
        never receive `end`.
        """
        return _Wake(self, session_id)

    def wake(self, session_id: uuid.UUID) -> None:
        """Push the Session's records after the hub's cursor, then `end` once
        its stream has ended. Nothing without a hub."""
        hub = self._hub(session_id)
        if hub is not None:
            self._pass(hub, partial=None)

    def forward_partial(self, session_id: uuid.UUID, line: dict[str, Any]) -> bool:
        """Push a `stream_event` line to the Session's views as a `partial`,
        after the records before it.

        Returns:
            False when the Session has no hub, and the line went nowhere
        """
        hub = self._hub(session_id)
        if hub is None:
            return False
        self._pass(hub, partial=line)
        return True

    def _hub(self, session_id: uuid.UUID) -> _Hub | None:
        with self._lock:
            return self._hubs.get(session_id)

    def _pass(self, hub: _Hub, partial: dict[str, Any] | None) -> None:
        with hub.lock:
            with self._open_session() as db:
                # The state is read before the records, so `end` follows every
                # record committed before the stream ended.
                state = db.scalar(
                    select(AgentSession.state_code).where(
                        AgentSession.id == hub.session_id
                    )
                )
                cursor = self._prime(db, hub)
                while True:
                    page = read_records(db, hub.session_id, after=cursor, limit=_PAGE)
                    for stored in page:
                        frame = to_record_schema(stored).model_dump(mode="json")
                        self._push(hub, "record", frame)
                        cursor = hub.cursor = stored.record.seq
                    if len(page) < _PAGE:
                        break
            if partial is not None:
                self._push(hub, "partial", partial)
            if state in STREAM_ENDED_STATES and not hub.end_pushed:
                self._push(hub, "end", None)
                hub.end_pushed = True

    def _prime(self, db: Session, hub: _Hub) -> int:
        """The hub's cursor; a new hub's is set to the Session's last record:
        what came before it, a view reads by REST."""
        if hub.cursor is None:
            last = last_record(db, hub.session_id)
            hub.cursor = 0 if last is None else last.record.seq
        return hub.cursor

    def _push(self, hub: _Hub, frame: str, data: dict[str, Any] | None) -> None:
        payload: dict[str, Any] = {"session": str(hub.session_id), "frame": frame}
        if data is not None:
            payload["data"] = data
        self._manager.send_event(
            Target.channel(session_channel(hub.session_id)),
            payload,
            EVENT_NAME,
            "session",
        )

    def _open_session(self) -> Session:
        # Not `scoped_session`: a pass runs inside `run_after_commit_callbacks()`,
        # whose callbacks are still registered, and its exit would run them,
        # this wake included, again.
        session: Session = self._container.session_maker()()
        return session

    def _check_connection(self, request_id: str, subject: str | None) -> None:
        info = self._manager.get_connection_info(request_id)
        if info is None:
            raise StreamNotConnectedException(request_id)
        self._check_owner(request_id, info.subject, info.local_admin, subject)

    @staticmethod
    def _check_owner(
        request_id: str,
        connection_subject: str | None,
        local_admin: bool,
        subject: str | None,
    ) -> None:
        if not (local_admin or (subject is not None and connection_subject == subject)):
            raise AuthorizationException(
                f"SSE connection {request_id} is not the caller's"
            )

    def _drop_connection(self, request_id: str) -> None:
        with self._lock:
            for session_id in list(self._hubs):
                hub = self._hubs[session_id]
                hub.views.pop(request_id, None)
                if not hub.views:
                    del self._hubs[session_id]
            self._count_views()

    def _discard(self, session_id: uuid.UUID, request_id: str, view: str) -> None:
        # Under the lock
        hub = self._hubs.get(session_id)
        if hub is None:
            return
        views = hub.views.get(request_id)
        if views is not None:
            views.discard(view)
            if not views:
                del hub.views[request_id]
        if not hub.views:
            del self._hubs[session_id]

    def _count_views(self) -> None:
        # Under the lock
        STREAM_VIEWS.set(
            sum(
                len(views)
                for hub in self._hubs.values()
                for views in hub.views.values()
            )
        )
