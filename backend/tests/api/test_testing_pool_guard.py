"""The pool guard's nestings taken under /api/testing/pool-guard, as each
Playwright spec's teardown takes its backend's, and a nesting made through it
for a spec of the guard."""

from collections.abc import Generator

import pytest
from dependency_injector import providers
from flask import Flask

from app.app_config import AppSettings
from app.config import Settings, Stage
from app.extensions import db
from app.utils.pool_guard import PoolGuard
from tests.conftest_infrastructure import _create_test_app, _dispose_app

PREFIX = "/api/testing/pool-guard"
_HERE = "tests/api/test_testing_pool_guard.py"
_ROUTE = "app/api/testing_pool_guard.py"


@pytest.fixture
def guard(app: Flask) -> Generator[PoolGuard]:
    """A backend's guard, installed, the one the endpoint takes from."""
    guard = PoolGuard(watched=None)
    app.container.pool_guard.override(providers.Object(guard))
    guard.install()
    try:
        yield guard
    finally:
        guard.uninstall()


def _nest(app: Flask) -> None:
    with app.app_context():
        engine = db.engine
    with engine.connect(), engine.connect():
        pass


class TestTestingPoolGuardApi:
    def test_it_hands_each_nesting_over_once_with_both_stacks(
        self, app: Flask, guard: PoolGuard
    ) -> None:
        _nest(app)
        client = app.test_client()

        taken = client.post(f"{PREFIX}/take")
        again = client.post(f"{PREFIX}/take")

        assert taken.status_code == 200
        [nesting] = taken.get_json()["nestings"]
        assert "checked out a second connection of a pool while it held one" in nesting
        assert nesting.count(f"{_HERE}:") == nesting.count(" in _nest") * 2 == 4
        assert again.get_json() == {"nestings": []}

    def test_it_nests_in_its_route_once(
        self, app: Flask, guard: PoolGuard, pool_guard: PoolGuard
    ) -> None:
        client = app.test_client()

        nested = client.post(f"{PREFIX}/nest")
        taken = client.post(f"{PREFIX}/take")

        assert nested.status_code == 204
        [nesting] = taken.get_json()["nestings"]
        assert "checked out a second connection of a pool while it held one" in nesting
        assert nesting.count(f"{_ROUTE}:") == nesting.count(" in nest_checkouts") == 2
        # The app's, to the suite's guard as well.
        assert len(pool_guard.drain()) == 1

    def test_a_backend_without_the_guard_installed_refuses_it(self, app: Flask) -> None:
        response = app.test_client().post(f"{PREFIX}/take")

        assert response.status_code == 409
        assert response.get_json()["code"] == "INVALID_OPERATION"

    @pytest.mark.parametrize("route", ["take", "nest"])
    @pytest.mark.parametrize(
        "update",
        [{"flask_env": "development"}, {"stage": Stage("prd")}],
        ids=["outside-testing-mode", "testing-on-prd"],
    )
    def test_it_is_refused_outside_testing_mode(
        self,
        app: Flask,
        guard: PoolGuard,
        test_settings: Settings,
        update: dict[str, object],
        route: str,
    ) -> None:
        app.container.config.override(test_settings.model_copy(update=update))

        response = app.test_client().post(f"{PREFIX}/{route}")

        assert response.status_code == 400
        assert response.get_json()["code"] == "ROUTE_NOT_AVAILABLE"
        assert guard.drain() == []

    def test_a_production_app_refuses_it(self, test_settings: Settings) -> None:
        production = _create_test_app(
            test_settings.model_copy(
                update={"flask_env": "production", "stage": Stage("prd")}
            ),
            AppSettings(),
        )
        try:
            response = production.test_client().post(f"{PREFIX}/take")
        finally:
            _dispose_app(production)

        assert response.status_code == 400
