"""Request diagnostics service for performance profiling.

Tracks per-request timing, query counts, and query durations to help
identify slow endpoints and N+1 query issues.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from flask import Flask, g, request
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import event
from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class QueryInfo:
    """Information about a single query execution."""
    sql: str
    duration_ms: float
    parameters: Any = None


@dataclass
class RequestDiagnostics:
    """Diagnostics data collected during a single request."""
    start_time: float = field(default_factory=time.perf_counter)
    queries: list[QueryInfo] = field(default_factory=list)

    # Track query timing within a single query
    _query_start: float | None = field(default=None, repr=False)
    _query_sql: str | None = field(default=None, repr=False)
    _query_params: Any = field(default=None, repr=False)

    @property
    def query_count(self) -> int:
        """Number of queries executed."""
        return len(self.queries)

    @property
    def total_query_time_ms(self) -> float:
        """Total time spent in database queries (ms)."""
        return sum(q.duration_ms for q in self.queries)

    @property
    def request_duration_ms(self) -> float:
        """Total request duration so far (ms)."""
        return (time.perf_counter() - self.start_time) * 1000

    @property
    def python_time_ms(self) -> float:
        """Time spent in Python code (not in DB) (ms)."""
        return self.request_duration_ms - self.total_query_time_ms


class DiagnosticsService:
    """Service for collecting request and query performance diagnostics.

    When enabled, this service:
    - Times every HTTP request and exposes histograms by endpoint
    - Counts queries per request to detect N+1 issues
    - Times individual queries to find slow queries
    - Logs warnings for slow requests and queries
    - Exposes all data via Prometheus metrics
    """

    def __init__(self, settings: "Settings"):
        self.settings = settings
        self.enabled = settings.diagnostics_enabled
        self.slow_query_threshold_ms = settings.diagnostics_slow_query_threshold_ms
        self.slow_request_threshold_ms = settings.diagnostics_slow_request_threshold_ms
        self.log_all_queries = settings.diagnostics_log_all_queries

        # Thread-local storage for non-request contexts (background threads)
        self._local = threading.local()

        # Initialize Prometheus metrics
        self._init_metrics()

    def _init_metrics(self) -> None:
        """Initialize Prometheus metric collectors."""
        # Request-level metrics
        self.request_duration_seconds = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['method', 'endpoint', 'status'],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
        )

        self.request_query_count = Histogram(
            'http_request_query_count',
            'Number of database queries per HTTP request',
            ['method', 'endpoint'],
            buckets=(1, 2, 3, 5, 10, 20, 50, 100)
        )

        self.request_query_time_seconds = Histogram(
            'http_request_query_time_seconds',
            'Total database query time per HTTP request',
            ['method', 'endpoint'],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
        )

        self.request_python_time_seconds = Histogram(
            'http_request_python_time_seconds',
            'Time spent in Python code (not DB) per request',
            ['method', 'endpoint'],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
        )

        # Query-level metrics
        self.query_duration_seconds = Histogram(
            'db_query_duration_seconds',
            'Individual database query duration',
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
        )

        self.slow_query_total = Counter(
            'db_slow_query_total',
            'Total number of slow queries detected'
        )

        self.slow_request_total = Counter(
            'http_slow_request_total',
            'Total number of slow requests detected',
            ['method', 'endpoint']
        )

        # Current state gauges (for dashboards)
        self.active_requests = Gauge(
            'http_active_requests',
            'Number of requests currently being processed'
        )

    def init_app(self, app: Flask, engine: Engine) -> None:
        """Initialize diagnostics hooks on Flask app and SQLAlchemy engine.

        Args:
            app: Flask application instance
            engine: SQLAlchemy engine to instrument
        """
        if not self.enabled:
            logger.info("Request diagnostics disabled (set DIAGNOSTICS_ENABLED=true to enable)")
            return

        logger.info(
            "Request diagnostics enabled: slow_query=%dms slow_request=%dms log_all=%s",
            self.slow_query_threshold_ms,
            self.slow_request_threshold_ms,
            self.log_all_queries
        )

        # Register Flask hooks
        app.before_request(self._before_request)
        app.after_request(self._after_request)

        # Register SQLAlchemy hooks
        event.listen(engine, "before_cursor_execute", self._before_cursor_execute)
        event.listen(engine, "after_cursor_execute", self._after_cursor_execute)

    def _get_diagnostics(self) -> RequestDiagnostics | None:
        """Get the current request's diagnostics data."""
        # Try Flask's g first (for request context)
        try:
            return getattr(g, '_diagnostics', None)
        except RuntimeError:
            # Outside request context, use thread-local
            return getattr(self._local, 'diagnostics', None)

    def _set_diagnostics(self, diag: RequestDiagnostics | None) -> None:
        """Set diagnostics data for current context."""
        try:
            g._diagnostics = diag
        except RuntimeError:
            self._local.diagnostics = diag

    def _before_request(self) -> None:
        """Called before each request - initialize diagnostics."""
        self._set_diagnostics(RequestDiagnostics())
        self.active_requests.inc()

    def _after_request(self, response: Any) -> Any:
        """Called after each request - record metrics and log if slow."""
        diag = self._get_diagnostics()
        if diag is None:
            return response

        self.active_requests.dec()

        # Get endpoint name (use rule if available, else path)
        endpoint = request.endpoint or request.path
        method = request.method
        status = str(response.status_code)

        duration_s = diag.request_duration_ms / 1000
        query_time_s = diag.total_query_time_ms / 1000
        python_time_s = diag.python_time_ms / 1000

        # Record Prometheus metrics
        self.request_duration_seconds.labels(
            method=method, endpoint=endpoint, status=status
        ).observe(duration_s)

        self.request_query_count.labels(
            method=method, endpoint=endpoint
        ).observe(diag.query_count)

        self.request_query_time_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(query_time_s)

        self.request_python_time_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(python_time_s)

        # Log slow requests
        if diag.request_duration_ms >= self.slow_request_threshold_ms:
            self.slow_request_total.labels(method=method, endpoint=endpoint).inc()
            logger.warning(
                "SLOW REQUEST %s %s: %.1fms total (%.1fms db, %.1fms python, %d queries)",
                method,
                request.path,
                diag.request_duration_ms,
                diag.total_query_time_ms,
                diag.python_time_ms,
                diag.query_count
            )

            # Log query breakdown for slow requests
            if diag.queries:
                sorted_queries = sorted(diag.queries, key=lambda q: q.duration_ms, reverse=True)
                for i, q in enumerate(sorted_queries[:5]):  # Top 5 slowest
                    logger.warning(
                        "  Query %d: %.1fms - %s",
                        i + 1,
                        q.duration_ms,
                        q.sql[:200] + "..." if len(q.sql) > 200 else q.sql
                    )

        return response

    def _before_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool
    ) -> None:
        """Called before each query execution."""
        diag = self._get_diagnostics()
        if diag is None:
            return

        diag._query_start = time.perf_counter()
        diag._query_sql = statement
        diag._query_params = parameters

    def _after_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool
    ) -> None:
        """Called after each query execution."""
        diag = self._get_diagnostics()
        if diag is None or diag._query_start is None:
            return

        duration_ms = (time.perf_counter() - diag._query_start) * 1000

        # Record query info
        query_info = QueryInfo(
            sql=statement,
            duration_ms=duration_ms,
            parameters=parameters
        )
        diag.queries.append(query_info)

        # Record Prometheus metric
        self.query_duration_seconds.observe(duration_ms / 1000)

        # Log slow queries
        if duration_ms >= self.slow_query_threshold_ms:
            self.slow_query_total.inc()
            logger.warning(
                "SLOW QUERY (%.1fms): %s",
                duration_ms,
                statement[:500] + "..." if len(statement) > 500 else statement
            )
        elif self.log_all_queries:
            logger.debug(
                "QUERY (%.1fms): %s",
                duration_ms,
                statement[:200] + "..." if len(statement) > 200 else statement
            )

        # Reset for next query
        diag._query_start = None
        diag._query_sql = None
        diag._query_params = None
