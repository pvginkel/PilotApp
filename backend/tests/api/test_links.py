"""/api/links: the deployment's link settings and the record's environments
(F91, F93)."""

import pytest
from dependency_injector import providers
from flask import Flask
from flask.testing import FlaskClient

from app.app_config import AppSettings
from app.models import Environment

LINKS = "/api/links"


@pytest.fixture
def link_settings(app: Flask) -> None:
    """The app with both link settings set; the isolation fixture undoes it."""
    app.container.app_config.override(
        providers.Object(
            AppSettings(
                ticket_url_template="https://tracker.example.com/issue/{id}",
                environment_link_base_url="https://kubecoder.example.com",
            )
        )
    )


class TestGetLinks:
    def test_unset_settings_read_null(self, client: FlaskClient) -> None:
        response = client.get(LINKS)

        assert response.status_code == 200
        assert response.get_json() == {
            "ticket_id_pattern": "[A-Z][A-Z0-9_]*-[1-9][0-9]*",
            "ticket_url_template": None,
            "environment_link_base_url": None,
            "environments": [],
        }

    @pytest.mark.usefixtures("link_settings")
    def test_set_settings_are_read(self, client: FlaskClient) -> None:
        body = client.get(LINKS).get_json()

        assert body["ticket_url_template"] == "https://tracker.example.com/issue/{id}"
        assert body["environment_link_base_url"] == "https://kubecoder.example.com"

    def test_the_records_environments_are_read(
        self, client: FlaskClient, environment: Environment
    ) -> None:
        assert client.get(LINKS).get_json()["environments"] == [
            {"id": "example-env-1", "name": "Example-1"}
        ]

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        client.post(
            "/api/testing/auth/session", json={"subject": "someone", "roles": []}
        )

        assert client.get(LINKS).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(LINKS).status_code == 401
