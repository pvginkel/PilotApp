"""The environment a call to Pilot's projects surface came from, by its name
(F150.1): Pilot's own row's, else the controller's report's."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core_exceptions import ExternalServiceException
from app.models import Environment
from app.services.controller_client import ControllerClient

CALLER_ENVIRONMENT_HEADER = "X-Pilot-Environment"
"""The header of a request Pilot's MCP process makes for a call to its
projects surface: the id of the environment the call came from, as the
caller's own header gave it; absent where the caller sent none (F150.1)."""


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
        if not self._controller_configured:
            return env_id
        try:
            report = self._controller_client().get_environment(env_id)
        except ExternalServiceException:
            return env_id
        return report.name or env_id
