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
from app.services.auth_service import AuthService
from app.services.frontend_version_service import FrontendVersionService
from app.services.health_service import HealthService
from app.services.metrics_service import MetricsService
from app.services.oidc_client_service import OidcClientService
from app.services.sse_connection_manager import SSEConnectionManager
from app.services.task_service import TaskService
from app.services.test_data_service import TestDataService
from app.services.testing_service import TestingService
from app.utils.lifecycle_coordinator import LifecycleCoordinator
from app.utils.temp_file_manager import TempFileManager

# Background service startup registry. Services register lambdas here
# (co-located with their provider definitions) that are invoked by
# start_background_services() during app startup.
_background_starters: list[Callable[[Any], None]] = []


def register_for_background_startup(fn: Callable[[Any], None]) -> None:
    """Register a callable to be invoked during background service startup."""
    _background_starters.append(fn)


class ServiceContainer(containers.DeclarativeContainer):
    """Container for service dependency injection."""

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

    # The dev stack's seed, loaded by `cli load-test-data`
    test_data_service = providers.Factory(
        TestDataService,
        db=db_session,
        document_service=document_service,
        record_service=record_service,
        plan_service=plan_service,
    )


def start_background_services(container: Any) -> None:
    """Eagerly instantiate and start all registered background services."""
    for starter in _background_starters:
        starter(container)
