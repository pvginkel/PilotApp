"""Infrastructure test fixtures for the test suite.

This module contains all infrastructure fixtures (app factory, database,
client, session, OIDC) that the template owns. App-specific fixtures
(domain objects, domain builders) live in conftest.py.

The suite runs on PostgreSQL. At session start it builds one template database
for the run with the Alembic revisions, in production's locale, and every
database a test runs on is a clone of it. Tests come in two tiers:

- **Rollback, the default.** The session-scoped ``app`` runs on the run's main
  database. Each test's ``session`` lives in a transaction that is rolled back
  at teardown, and ``container`` and ``client`` hand that session to services
  and requests, so nothing a test writes outlives it. ``commit()`` and
  ``rollback()`` are real (the session runs on savepoints), so after-commit
  callbacks run as in production; only ``close()`` is a no-op.
- **A database of its own.** ``committed_app`` is an app on a fresh clone,
  for tests whose commits must be seen by another connection: other threads,
  row locks, code that opens its own sessions.

The server is ``TEST_DATABASE_ADMIN_URL``, by default the environment's
``postgres`` sidecar. The suite uses its maintenance database and the
databases it creates, nothing else.
"""

import itertools
import os
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv
from flask import Flask
from prometheus_client import REGISTRY
from psycopg.errors import ObjectInUse
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app import create_app
from app.app_config import AppSettings
from app.config import TEST_DB_POOL_MAX_OVERFLOW, TEST_DB_POOL_SIZE, Settings
from app.database import upgrade_database
from app.extensions import db
from app.services.container import ServiceContainer
from app.startup import post_migration_hook

# .env holds the base configuration and .env.test overrides it for tests: the
# same two layers scripts/testing-server.sh gives the Playwright backends.
_PROJECT_ROOT = Path(__file__).parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
_TEST_ENV_FILE = _PROJECT_ROOT / ".env.test"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
if _TEST_ENV_FILE.exists():
    load_dotenv(_TEST_ENV_FILE, override=True)

# The server the suite creates its databases on: the environment's postgres
# sidecar locally, the validation Job's postgres container in CI. Keep in step
# with scripts/wait-for-services.py.
_DEFAULT_ADMIN_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"

# Every database the suite creates is named <prefix><run id>_<name>.
_DATABASE_PREFIX = "pilot_test_"

# Production's locale: the clusters are initialised with ICU 'und' and C. The
# server's default (libc en_US.utf8 on the sidecar) sorts text differently.
_DATABASE_LOCALE = (
    "ENCODING 'UTF8' LOCALE_PROVIDER icu ICU_LOCALE 'und' LC_COLLATE 'C' LC_CTYPE 'C'"
)


def _admin_url() -> URL:
    return make_url(os.environ.get("TEST_DATABASE_ADMIN_URL", _DEFAULT_ADMIN_URL))


def _database_url(name: str) -> str:
    """The URL of a database on the suite's server.

    Rendered with its password: ``str(url)`` masks it, and an app built from
    the masked URL cannot log in.
    """
    return _admin_url().set(database=name).render_as_string(hide_password=False)


def pytest_configure(config: pytest.Config) -> None:
    """Verify required infrastructure is available before running any tests.

    Checks PostgreSQL connectivity at session start and aborts with a
    clear message if a service is unreachable. This prevents confusing
    scattered errors throughout the suite.

    PostgreSQL is the server at ``TEST_DATABASE_ADMIN_URL``.
    """
    admin_url = _admin_url()
    engine = create_engine(
        admin_url, poolclass=NullPool, connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect():
            pass
    except DBAPIError as exc:
        pytest.exit(
            "PostgreSQL is not reachable at "
            f"{admin_url.render_as_string(hide_password=True)}: {exc.orig}. "
            "Set TEST_DATABASE_ADMIN_URL to a server the suite may create "
            "databases on.",
            returncode=1,
        )
    finally:
        engine.dispose()


def _clear_prometheus_registry() -> None:
    """Unregister every collector from the Prometheus registry."""
    for collector in list(REGISTRY._collector_to_names.keys()):
        try:
            REGISTRY.unregister(collector)
        except (KeyError, ValueError):
            # Collector may have already been unregistered or not exist
            pass


@pytest.fixture
def clear_prometheus_registry() -> Generator[None]:
    """Clear the Prometheus registry before and after a test.

    Not autouse: the session app's metrics are registered once, and clearing
    after every test would unregister them for the rest of the run. Every app
    the fixtures build clears the registry before it is created. Request this
    in a test that constructs a service that registers its metrics in its
    constructor, which would otherwise collide with the app's.
    """
    _clear_prometheus_registry()
    yield
    _clear_prometheus_registry()


def _build_test_settings() -> Settings:
    """Construct base Settings object for tests."""
    return Settings(
        # The fixture that builds an app sets its database; this one does not
        # exist.
        database_url=_database_url("test_database_unset"),
        db_pool_size=TEST_DB_POOL_SIZE,
        db_pool_max_overflow=TEST_DB_POOL_MAX_OVERFLOW,
        db_pool_timeout=10,
        db_pool_echo=False,
        # The whole dict, as Settings.load() builds it: Settings() leaves it
        # empty, and an engine without options takes SQLAlchemy's own pool
        # (5 + 10), not db_pool_*.
        sqlalchemy_engine_options={
            "pool_size": TEST_DB_POOL_SIZE,
            "max_overflow": TEST_DB_POOL_MAX_OVERFLOW,
            "pool_timeout": 10,
            "pool_pre_ping": True,
            "echo_pool": False,
        },
        diagnostics_enabled=False,
        diagnostics_slow_query_threshold_ms=100,
        diagnostics_slow_request_threshold_ms=500,
        diagnostics_log_all_queries=False,
        secret_key="test-secret-key",
        debug=True,
        flask_env="testing",
        cors_origins=["http://localhost:3500"],
        # Tasks
        task_max_workers=4,
        task_timeout_seconds=300,
        task_cleanup_interval_seconds=600,
        # Metrics
        metrics_update_interval=60,
        # Shutdown
        graceful_shutdown_timeout=600,
        drain_auth_key="",
        # SSE
        sse_heartbeat_interval=1,
        frontend_version_url="http://localhost:3500/version.json",
        # OIDC Authentication (disabled for most tests)
        baseurl="http://localhost:3500",
        oidc_enabled=False,
        oidc_issuer_url="https://auth.example.com/realms/test",
        oidc_client_id="test-backend",
        oidc_client_secret=None,
        oidc_scopes="openid profile email",
        oidc_audience="test-backend",
        oidc_clock_skew_seconds=30,
        oidc_cookie_name="access_token",
        oidc_cookie_secure=False,
        oidc_cookie_samesite="Lax",
        oidc_refresh_cookie_name="refresh_token",
    )


def _build_test_app_settings() -> AppSettings:
    """Construct base AppSettings object for tests."""
    return AppSettings()


# Session-scoped: the session app is built from them. An override in the app's
# conftest.py must be session-scoped as well (pytest says so if it is not).
@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create test settings."""
    return _build_test_settings()


@pytest.fixture(scope="session")
def test_app_settings() -> AppSettings:
    """Create test app settings."""
    return _build_test_app_settings()


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


def _create_test_app(settings: Settings, app_settings: AppSettings) -> Flask:
    """Build an app for the suite, without background services.

    Clears the Prometheus registry first, so that services which register
    their metrics when they are constructed don't collide with the previous
    app's.
    """
    _clear_prometheus_registry()
    return create_app(
        settings, app_settings=app_settings, skip_background_services=True
    )


def _dispose_app(app: Flask) -> None:
    """Shut an app down and close its database connections."""
    # Shut down all background services via the lifecycle coordinator.
    # This fires PREPARE_SHUTDOWN then SHUTDOWN, which MetricsService,
    # TempFileManager, TaskService (and any other registered service)
    # handle in their _on_lifecycle_event callbacks.
    try:
        app.container.lifecycle_coordinator().shutdown()
    except Exception:
        pass

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _api_wiring_probe() -> tuple[Any, Any, Any] | None:
    """One injection of an app.api function, to tell later whether it moved.

    Reads dependency-injector's registry of wired functions, which is not its
    public API. Without it (another version), this returns None and every
    check re-wires: slower, still right.
    """
    try:
        from dependency_injector.wiring import _patched_registry

        patched_callables = list(_patched_registry._callables.values())
    except (ImportError, AttributeError):
        return None
    for patched in patched_callables:
        function = patched.patched
        if (
            function is not None
            and function.__module__.startswith("app.api")
            and patched.injections
        ):
            argument, provider = next(iter(patched.injections.items()))
            return patched, argument, provider
    return None


def _ensure_wired(app: Flask) -> None:
    """Wire app.api to the app's container again if another app took it."""
    probe = getattr(app, "_test_wiring_probe", None)
    if probe is not None:
        patched, argument, provider = probe
        if patched.injections.get(argument) is provider:
            return
    app.container.wire(packages=["app.api"])
    app._test_wiring_probe = _api_wiring_probe()  # type: ignore[attr-defined]


class RunDatabases:
    """The run's databases: a template built by the revisions, and its clones.

    The run holds one connection to the server's maintenance database for as
    long as it lasts, with its prefix as the connection's application_name.
    That is how a run tells another live run's databases, which it must leave
    alone, from the ones a run that died left behind.
    """

    def __init__(self) -> None:
        self.prefix = f"{_DATABASE_PREFIX}{uuid.uuid4().hex[:8]}"
        self.template = f"{self.prefix}_tpl"
        self._clone_numbers = itertools.count(1)
        self._engine = create_engine(
            _admin_url(),
            isolation_level="AUTOCOMMIT",
            poolclass=NullPool,
            connect_args={"application_name": self.prefix},
        )
        self._connection = self._engine.connect()

    def sweep(self) -> None:
        """Drop the databases that runs which are no longer alive left behind.

        A database that still has connections is skipped. The drop is without
        FORCE, so one that gains a connection meanwhile refuses with
        ObjectInUse, and is skipped too (after the server's 5 s wait).
        """
        live_runs = set(
            self._connection.execute(
                text(
                    "SELECT application_name FROM pg_stat_activity "
                    "WHERE starts_with(application_name, :prefix)"
                ),
                {"prefix": _DATABASE_PREFIX},
            ).scalars()
        )
        in_use = set(
            self._connection.execute(
                text(
                    "SELECT datname FROM pg_stat_activity "
                    "WHERE starts_with(datname, :prefix)"
                ),
                {"prefix": _DATABASE_PREFIX},
            ).scalars()
        )
        for name in self._database_names(_DATABASE_PREFIX):
            if name[: len(self.prefix)] in live_runs or name in in_use:
                continue
            try:
                self._connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            except DBAPIError as exc:
                if not isinstance(exc.orig, ObjectInUse):
                    raise

    def build_template(self, settings: Settings, app_settings: AppSettings) -> None:
        """Create the template and build it as ``cli upgrade-db`` does.

        That is the revisions, then the app's ``post_migration_hook``. A
        revision that fails stops the run here.
        """
        self._connection.execute(
            text(
                f'CREATE DATABASE "{self.template}" TEMPLATE template0 {_DATABASE_LOCALE}'
            )
        )
        template_app = _create_test_app(
            settings.model_copy(update={"database_url": _database_url(self.template)}),
            app_settings,
        )
        try:
            with template_app.app_context():
                upgrade_database()
                post_migration_hook(template_app)
        finally:
            # A database cannot be cloned while it has connections.
            _dispose_app(template_app)

    def clone(self, name: str | None = None) -> str:
        """Create a database from the template, and return its URL."""
        database = f"{self.prefix}_{name or next(self._clone_numbers)}"
        self._connection.execute(
            text(f'CREATE DATABASE "{database}" TEMPLATE "{self.template}"')
        )
        return _database_url(database)

    def drop(self, url: str) -> None:
        """Drop one of the run's databases, connections and all."""
        database = make_url(url).database
        self._connection.execute(
            text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        )

    def close(self) -> None:
        """Drop every database of the run, and end its connection."""
        try:
            for name in self._database_names(self.prefix):
                self._connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
                )
        finally:
            self._connection.close()
            self._engine.dispose()

    def _database_names(self, prefix: str) -> list[str]:
        return list(
            self._connection.execute(
                text(
                    "SELECT datname FROM pg_database WHERE starts_with(datname, :prefix)"
                ),
                {"prefix": prefix},
            ).scalars()
        )


@pytest.fixture(scope="session")
def run_databases(
    test_settings: Settings, test_app_settings: AppSettings
) -> Generator[RunDatabases]:
    """The run's databases: the sweep, then the template, once per run."""
    databases = RunDatabases()
    try:
        databases.sweep()
        databases.build_template(test_settings, test_app_settings)
        yield databases
    finally:
        databases.close()


@pytest.fixture(scope="session")
def app(
    run_databases: RunDatabases, test_settings: Settings, test_app_settings: AppSettings
) -> Generator[Flask]:
    """The session's app, on the run's main database.

    Built once and shared by every test. A test writes through ``session``, or
    through ``container`` or ``client``, which share it, and its writes are
    rolled back. What services keep in memory, such as the task service's
    tasks, lives for the whole run: a test cleans up what it starts.
    """
    settings = test_settings.model_copy(
        update={"database_url": run_databases.clone("main")}
    )
    application = _create_test_app(settings, test_app_settings)
    # create_app() wired app.api to it.
    application._test_wiring_probe = _api_wiring_probe()  # type: ignore[attr-defined]

    try:
        yield application
    finally:
        _dispose_app(application)


@pytest.fixture(autouse=True)
def session_app_isolation(app: Flask) -> Generator[None]:
    """Hand every test the session app as the previous test found it.

    - **Wiring.** Wiring is per module, not per app: creating an app wires
      app.api to its container, and that container then serves the requests
      of every app in the process. A test that builds a second app
      (``oidc_app``, ``committed_app``, or ``create_app()`` called directly)
      takes the wiring; the next test gets it back. Re-wiring costs about
      15 ms, so it happens only when the wiring moved.
    - **Provider overrides.** An override a test leaves on the container
      (``app.container.some_service.override(mock)``) is undone at teardown.

    What services keep in memory is not restored: a test cleans up what it
    starts.
    """
    _ensure_wired(app)
    overrides = [
        (provider, provider.overridden) for provider in app.container.traverse()
    ]

    yield

    for provider, overridden in overrides:
        if provider.overridden != overridden:
            provider.reset_override()
            for overriding in overridden:
                provider.override(overriding)


class _KeptOpenSession(Session):
    """A test's session: ``close()`` is a no-op, everything else is real.

    Request teardown commits the request's session and closes it. On this
    one, ``commit()`` releases a savepoint and fires the after-commit hooks,
    ``rollback()`` returns to the last savepoint, and the rows stay inside the
    test's transaction. Ignoring ``close()`` keeps objects attached across
    requests, so a test can read what a request wrote.
    """

    def close(self) -> None:
        pass


class _TestSessionMaker(sessionmaker[Session]):
    """A session maker that always returns the test's session."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self._session = session

    def __call__(self, **kwargs: Any) -> Session:
        return self._session


@pytest.fixture
def session(app: Flask) -> Generator[Session]:
    """The test's database session, rolled back at teardown.

    It runs on one connection, in a transaction that the teardown rolls back
    whatever state the session is in.
    """
    with app.app_context():
        engine = db.engine

    connection = engine.connect()
    transaction = connection.begin()
    test_session = _KeptOpenSession(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=True,
        expire_on_commit=False,
    )

    try:
        yield test_session
    finally:
        Session.close(test_session)
        transaction.rollback()
        connection.close()


@pytest.fixture
def container(app: Flask, session: Session) -> Generator[ServiceContainer]:
    """The session app's DI container, handing out the test's session."""
    container = app.container
    container.session_maker.override(_TestSessionMaker(session))
    container.db_session.reset()

    try:
        yield container
    finally:
        container.db_session.reset()
        container.session_maker.reset_last_overriding()


@pytest.fixture
def committed_app(
    run_databases: RunDatabases,
    test_settings: Settings,
    test_app_settings: AppSettings,
) -> Generator[Flask]:
    """An app on a database of its own, cloned from the run's template.

    Its sessions come from its real session maker, so every commit is real
    and visible to other connections. For row locks, other threads, and code
    that opens its own sessions. The database is dropped afterwards. A test
    that only needs to see its own commit stays on ``session``.
    """
    url = run_databases.clone()
    application = _create_test_app(
        test_settings.model_copy(update={"database_url": url}), test_app_settings
    )

    try:
        yield application
    finally:
        _dispose_app(application)
        run_databases.drop(url)


@pytest.fixture
def client(app: Flask, container: ServiceContainer):
    """Create test client. Its requests share the test's session."""
    return app.test_client()


@pytest.fixture
def runner(app: Flask):
    """Create test CLI runner."""
    return app.test_cli_runner()


# ---------------------------------------------------------------------------
# OIDC fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_oidc_discovery() -> dict[str, Any]:
    """Mock OIDC discovery document for authentication tests."""
    return {
        "issuer": "https://auth.example.com/realms/test",
        "authorization_endpoint": "https://auth.example.com/realms/test/protocol/openid-connect/auth",
        "token_endpoint": "https://auth.example.com/realms/test/protocol/openid-connect/token",
        "end_session_endpoint": "https://auth.example.com/realms/test/protocol/openid-connect/logout",
        "jwks_uri": "https://auth.example.com/realms/test/protocol/openid-connect/certs",
    }


@pytest.fixture
def mock_jwks() -> dict[str, Any]:
    """Mock JWKS (JSON Web Key Set) for authentication tests."""
    return {
        "keys": [
            {
                "kid": "test-key-id",
                "kty": "RSA",
                "use": "sig",
                "n": "test-modulus",
                "e": "AQAB",
            }
        ]
    }


@pytest.fixture
def generate_test_jwt(test_settings: Settings) -> Any:
    """Factory fixture to generate test JWT tokens.

    Returns a callable that generates JWT tokens with configurable claims.
    The public_key and private_key are available as attributes on the returned callable.
    """
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    # Generate RSA keypair for testing
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    def _generate(
        subject: str = "test-user",
        email: str | None = "test@example.com",
        name: str | None = "Test User",
        roles: list[str] | None = None,
        expired: bool = False,
        invalid_signature: bool = False,
        invalid_issuer: bool = False,
        invalid_audience: bool = False,
    ) -> str:
        """Generate a test JWT token.

        Args:
            subject: Subject claim (sub)
            email: Email claim
            name: Name claim
            roles: List of roles (stored in realm_access.roles)
            expired: Whether token should be expired
            invalid_signature: Whether to use wrong key for signing
            invalid_issuer: Whether to use wrong issuer
            invalid_audience: Whether to use wrong audience

        Returns:
            JWT token string
        """
        if roles is None:
            roles = ["admin"]

        now = int(time.time())
        exp = now - 3600 if expired else now + 3600

        payload = {
            "sub": subject,
            "iss": "https://wrong.example.com"
            if invalid_issuer
            else test_settings.oidc_issuer_url,
            "aud": "wrong-client-id"
            if invalid_audience
            else test_settings.oidc_client_id,
            "exp": exp,
            "iat": now,
            "realm_access": {"roles": roles},
        }

        if email:
            payload["email"] = email
        if name:
            payload["name"] = name

        # Use wrong key if invalid_signature requested
        signing_key = (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            if invalid_signature
            else private_key
        )

        token = jwt.encode(
            payload, signing_key, algorithm="RS256", headers={"kid": "test-key-id"}
        )
        return token

    # Attach keys for test verification
    _generate.public_key = public_key  # type: ignore[attr-defined]
    _generate.private_key = private_key  # type: ignore[attr-defined]

    return _generate


@pytest.fixture
def oidc_app(
    app: Flask,
    session: Session,
    test_settings: Settings,
    test_app_settings: AppSettings,
    mock_oidc_discovery: dict[str, Any],
    generate_test_jwt: Any,
) -> Generator[Flask]:
    """Create Flask app with OIDC enabled, on the session app's database.

    Its requests get the test's ``session``, so what they write is rolled back
    with the rest. Keeps httpx.get and PyJWKClient mocks active so that
    AuthService can discover endpoints and validate tokens throughout the test.
    """
    settings = test_settings.model_copy(
        update={
            "database_url": app.config["SQLALCHEMY_DATABASE_URI"],
            "oidc_enabled": True,
            "oidc_client_secret": "test-secret",
        }
    )

    with patch("httpx.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_discovery
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with patch("app.services.auth_service.PyJWKClient") as mock_jwk_client_class:
            mock_jwk_client = MagicMock()
            mock_signing_key = MagicMock()
            mock_signing_key.key = generate_test_jwt.public_key
            mock_jwk_client.get_signing_key_from_jwt.return_value = mock_signing_key
            mock_jwk_client_class.return_value = mock_jwk_client

            oidc_flask_app = _create_test_app(settings, test_app_settings)
            oidc_flask_app.container.session_maker.override(_TestSessionMaker(session))

            try:
                yield oidc_flask_app
            finally:
                _dispose_app(oidc_flask_app)


@pytest.fixture
def oidc_client(oidc_app: Flask) -> Any:
    """Create test client for the OIDC-enabled app."""
    return oidc_app.test_client()
