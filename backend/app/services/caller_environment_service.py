"""The environment a call to Pilot's projects surface came from (F150.1): its
name, Pilot's own row's, else the controller's report's; and its row, which
a Conversation opened from it names (DB decision 77)."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.models import Environment
from app.services.controller_client import ControllerClient, ControllerEnvironment
from app.services.environment_service import reported_columns

CALLER_ENVIRONMENT_HEADER = "X-Pilot-Environment"
"""The header of a request Pilot's MCP process makes for a call to its
projects surface: the id of the environment the call came from, as the
caller's own header gave it; absent where the caller sent none (F150.1)."""

CALLER_SESSION_HEADER = "X-Pilot-Session"
"""The header beside it: the name of the caller's session in that
environment, shown and never checked; absent where the caller sent none
(F150.1, F150.11)."""


class CallerEnvironmentService:
    def __init__(
        self,
        db: Session,
        controller_client: Callable[[], ControllerClient],
        controller_configured: bool,
    ) -> None:
        """
        Args:
            controller_client: Builds the controller's client, at the call
            controller_configured: False asks the controller nothing
        """
        self.db = db
        self._controller_client = controller_client
        self._controller_configured = controller_configured

    def name(self, env_id: str) -> str:
        """The name of the environment `env_id`, which a call's header gave:
        its Environment row's, else the one the controller reports, else the
        id itself. The id names an environment neither knows, one of another
        fleet's controller among them, one the controller reports without a
        name, and any while no controller is configured or the controller
        does not answer: a call is never refused for where it came from.

        No row is written: the environment of a call that starts a draft is
        in the brief's words alone (DB decision 77).
        """
        row = self.db.get(Environment, env_id)
        if row is not None:
            return row.name
        report = self._report(env_id)
        return env_id if report is None else report.name or env_id

    def reported(self, env_id: str) -> ControllerEnvironment | None:
        """The controller's report on the environment `env_id` a Conversation
        is opened from, for the row Pilot does not have of it yet (`row`):
        None where Pilot has its row, and for an environment the controller
        does not know, one of another fleet's controller among them, and any
        while no controller is configured or the controller does not answer.
        The opening asks before it takes a lock: no controller call is made
        under one."""
        if self.db.get(Environment, env_id) is not None:
            return None
        return self._report(env_id)

    def row(self, env_id: str, report: ControllerEnvironment | None) -> Environment:
        """The Environment row of the environment `env_id` a Conversation is
        opened from, written at the first call from it, in the caller's
        transaction (DB Environment; 331): from `report` (`reported`), its
        name with it, and with none, named by its id, a call never refused
        for where it came from; the fleet stream keeps it current as it does
        every row. A row that exists is left as it is. Never one of Pilot's
        own: no start takes it, and the server resets, stops and deletes
        nothing of it."""
        columns = (
            {"name": env_id, "exempt": False}
            if report is None
            else reported_columns(report, datetime.now(UTC))
        )
        self.db.execute(
            insert(Environment)
            .values(id=env_id, **columns)
            .on_conflict_do_nothing(index_elements=[Environment.id])
        )
        return self.db.get_one(Environment, env_id)

    def _report(self, env_id: str) -> ControllerEnvironment | None:
        """The controller's report on the environment; None for one it does
        not know, while it does not answer and while none is configured."""
        if not self._controller_configured:
            return None
        try:
            return self._controller_client().get_environment(env_id)
        except ExternalServiceException:
            return None
