"""SQLAlchemy connection pool diagnostics.

Registers event listeners on the engine that log checkout/checkin activity
with caller information and pool statistics. Enable via the db_pool_echo
configuration flag.
"""

import logging
import traceback

from sqlalchemy import Engine, event
from sqlalchemy.pool import Pool

logger = logging.getLogger(__name__)
pool_logger = logging.getLogger("sqlalchemy.pool")


def setup_pool_logging(engine: Engine) -> None:
    """Attach checkout/checkin event listeners that log pool activity.

    Args:
        engine: The SQLAlchemy engine whose pool should be instrumented.
    """
    pool_logger.setLevel(logging.DEBUG)
    if not pool_logger.handlers:
        pool_logger.addHandler(logging.StreamHandler())

    def _get_pool_stats(pool: Pool) -> str:
        # QueuePool has checkedout(), size(), overflow() methods not on base Pool type
        return f"checkedout={pool.checkedout()} size={pool.size()} overflow={pool.overflow()}"  # type: ignore[attr-defined]

    def _get_caller_info() -> str:
        """Extract the first app-level caller from the stack trace."""
        # Skip SQLAlchemy/library internals, find app code
        skip_prefixes = (
            "sqlalchemy",
            "flask_sqlalchemy",
            "werkzeug",
            "flask",
            "waitress",
            "paste",
        )
        frames = []
        for frame_info in traceback.extract_stack():
            # Skip this module and library code
            if "/app/utils/pool_diagnostics.py" in frame_info.filename:
                continue
            if any(p in frame_info.filename for p in skip_prefixes):
                continue
            if "/app/" in frame_info.filename or "/tests/" in frame_info.filename:
                # Extract just the relevant part of the path
                path = frame_info.filename
                if "/app/" in path:
                    path = "app/" + path.split("/app/")[-1]
                elif "/tests/" in path:
                    path = "tests/" + path.split("/tests/")[-1]
                frames.append(f"{path}:{frame_info.lineno}:{frame_info.name}")
        # Return the most recent app-level callers (last 3)
        return " <- ".join(frames[-3:]) if frames else "unknown"

    @event.listens_for(engine, "checkout")
    def _on_checkout(
        dbapi_conn: object, conn_record: object, conn_proxy: object
    ) -> None:
        caller = _get_caller_info()
        pool_logger.debug(
            "CHECKOUT %s | conn=%s %s",
            caller,
            id(dbapi_conn),
            _get_pool_stats(engine.pool),
        )

    @event.listens_for(engine, "checkin")
    def _on_checkin(dbapi_conn: object, conn_record: object) -> None:
        caller = _get_caller_info()
        pool_logger.debug(
            "CHECKIN %s | conn=%s %s",
            caller,
            id(dbapi_conn),
            _get_pool_stats(engine.pool),
        )

    logger.info("Pool diagnostics enabled")
