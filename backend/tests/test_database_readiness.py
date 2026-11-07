"""The database's readiness check (app/database.py) on the app's pool."""

from flask import Flask

from app.database import check_readiness
from app.utils.pool_guard import PoolGuard


def test_the_readiness_check_holds_one_connection_at_a_time(app: Flask) -> None:
    guard = PoolGuard(watched=None)
    guard.install()
    try:
        with app.app_context():
            check_readiness()
    finally:
        guard.uninstall()

    assert guard.drain() == []
