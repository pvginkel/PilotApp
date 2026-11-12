"""/api/testing/halt-settings: what each usage halt does to the work items
(F135.6), set on the running app, for the specs that need a setting the
backend did not boot with."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.models import UsageReading, WindowShare
from app.models.reference import UsageWindow
from app.services.container import ServiceContainer

SETTINGS = "/api/testing/halt-settings"
CONDITIONS = "/api/conditions"


@pytest.fixture(autouse=True)
def _booted_settings(client: FlaskClient) -> Iterator[None]:
    """The session app's halts back at the settings it booted with."""
    yield
    assert client.put(SETTINGS, json={}).status_code == 200


def _usage(db: Session, *, week: float, five_hour: float) -> None:
    """A fresh Usage Reading recorded now with these shares."""
    now = datetime.now(UTC)
    reading = UsageReading(taken_at=now, received_at=now, stale=False)
    db.add(reading)
    db.flush()
    db.add_all(
        WindowShare(
            reading_id=reading.id,
            window_code=window,
            share=share,
            resets_at=now + timedelta(hours=4),
        )
        for window, share in (
            (UsageWindow.SEVEN_DAY, week),
            (UsageWindow.FIVE_HOUR, five_hour),
        )
    )
    db.flush()


def _settings(client: FlaskClient) -> list[tuple[str, str]]:
    """Each halt that holds, with its setting, as the conditions give them."""
    held = client.get(CONDITIONS).get_json()["conditions"]
    return [(condition["code"], condition["setting"]) for condition in held]


class TestPutHaltSettings:
    def test_both_settings_are_set(self, client: FlaskClient, session: Session) -> None:
        _usage(session, week=0.92, five_hour=0.8)

        response = client.put(
            SETTINGS, json={"week_halt": "no_new_work", "five_hour_halt": "hard_stop"}
        )

        assert response.status_code == 200
        assert response.get_json() == {
            "week_halt": "no_new_work",
            "five_hour_halt": "hard_stop",
        }
        assert _settings(client) == [
            ("week_halt", "no_new_work"),
            ("five_hour_halt", "hard_stop"),
        ]

    def test_a_setting_left_out_is_the_one_the_app_booted_with(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        booted = container.app_config()
        _usage(session, week=0.92, five_hour=0.8)
        client.put(
            SETTINGS, json={"week_halt": "no_new_work", "five_hour_halt": "hard_stop"}
        )

        response = client.put(SETTINGS, json={"five_hour_halt": "no_new_work"})

        assert response.get_json() == {
            "week_halt": booted.week_halt.value,
            "five_hour_halt": "no_new_work",
        }
        assert _settings(client) == [
            ("week_halt", booted.week_halt.value),
            ("five_hour_halt", "no_new_work"),
        ]

    def test_the_hard_stop_and_the_halt_file_take_the_setting(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        _usage(session, week=0.92, five_hour=0.1)

        client.put(SETTINGS, json={"week_halt": "hard_stop"})
        hard = (
            container.usage_halts().stopping(session),
            container.halt_file_service().halting(session),
        )
        client.put(SETTINGS, json={"week_halt": "cooperative_stop"})
        cooperative = (
            container.usage_halts().stopping(session),
            container.halt_file_service().halting(session),
        )
        client.put(SETTINGS, json={"week_halt": "no_new_work"})
        no_new_work = (
            container.usage_halts().stopping(session),
            container.halt_file_service().halting(session),
        )

        assert (hard, cooperative, no_new_work) == (
            (True, False),
            (False, True),
            (False, False),
        )

    @pytest.mark.parametrize(
        "body",
        [{"week_halt": "soft_stop"}, {"five_hour_halt": 7}],
    )
    def test_a_setting_that_is_none_of_the_three_is_refused(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        body: dict[str, object],
    ) -> None:
        booted = container.app_config()
        _usage(session, week=0.92, five_hour=0.8)

        response = client.put(SETTINGS, json=body)

        assert response.status_code == 400
        assert _settings(client) == [
            ("week_halt", booted.week_halt.value),
            ("five_hour_halt", booted.five_hour_halt.value),
        ]

    def test_it_is_refused_in_production(
        self,
        app: Flask,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        booted = container.app_config()
        _usage(session, week=0.92, five_hour=0.1)
        monkeypatch.setattr(app.container.config(), "flask_env", "production")

        response = client.put(SETTINGS, json={"week_halt": "no_new_work"})

        assert response.status_code == 400
        monkeypatch.undo()
        assert _settings(client) == [("week_halt", booted.week_halt.value)]
