"""/api/testing/links: the deployment's link settings set on the running app
(F91, F93), for the specs that need them set and unset."""

import pytest
from flask import Flask
from flask.testing import FlaskClient

SETTINGS = "/api/testing/links"
LINKS = "/api/links"

TICKETS = "https://tracker.example.com/issue/{id}"
KUBECODER = "https://kubecoder.example.com"


class TestPutLinkSettings:
    def test_both_settings_are_set(self, client: FlaskClient) -> None:
        response = client.put(
            SETTINGS,
            json={
                "ticket_url_template": TICKETS,
                "environment_link_base_url": KUBECODER,
            },
        )

        assert response.status_code == 200
        assert response.get_json() == {
            "ticket_url_template": TICKETS,
            "environment_link_base_url": KUBECODER,
        }
        links = client.get(LINKS).get_json()
        assert links["ticket_url_template"] == TICKETS
        assert links["environment_link_base_url"] == KUBECODER

    def test_a_setting_left_out_is_unset(self, client: FlaskClient) -> None:
        client.put(
            SETTINGS,
            json={
                "ticket_url_template": TICKETS,
                "environment_link_base_url": KUBECODER,
            },
        )

        response = client.put(SETTINGS, json={"ticket_url_template": TICKETS})

        assert response.get_json() == {
            "ticket_url_template": TICKETS,
            "environment_link_base_url": None,
        }
        assert client.get(LINKS).get_json()["environment_link_base_url"] is None

    def test_the_ticket_id_pattern_stays(self, client: FlaskClient) -> None:
        client.put(SETTINGS, json={"ticket_url_template": TICKETS})

        assert (
            client.get(LINKS).get_json()["ticket_id_pattern"]
            == "[A-Z][A-Z0-9_]*-[1-9][0-9]*"
        )

    def test_the_base_loses_its_trailing_slash(self, client: FlaskClient) -> None:
        response = client.put(
            SETTINGS, json={"environment_link_base_url": f"{KUBECODER}/"}
        )

        assert response.get_json()["environment_link_base_url"] == KUBECODER

    @pytest.mark.parametrize(
        "body",
        [
            {"ticket_url_template": "https://tracker.example.com/issue/"},
            {"environment_link_base_url": "kubecoder.example.com"},
            {"ticket_url_template": 7},
        ],
    )
    def test_a_setting_the_boot_refuses_is_refused(
        self, client: FlaskClient, body: dict[str, object]
    ) -> None:
        response = client.put(SETTINGS, json=body)

        assert response.status_code == 400
        assert client.get(LINKS).get_json()["ticket_url_template"] is None

    def test_it_is_refused_in_production(
        self, app: Flask, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app.container.config(), "flask_env", "production")

        response = client.put(SETTINGS, json={"ticket_url_template": TICKETS})

        assert response.status_code == 400
        monkeypatch.undo()
        assert client.get(LINKS).get_json()["ticket_url_template"] is None
