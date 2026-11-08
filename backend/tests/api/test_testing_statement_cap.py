"""The statement cap's statements taken under /api/testing/statement-cap, as
each Playwright spec's teardown takes its backend's, and a statement sent
through it for a spec of the cap."""

from collections.abc import Generator

import pytest
from dependency_injector import providers
from flask import Flask

from app.app_config import AppSettings
from app.config import Settings, Stage
from app.utils.statement_cap import CAP, StatementCap
from tests.conftest_infrastructure import _create_test_app, _dispose_app

PREFIX = "/api/testing/statement-cap"


@pytest.fixture
def cap(app: Flask) -> Generator[StatementCap]:
    """A backend's cap, installed, the one the endpoint takes from."""
    cap = StatementCap(watched=None)
    app.container.statement_cap.override(providers.Object(cap))
    cap.install()
    try:
        yield cap
    finally:
        cap.uninstall()


class TestTestingStatementCapApi:
    def test_it_hands_each_statement_over_once_with_its_length_and_text(
        self, app: Flask, cap: StatementCap, statement_cap: StatementCap
    ) -> None:
        client = app.test_client()

        sent = client.post(f"{PREFIX}/send", json={"length": CAP + 1, "ids": 1})
        taken = client.post(f"{PREFIX}/take")
        again = client.post(f"{PREFIX}/take")

        assert sent.status_code == 204
        assert taken.status_code == 200
        [statement] = taken.get_json()["statements"]
        assert statement.startswith(
            f"A statement of {CAP + 1:,} characters, over its bound of {CAP:,}"
        )
        assert "app/api/testing_statement_cap.py:" in statement
        assert "SELECT 1 WHERE 1 IN (__[POSTCOMPILE_ids]) -- " in statement
        assert again.get_json() == {"statements": []}
        # The app's, to the suite's cap as well.
        assert len(statement_cap.drain()) == 1

    def test_a_statement_at_the_cap_with_a_long_in_list_is_none(
        self, app: Flask, cap: StatementCap
    ) -> None:
        client = app.test_client()

        sent = client.post(f"{PREFIX}/send", json={"length": CAP, "ids": 1_000})

        assert sent.status_code == 204
        assert client.post(f"{PREFIX}/take").get_json() == {"statements": []}

    def test_it_refuses_a_length_below_the_shortest_statement(
        self, app: Flask, cap: StatementCap
    ) -> None:
        response = app.test_client().post(
            f"{PREFIX}/send", json={"length": 10, "ids": 1}
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "INVALID_OPERATION"

    @pytest.mark.parametrize(
        "body", [{"ids": 1}, {"length": CAP, "ids": 0}], ids=["no-length", "no-id"]
    )
    def test_it_refuses_a_body_that_is_no_statement(
        self, app: Flask, cap: StatementCap, body: dict[str, int]
    ) -> None:
        response = app.test_client().post(f"{PREFIX}/send", json=body)

        assert response.status_code == 400

    def test_a_backend_without_the_cap_installed_refuses_the_take(
        self, app: Flask
    ) -> None:
        response = app.test_client().post(f"{PREFIX}/take")

        assert response.status_code == 409
        assert response.get_json()["code"] == "INVALID_OPERATION"

    @pytest.mark.parametrize("route", ["take", "send"])
    @pytest.mark.parametrize(
        "update",
        [{"flask_env": "development"}, {"stage": Stage("prd")}],
        ids=["outside-testing-mode", "testing-on-prd"],
    )
    def test_it_is_refused_outside_testing_mode(
        self,
        app: Flask,
        cap: StatementCap,
        test_settings: Settings,
        update: dict[str, object],
        route: str,
    ) -> None:
        app.container.config.override(test_settings.model_copy(update=update))

        response = app.test_client().post(
            f"{PREFIX}/{route}", json={"length": CAP + 1, "ids": 1}
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "ROUTE_NOT_AVAILABLE"
        assert cap.drain() == []

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
