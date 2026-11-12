"""The service user at the API (DB 338): its token is admitted as a person's
is, by the `editor` role and the subject, and it is the caller and nothing
more: every write attributed to a person refuses it."""

import secrets
import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from flask.testing import FlaskClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.config import Settings
from app.models import (
    AppPage,
    ChatRead,
    Document,
    Item,
    ItemSighting,
    Project,
    ProjectMember,
    ProjectTransition,
    PushSubscription,
    QuotaOverrule,
    Turn,
    User,
)
from app.services.web_push import point
from app.utils.base64url import b64

NO_ROW = uuid.UUID("00000000-0000-4000-8000-000000000000")
PHONE = "https://push.example.com/send/phone-of-fleet"
# A browser's keys in the form the Push API gives them, minted for the module.
BROWSER_P256DH = b64(point(ec.generate_private_key(ec.SECP256R1()).public_key()))
BROWSER_AUTH = b64(secrets.token_bytes(16))

REFUSAL = "you call as the service user 'fleet', which is no person"


def _count(session: Session, model: Any) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _sign_in(client: FlaskClient, service_user: User) -> None:
    """A testing session under the service user's subject, with what its
    token carries: the role, and no name or email."""
    response = client.post(
        "/api/testing/auth/session",
        json={
            "subject": service_user.subject,
            "name": None,
            "email": None,
            "roles": ["editor"],
        },
    )
    assert response.status_code == 201


class TestTheGate:
    """A client-credentials token of the service user's client, as a bearer."""

    @pytest.fixture
    def bearer(
        self, test_settings: Settings, generate_test_jwt: Any, service_user: User
    ) -> dict[str, str]:
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": service_user.subject,
                "iss": test_settings.oidc_issuer_url,
                "aud": test_settings.oidc_audience,
                "iat": now,
                "exp": now + 3600,
                "resource_access": {test_settings.oidc_audience: {"roles": ["editor"]}},
            },
            generate_test_jwt.private_key,
            algorithm="RS256",
            headers={"kid": "test-key-id"},
        )
        return {"Authorization": f"Bearer {token}"}

    def test_its_token_is_admitted_by_the_role_and_the_subject(
        self, oidc_client: FlaskClient, bearer: dict[str, str], project: Project
    ) -> None:
        me = oidc_client.get("/api/people/self", headers=bearer)
        listed = oidc_client.get("/api/projects", headers=bearer)

        assert me.status_code == 200
        assert me.get_json()["handle"] == "fleet"
        assert listed.status_code == 200
        assert [row["id"] for row in listed.get_json()["projects"]] == [str(project.id)]

    def test_a_persons_write_refuses_it(
        self, oidc_client: FlaskClient, bearer: dict[str, str], session: Session
    ) -> None:
        response = oidc_client.post(
            "/api/projects", headers=bearer, json={"words": "Hello"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot start a new project because {REFUSAL}"
        )
        assert _count(session, Project) == 0


def _writes(
    project: uuid.UUID, item: uuid.UUID, work: uuid.UUID
) -> list[tuple[str, str, Any]]:
    """Every write of the API that names the person who made it: the method,
    the path and a body the route takes."""
    return [
        ("POST", "/api/projects", {"words": "Hello"}),
        ("POST", f"/api/projects/{project}/transitions", {"kind": "paused"}),
        ("POST", f"/api/projects/{project}/membership", None),
        ("DELETE", f"/api/projects/{project}/membership", None),
        ("POST", f"/api/projects/{project}/draft/blocks/Q1/answer", {"answer": "A"}),
        ("POST", f"/api/projects/{project}/draft/blocks/A1/done", {}),
        ("POST", f"/api/projects/{project}/chat/messages", {"words": "Hello"}),
        ("POST", f"/api/projects/{project}/chat/stop", None),
        ("PUT", f"/api/projects/{project}/chat/read", None),
        ("POST", f"/api/items/{item}/blocks/Q1/answer", {"answer": "A"}),
        ("POST", f"/api/items/{item}/blocks/A1/done", {}),
        ("POST", f"/api/items/{item}/done", None),
        ("POST", f"/api/items/{item}/read", None),
        ("POST", f"/api/items/{item}/reviewed", None),
        ("POST", f"/api/items/{item}/take-over", None),
        ("POST", f"/api/items/{item}/cancel", None),
        ("POST", f"/api/items/{item}/request", None),
        ("POST", "/api/people/self/app-pages", {"project_id": None}),
        ("PUT", f"/api/people/self/app-pages/{NO_ROW}", {"project_id": None}),
        ("POST", f"/api/people/self/app-pages/{NO_ROW}/away", None),
        ("PUT", "/api/people/self/alarms", {"alarms": False}),
        (
            "POST",
            "/api/people/self/push-subscriptions",
            {
                "endpoint": PHONE,
                "keys": {"p256dh": BROWSER_P256DH, "auth": BROWSER_AUTH},
            },
        ),
        ("DELETE", f"/api/people/self/push-subscriptions?endpoint={PHONE}", None),
        ("POST", "/api/quota-overrules", {"kind": "allowance"}),
        ("POST", f"/api/sessions/{work}/stop", None),
    ]


class TestAPersonsWrites:
    def test_every_one_refuses_the_service_user_and_writes_nothing(
        self,
        client: FlaskClient,
        session: Session,
        service_user: User,
        project: Project,
        draft_document: Document,
        item: Item,
        project_session: models.Session,
    ) -> None:
        _sign_in(client, service_user)
        written = (
            Project,
            ProjectMember,
            ProjectTransition,
            Item,
            Turn,
            ChatRead,
            AppPage,
            PushSubscription,
            QuotaOverrule,
        )
        before = [_count(session, model) for model in written]

        answers = {}
        for method, path, body in _writes(project.id, item.id, project_session.id):
            response = client.open(path, method=method, json=body)
            error = (response.get_json() or {}).get("error", "")
            answers[f"{method} {path}"] = (
                response.status_code,
                error.endswith(f" because {REFUSAL}"),
            )

        assert answers == dict.fromkeys(answers, (409, True))
        assert [_count(session, model) for model in written] == before
        session.refresh(item)
        assert item.done_at is None
        assert (service_user.alarms, service_user.last_seen_at) == (True, None)

    def test_a_read_answers_it_and_writes_nothing_of_it(
        self,
        client: FlaskClient,
        session: Session,
        service_user: User,
        person: User,
    ) -> None:
        made = client.post("/api/testing/projects", json={"members": ["ada"]})
        project_id = made.get_json()["id"]
        _sign_in(client, service_user)

        reads = [
            client.get(path).status_code
            for path in (
                "/api/people/self",
                "/api/projects",
                f"/api/projects/{project_id}",
                f"/api/projects/{project_id}/timeline",
                f"/api/projects/{project_id}/chats",
            )
        ]

        assert reads == [200] * 5
        assert session.scalars(select(ProjectMember.user_id)).all() == [person.id]
        assert [_count(session, model) for model in (ChatRead, ItemSighting)] == [0, 0]
        assert service_user.last_seen_at is None
