"""The session start on a supervisor of its own, a controller configured, for
the tests that place work items through a surface of Pilot's: its loops never
run, and its creates hand no MCP server."""

from app.services.container import ServiceContainer
from app.services.environment_service import EnvironmentService
from app.services.pilot_server import PilotServer
from app.services.relay_service import RelayService
from app.services.session_start_service import SessionStartService
from app.services.start_gate import WorkSlots
from app.services.turn_end_read_service import TurnEndReadService
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID
from tests.support.supervisor import Supervise


def configured_starts(
    container: ServiceContainer, supervise: Supervise, *, project_max: int = 3
) -> SessionStartService:
    """The start on the container's outage and a slot of its own, of
    `project_max` work items per project."""
    supervisor, _ = supervise(container)
    environments = EnvironmentService(
        container=container,
        supervisor=supervisor,
        stop_after_seconds=1800,
        delete_after_seconds=604800,
    )
    slots = WorkSlots(work_max=3, project_max=project_max)
    pilot_server = PilotServer(None)
    relays = RelayService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        work_slots=slots,
        pilot_server=pilot_server,
        turn_end_reads=TurnEndReadService(
            container=container,
            supervisor=supervisor,
            session_streams=container.session_stream_service(),
        ),
    )
    return SessionStartService(
        container=container,
        supervisor=supervisor,
        session_streams=container.session_stream_service(),
        environment_service=environments,
        relay_service=relays,
        controller_outage=container.controller_outage(),
        work_slots=slots,
        pilot_server=pilot_server,
        controller_configured=True,
        store_environment_id=STORE_ENVIRONMENT_ID,
    )
