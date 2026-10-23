"""A work item's status, live on every browser (F80.2's work status).

Every writer of a work Session's state, its current line, its `started_at` or
its `error` calls `work_moved` in its transaction. Once that commits the bus
carries `WorkMoved`, which the browsers hear as the item's work status alone,
read again with nothing else of the project's screens: sized for the relay,
which moves the line on most records it writes. A move of the state, which
moves the project's tab and head too, a badge's count among them, carries
`ProjectChanged` with it.
"""

from app.engine.bus import EngineBus, ProjectChanged, WorkMoved
from app.models import Session as AgentSession

_WORK_KINDS = ("work", "job")
"""The Session Kinds a Work has (`ck_work_session_kind`); a Chat's Session has
no work item."""


def work_moved(bus: EngineBus, session: AgentSession, *, state: bool = False) -> None:
    """Tell the browsers, once the transaction commits, that what the
    Session's work item shows on its line moved; with `state`, that its state
    moved. Equal events of one transaction go out once."""
    if session.kind_code not in _WORK_KINDS:
        return
    bus.emit(WorkMoved(session.project_id, session.id))
    if state:
        bus.emit(ProjectChanged(session.project_id))
