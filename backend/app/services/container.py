"""Dependency injection container for services."""

from collections.abc import Callable
from typing import Any

from dependency_injector import containers, providers
from sqlalchemy.orm import sessionmaker

from app.app_config import AppSettings
from app.config import Settings
from app.engine.bus import EngineBus
from app.engine.documents import DocumentService
from app.engine.ingest import IngestService
from app.engine.plan import PlanService
from app.engine.record import RecordService
from app.engine.tree import TreeService
from app.engine.views import ViewService
from app.exceptions import ConfigurationError
from app.services.auth_service import AuthService
from app.services.controller_client import ControllerClient
from app.services.environment_service import EnvironmentService
from app.services.fake_controller import FakeController
from app.services.fleet_consumer import FleetConsumer
from app.services.frontend_version_service import FrontendVersionService
from app.services.health_service import HealthService
from app.services.link_service import LinkService
from app.services.metrics_service import MetricsService
from app.services.oidc_client_service import OidcClientService
from app.services.people_service import PeopleService
from app.services.project_service import ProjectService
from app.services.relay_service import RelayService
from app.services.relay_watchdog import RelayWatchdog
from app.services.session_record_service import SessionRecordService
from app.services.session_start_service import SessionStartService
from app.services.session_stream_service import SessionStreamService
from app.services.sse_connection_manager import SSEConnectionManager
from app.services.supervisor import Supervisor
from app.services.sync_service import SyncService
from app.services.sync_stream_service import SyncStreamService
from app.services.task_service import TaskService
from app.services.test_data_service import TestDataService
from app.services.testing_service import TestingService
from app.services.testing_sync_service import TestingSyncService
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from app.utils.temp_file_manager import TempFileManager

# Background service startup registry. Services register lambdas here
# (co-located with their provider definitions) that are invoked by
# start_background_services() during app startup.
_background_starters: list[Callable[[Any], None]] = []


def register_for_background_startup(fn: Callable[[Any], None]) -> None:
    """Register a callable to be invoked during background service startup."""
    _background_starters.append(fn)


def start_controller_client(container: "ServiceContainer") -> None:
    """Build the controller's client, which registers its readiness check, when
    a controller is configured.

    Production refuses to start without one. The CLI builds the app without its
    background services and never gets here, so a migration needs no
    controller's settings.
    """
    app_config = container.app_config()
    if container.config().is_production and (
        app_config.controller_url is None or not app_config.controller_token
    ):
        raise ConfigurationError(
            "CONTROLLER_URL and CONTROLLER_TOKEN must be set in production"
        )
    if app_config.controller_url is not None:
        container.controller_client()


class ServiceContainer(containers.DeclarativeContainer):
    """Container for service dependency injection."""

    # The container itself, for a service that opens sessions of its own. An
    # inline providers.Self() argument resolves to None.
    __self__ = providers.Self()

    # Configuration providers
    config = providers.Dependency(instance_of=Settings)
    app_config = providers.Dependency(instance_of=AppSettings)
    session_maker = providers.Dependency(instance_of=sessionmaker)
    db_session = providers.ContextLocalSingleton(session_maker.provided.call())

    # Testing service - test sessions and content generation
    testing_service = providers.Factory(TestingService)

    # Lifecycle coordinator - manages startup and graceful shutdown
    lifecycle_coordinator = providers.Singleton(
        LifecycleCoordinator,
        graceful_shutdown_timeout=config.provided.graceful_shutdown_timeout,
    )

    # Health service - callback registry for health checks
    health_service = providers.Singleton(
        HealthService,
        lifecycle_coordinator=lifecycle_coordinator,
        settings=config,
    )

    # The KubeCoder controller's client (design 2 §14). Its starter is
    # registered before any that starts a thread, so a refusal starts none.
    controller_client = providers.Singleton(
        ControllerClient,
        base_url=app_config.provided.controller_url,
        token=app_config.provided.controller_token,
        health_service=health_service,
        ca_file=app_config.provided.controller_ca_file,
    )
    register_for_background_startup(lambda c: start_controller_client(c))

    # The controller's fake, served under /api/testing/controller in testing mode
    fake_controller = providers.Singleton(
        FakeController, token=app_config.provided.controller_token
    )

    # The supervisor: the long-lived jobs' threads (design 2 §7). Built by its
    # starter so that it hears STARTUP; jobs register on it before then.
    supervisor = providers.Singleton(
        Supervisor,
        container=__self__,
        lifecycle_coordinator=lifecycle_coordinator,
        controller_configured=providers.Callable(
            lambda url: url is not None, app_config.provided.controller_url
        ),
        scheduler_tick_seconds=app_config.provided.scheduler_tick_seconds,
    )
    register_for_background_startup(lambda c: c.supervisor())

    # The fleet consumer keeps the Environment rows current; the environment
    # service starts environments and runs the shutdown timer (design 2 §13).
    # Each registers its job on the supervisor when built, before STARTUP.
    fleet_consumer = providers.Singleton(
        FleetConsumer, container=__self__, supervisor=supervisor
    )
    register_for_background_startup(lambda c: c.fleet_consumer())
    environment_service = providers.Singleton(
        EnvironmentService,
        container=__self__,
        supervisor=supervisor,
        stop_after_seconds=app_config.provided.environment_stop_after_seconds,
    )
    register_for_background_startup(lambda c: c.environment_service())

    # Temp file manager
    temp_file_manager = providers.Singleton(
        TempFileManager,
        lifecycle_coordinator=lifecycle_coordinator,
    )
    register_for_background_startup(
        lambda c: c.temp_file_manager().start_cleanup_thread()
    )

    # Metrics service - background thread for Prometheus metrics
    metrics_service = providers.Singleton(
        MetricsService,
        container=providers.Self(),
        lifecycle_coordinator=lifecycle_coordinator,
    )

    # Auth services - OIDC authentication
    auth_service = providers.Singleton(
        AuthService, config=config, read_role="editor", write_role="editor"
    )
    oidc_client_service = providers.Singleton(OidcClientService, config=config)

    # SSE connection manager (always included - TaskService depends on it)
    sse_connection_manager = providers.Singleton(
        SSEConnectionManager,
        lifecycle_coordinator=lifecycle_coordinator,
        queue_max_frames=config.provided.sse_queue_max_frames,
    )

    # A Session's records and its hubs, the live frames on the browsers'
    # connections (design 2 §10, §11)
    session_stream_service = providers.Singleton(
        SessionStreamService,
        container=__self__,
        sse_connection_manager=sse_connection_manager,
    )
    session_record_service = providers.Factory(
        SessionRecordService, db=db_session, session_streams=session_stream_service
    )

    # The send and the relay (design 2 §9); the relay's job registers on the
    # supervisor when built, before STARTUP.
    relay_service = providers.Singleton(
        RelayService,
        container=__self__,
        supervisor=supervisor,
        session_streams=session_stream_service,
        environment_service=environment_service,
    )
    register_for_background_startup(lambda c: c.relay_service())
    # The relays' watchdog, on the fleet stream (design 2 §9.3); its timer
    # registers on the supervisor when built, before STARTUP.
    relay_watchdog = providers.Singleton(
        RelayWatchdog, supervisor=supervisor, fleet_consumer=fleet_consumer
    )
    register_for_background_startup(lambda c: c.relay_watchdog())

    # The session start (design 2 §13.2); its job registers on the supervisor
    # when built, before STARTUP.
    session_start_service = providers.Singleton(
        SessionStartService,
        container=__self__,
        supervisor=supervisor,
        session_streams=session_stream_service,
        environment_service=environment_service,
        relay_service=relay_service,
        controller_configured=providers.Callable(
            lambda url: url is not None, app_config.provided.controller_url
        ),
    )
    register_for_background_startup(lambda c: c.session_start_service())

    # Task service - in-memory task management
    task_service = providers.Singleton(
        TaskService,
        lifecycle_coordinator=lifecycle_coordinator,
        sse_connection_manager=sse_connection_manager,
        max_workers=config.provided.task_max_workers,
        task_timeout=config.provided.task_timeout_seconds,
        cleanup_interval=config.provided.task_cleanup_interval_seconds,
    )
    register_for_background_startup(lambda c: c.task_service().startup())

    # Frontend version service - SSE version notifications
    frontend_version_service = providers.Singleton(
        FrontendVersionService,
        settings=config,
        lifecycle_coordinator=lifecycle_coordinator,
        sse_connection_manager=sse_connection_manager,
    )
    register_for_background_startup(lambda c: c.frontend_version_service())

    # The engine (design 1 §0): one bus per process, its services per session
    engine_bus = providers.Singleton(EngineBus)
    view_service = providers.Factory(ViewService, db=db_session, engine_bus=engine_bus)
    plan_service = providers.Factory(
        PlanService,
        db=db_session,
        ticket_id_pattern=app_config.provided.ticket_id_pattern,
    )
    tree_service = providers.Factory(
        TreeService, db=db_session, view_service=view_service, plan_service=plan_service
    )
    document_service = providers.Factory(
        DocumentService,
        db=db_session,
        engine_bus=engine_bus,
        tree_service=tree_service,
        view_service=view_service,
    )
    ingest_service = providers.Factory(
        IngestService,
        db=db_session,
        engine_bus=engine_bus,
        tree_service=tree_service,
        view_service=view_service,
        document_service=document_service,
        plan_service=plan_service,
    )
    record_service = providers.Factory(
        RecordService,
        db=db_session,
        document_service=document_service,
        view_service=view_service,
    )

    # The store's sync: the gate and the wire side of the engine (design 1 §5)
    sync_service = providers.Factory(
        SyncService,
        db=db_session,
        app_settings=app_config,
        ingest_service=ingest_service,
        tree_service=tree_service,
        plan_service=plan_service,
    )
    sync_stream_service = providers.Singleton(
        SyncStreamService,
        engine_bus=engine_bus,
        lifecycle_coordinator=lifecycle_coordinator,
    )
    testing_sync_service = providers.Factory(
        TestingSyncService,
        db=db_session,
        engine_bus=engine_bus,
        record_service=record_service,
        tree_service=tree_service,
    )

    # The signed-in person on the record (F137), and what links in text (F93)
    people_service = providers.Factory(PeopleService, db=db_session)
    link_service = providers.Factory(LinkService, db=db_session)

    # The projects as the signed-in person reads them (F1, F2, F3), and their
    # transitions and membership (F4.1, F5, F6, F127, F128)
    project_service = providers.Factory(
        ProjectService,
        db=db_session,
        people_service=people_service,
        record_service=record_service,
        view_service=view_service,
    )

    # The invented record: the dev stack's seed, loaded by `cli
    # load-test-data`, and the states a spec makes through /api/testing/
    test_data_service = providers.Factory(
        TestDataService,
        db=db_session,
        document_service=document_service,
        record_service=record_service,
        plan_service=plan_service,
        people_service=people_service,
    )


def start_background_services(container: Any) -> None:
    """Eagerly instantiate and start all registered background services."""
    for starter in _background_starters:
        starter(container)
