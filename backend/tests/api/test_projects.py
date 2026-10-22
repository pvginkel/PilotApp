"""/api/projects: the project list, the archived projects and a project's
head, as the signed-in person reads them (F1, F2, F3, D012); and what they
change of a project's standing, its transitions and their membership (F4.1,
F5, F6, F127, F128)."""

import uuid
from datetime import datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.models import (
    Document,
    Environment,
    Item,
    Project,
    ProjectMember,
    ProjectTransition,
    User,
)
from app.models.reference import SessionState, TransitionKind
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer

PROJECTS = "/api/projects"


def _sign_in(
    client: FlaskClient,
    subject: str = "subject-ada",
    roles: tuple[str, ...] = ("editor",),
) -> None:
    response = client.post(
        "/api/testing/auth/session",
        json={"subject": subject, "name": "Ada Example", "roles": list(roles)},
    )
    assert response.status_code == 201


def _run(
    session: Session, project: Project, environment: Environment
) -> models.Session:
    """An idle work session of `project`, which adds its items."""
    run = models.Session(
        project_id=project.id,
        environment_id=environment.id,
        kind_code="work",
        cwd="/work/Camp",
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.IDLE,
    )
    session.add(run)
    session.flush()
    return run


def _make(container: ServiceContainer, **spec: Any) -> uuid.UUID:
    spec.setdefault("members", ["ada"])
    return (
        container.test_data_service()
        .project(InventedProjectCreateSchema.model_validate(spec))
        .id
    )


@pytest.mark.usefixtures("person")
class TestListProjects:
    def test_the_tabs_of_every_unarchived_project(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        draft = _make(container, state="draft")
        recipes = _make(
            container,
            name="Recipe box",
            ticket="RB-12",
            members=["ben"],
            tasks=[
                {"id": "scope", "title": "Agree the scope", "status": "done"},
                {
                    "id": "build",
                    "title": "Build the card page",
                    "status": "in_progress",
                },
                {"id": "ship", "title": "Ship it", "status": "pending"},
            ],
        )
        finished = _make(container, name="Bike log", state="finished")
        _make(container, name="Photo album", archived=True)
        finished_at = session.scalars(
            select(ProjectTransition.at).where(
                ProjectTransition.project_id == finished,
                ProjectTransition.kind_code == TransitionKind.FINISHED,
            )
        ).one()
        _sign_in(client)

        response = client.get(PROJECTS)

        assert response.status_code == 200
        body = response.get_json()
        assert datetime.fromisoformat(body["projects"][2]["finished_at"]) == finished_at
        body["projects"][2]["finished_at"] = "<the finish>"
        assert body == {
            "projects": [
                {
                    "id": str(draft),
                    "name": None,
                    "ticket": None,
                    "state": "draft",
                    "finished_at": None,
                    "member": True,
                    "progress": {"done": 0, "total": 0, "in_progress": []},
                    "badge": {"count": 0, "urgent": False},
                },
                {
                    "id": str(recipes),
                    "name": "Recipe box",
                    "ticket": "RB-12",
                    "state": "open",
                    "finished_at": None,
                    "member": False,
                    "progress": {
                        "done": 1,
                        "total": 3,
                        "in_progress": ["Build the card page"],
                    },
                    "badge": {"count": 0, "urgent": False},
                },
                {
                    "id": str(finished),
                    "name": "Bike log",
                    "ticket": None,
                    "state": "finished",
                    "finished_at": "<the finish>",
                    "member": True,
                    "progress": {"done": 0, "total": 0, "in_progress": []},
                    "badge": {"count": 0, "urgent": False},
                },
            ]
        }

    def test_a_tab_counts_the_items_waiting_on_the_caller(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        camp = session.get_one(Project, _make(container, name="Camp"))
        run = _run(session, camp, environment)
        for title, front_matter in (
            ("Where?", ""),
            ("Storm", "urgent: true\n"),
            ("Opens in May", ""),
            ("Boots?", "for: ben\n"),
        ):
            container.document_service().bear_item(
                camp,
                "notice" if title in ("Storm", "Opens in May") else "question",
                title,
                run,
                f"---\ntitle: {title}\n{front_matter}---\n",
            )
        _sign_in(client)

        (tab,) = client.get(PROJECTS).get_json()["projects"]

        assert tab["badge"] == {"count": 2, "urgent": True}

    def test_archived_reads_the_archived_projects(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        _make(container, name="Kept")
        album = _make(container, name="Photo album", archived=True)
        _sign_in(client)

        response = client.get(PROJECTS, query_string={"archived": "true"})

        assert response.status_code == 200
        assert [tab["id"] for tab in response.get_json()["projects"]] == [str(album)]

    def test_no_project_is_an_empty_list(self, client: FlaskClient) -> None:
        _sign_in(client)

        assert client.get(PROJECTS).get_json() == {"projects": []}

    def test_a_person_at_their_first_sign_in_is_a_member_of_none(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        _make(container, name="Theirs")
        _sign_in(client, subject="subject-newcomer")

        (tab,) = client.get(PROJECTS).get_json()["projects"]

        assert tab["member"] is False

    def test_an_archived_that_is_no_boolean_is_refused(
        self, client: FlaskClient
    ) -> None:
        _sign_in(client)

        response = client.get(PROJECTS, query_string={"archived": "sometimes"})

        assert response.status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, roles=())

        assert client.get(PROJECTS).status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(PROJECTS).status_code == 401


@pytest.mark.usefixtures("person")
class TestGetProject:
    def test_the_head_of_a_project(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        environment: Environment,
    ) -> None:
        container.test_data_service().person("ben", "ben")
        recipes = _make(
            container,
            name="Recipe box",
            ticket="RB-12",
            repo="pvginkel/RecipeBox",
            autopilot=True,
            members=["ben", "ada"],
            tasks=[
                {"id": "scope", "title": "Agree the scope", "status": "done"},
                {
                    "id": "build",
                    "title": "Build the card page",
                    "status": "in_progress",
                    "notes": [
                        {
                            "id": "card-layout",
                            "summary": "Cards are one column",
                            "content": "Ben chose one column.",
                        }
                    ],
                },
                {"id": "ship", "title": "Ship it", "status": "pending"},
            ],
            notes=[
                {
                    "id": "print-view",
                    "summary": "A print view is the plan's question",
                    "content": "No task covers printing yet.",
                }
            ],
            open_items=2,
            environment_id=environment.id,
        )
        _sign_in(client)

        response = client.get(f"{PROJECTS}/{recipes}")

        assert response.status_code == 200
        assert response.get_json() == {
            "id": str(recipes),
            "name": "Recipe box",
            "ticket": "RB-12",
            "repo": "pvginkel/RecipeBox",
            "state": "open",
            "archived": False,
            "autopilot": True,
            "member": True,
            "members": [
                {"handle": "ben", "name": "ben", "initials": "B", "avatar_slot": 2},
                {
                    "handle": "ada",
                    "name": "Ada Example",
                    "initials": "AE",
                    "avatar_slot": 1,
                },
            ],
            "progress": {"done": 1, "total": 3, "in_progress": ["Build the card page"]},
            "tasks": [
                {
                    "id": "scope",
                    "title": "Agree the scope",
                    "status": "done",
                    "notes": [],
                },
                {
                    "id": "build",
                    "title": "Build the card page",
                    "status": "in_progress",
                    "notes": [
                        {
                            "id": "card-layout",
                            "summary": "Cards are one column",
                            "content": "Ben chose one column.",
                        }
                    ],
                },
                {"id": "ship", "title": "Ship it", "status": "pending", "notes": []},
            ],
            "notes": [
                {
                    "id": "print-view",
                    "summary": "A print view is the plan's question",
                    "content": "No task covers printing yet.",
                }
            ],
            "open_items": 2,
        }

    def test_an_archived_project_reads_as_it_was_left(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        album = _make(container, name="Photo album", state="finished", archived=True)
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{album}").get_json()

        assert (body["state"], body["archived"], body["autopilot"]) == (
            "finished",
            True,
            False,
        )

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.get(f"{PROJECTS}/{unknown}")

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_an_id_that_is_no_uuid_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        assert client.get(f"{PROJECTS}/recipe-box").status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, roles=())

        assert client.get(f"{PROJECTS}/{recipes}").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(f"{PROJECTS}/{uuid.uuid4()}").status_code == 401


_DECISION = """---
title: Which tent?
step: build
---

# Which tent?

The dome stands up in five minutes.

```decision id=D1
options:
  - Dome: up in five minutes
  - Tunnel
recommend: Dome
```
"""


def _stamped(body: dict[str, Any], path: tuple[str | int, ...]) -> datetime:
    """The time at `path` in `body`, replaced by a placeholder."""
    *parents, key = path
    holder: Any = body
    for parent in parents:
        holder = holder[parent]
    moment = datetime.fromisoformat(holder[key])
    holder[key] = "<time>"
    return moment


@pytest.mark.usefixtures("person")
class TestGetTimeline:
    def test_the_timeline_of_a_project(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
        person: User,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        camp = session.get_one(
            Project,
            _make(
                container,
                name="Camp",
                tasks=[{"id": "build", "title": "Build the camp", "status": "pending"}],
                opening="Let's camp.\n",
            ),
        )
        run = _run(session, camp, environment)
        documents = container.document_service()
        opening = session.scalars(select(Item).where(Item.project_id == camp.id)).one()
        decision = documents.bear_item(camp, "decision", "Which tent?", run, _DECISION)
        container.record_service().answer(
            session.get_one(Document, decision.id),
            "D1",
            person,
            "Tunnel",
            note="More room.",
        )
        notice = documents.bear_item(
            camp,
            "notice",
            "Storm",
            run,
            "---\ntitle: Storm\nurgent: true\nfor: ben\n---\n\nA storm comes.\n",
        )
        _sign_in(client)

        response = client.get(f"{PROJECTS}/{camp.id}/timeline")

        assert response.status_code == 200
        body = response.get_json()
        assert [
            _stamped(body, ("items", index, "created_at")) for index in range(3)
        ] == [opening.created_at, decision.created_at, notice.created_at]
        assert _stamped(body, ("items", 1, "done", "at")) == decision.done_at
        assert (
            _stamped(body, ("items", 1, "body", 1, "block", "at")) == decision.done_at
        )
        ada = {
            "kind": "person",
            "handle": "ada",
            "name": "Ada Example",
            "initials": "AE",
            "avatar_slot": 1,
        }
        assert body == {
            "finished_at": None,
            "items": [
                {
                    "id": str(opening.id),
                    "seq": 1,
                    "kind": "opening",
                    "form": "prose",
                    "title": "Camp",
                    "file_name": None,
                    "created_at": "<time>",
                    "step": None,
                    "urgent": False,
                    "for_user": None,
                    "done": None,
                    "concept": False,
                    "author": ada,
                    "words": "Let's camp.\n",
                    "body": None,
                },
                {
                    "id": str(decision.id),
                    "seq": 2,
                    "kind": "decision",
                    "form": "prose",
                    "title": "Which tent?",
                    "file_name": None,
                    "created_at": "<time>",
                    "step": {"id": "build", "title": "Build the camp"},
                    "urgent": False,
                    "for_user": None,
                    "done": {
                        "at": "<time>",
                        "cause": "answered",
                        "by": ada,
                        "undo": True,
                    },
                    "concept": False,
                    "author": None,
                    "words": None,
                    "body": [
                        {
                            "type": "prose",
                            "markdown": "The dome stands up in five minutes.",
                        },
                        {
                            "type": "block",
                            "block": {
                                "id": "D1",
                                "kind": "decision",
                                "confirmation": False,
                                "because": None,
                                "proposal": None,
                                "default": None,
                                "check": None,
                                "options": [
                                    {
                                        "label": "Dome",
                                        "text": "up in five minutes",
                                        "recommended": True,
                                    },
                                    {
                                        "label": "Tunnel",
                                        "text": None,
                                        "recommended": False,
                                    },
                                ],
                                "answer": "Tunnel",
                                "by": ada,
                                "at": "<time>",
                                "note": "More room.",
                                "via": "app",
                                "done": None,
                                "deferral": None,
                            },
                        },
                    ],
                },
                {
                    "id": str(notice.id),
                    "seq": 3,
                    "kind": "notice",
                    "form": "prose",
                    "title": "Storm",
                    "file_name": None,
                    "created_at": "<time>",
                    "step": None,
                    "urgent": True,
                    "for_user": {
                        "kind": "person",
                        "handle": "ben",
                        "name": "Ben Example",
                        "initials": "BE",
                        "avatar_slot": 2,
                    },
                    "done": None,
                    "concept": False,
                    "author": None,
                    "words": None,
                    "body": [{"type": "prose", "markdown": "A storm comes."}],
                },
            ],
        }

    def test_a_finished_project_has_its_finish(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        bikes = _make(container, name="Bike log", state="finished")
        finished_at = session.scalars(
            select(ProjectTransition.at).where(
                ProjectTransition.project_id == bikes,
                ProjectTransition.kind_code == TransitionKind.FINISHED,
            )
        ).one()
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{bikes}/timeline").get_json()

        assert datetime.fromisoformat(body["finished_at"]) == finished_at
        assert [item["kind"] for item in body["items"]] == ["opening"]

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.get(f"{PROJECTS}/{unknown}/timeline")

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_an_id_that_is_no_uuid_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        assert client.get(f"{PROJECTS}/camp/timeline").status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client, roles=())

        assert client.get(f"{PROJECTS}/{camp}/timeline").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        assert oidc_client.get(f"{PROJECTS}/{uuid.uuid4()}/timeline").status_code == 401


@pytest.mark.usefixtures("person")
class TestAddTransition:
    def test_finish_answers_the_head_with_its_new_standing(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        environment: Environment,
        session: Session,
        person: User,
    ) -> None:
        recipes = _make(
            container,
            name="Recipe box",
            autopilot=True,
            open_items=2,
            environment_id=environment.id,
        )
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 201
        body = response.get_json()
        assert body["id"] == str(recipes)
        assert (
            body["state"],
            body["archived"],
            body["autopilot"],
            body["member"],
            body["open_items"],
        ) == ("finished", False, False, True, 0)
        assert [
            (transition.kind_code, transition.by_user_id)
            for transition in session.scalars(
                select(ProjectTransition)
                .where(ProjectTransition.project_id == recipes)
                .order_by(ProjectTransition.at, ProjectTransition.id)
            )
        ][-2:] == [
            (TransitionKind.FINISHED, person.id),
            (TransitionKind.AUTOPILOT_OFF, person.id),
        ]
        assert {
            item.done_cause_code
            for item in session.scalars(
                select(Item).where(
                    Item.project_id == recipes, Item.kind_code != "opening"
                )
            )
        } == {"finished"}

    @pytest.mark.parametrize(
        ("spec", "kind", "standing"),
        [
            ({"state": "finished"}, "reopened", ("open", False, False)),
            ({"state": "finished"}, "archived", ("finished", True, False)),
            (
                {"autopilot": True, "archived": True},
                "brought_back",
                ("open", False, True),
            ),
            ({}, "autopilot_on", ("open", False, True)),
            ({"autopilot": True}, "autopilot_off", ("open", False, False)),
        ],
    )
    def test_every_kind_a_person_makes(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        spec: dict[str, Any],
        kind: str,
        standing: tuple[str, bool, bool],
    ) -> None:
        recipes = _make(container, name="Recipe box", **spec)
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{recipes}/transitions", json={"kind": kind})

        assert response.status_code == 201
        body = response.get_json()
        assert (body["state"], body["archived"], body["autopilot"]) == standing

    @pytest.mark.parametrize(
        "body",
        [{"kind": "opened"}, {"kind": "paused"}, {"kind": None}, {}],
    )
    def test_a_kind_no_person_makes_is_refused(
        self, client: FlaskClient, container: ServiceContainer, body: dict[str, Any]
    ) -> None:
        recipes = _make(container, name="Recipe box", state="draft")
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{recipes}/transitions", json=body)

        assert response.status_code == 400

    def test_a_kind_the_standing_does_not_allow_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box", archived=True)
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot finish Recipe box because it is archived, and an archived "
            "project takes Bring back alone"
        )

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, subject="subject-newcomer")

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "autopilot_on"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot turn auto pilot on for Recipe box because you have not chosen "
            "your handle yet"
        )

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.post(
            f"{PROJECTS}/{unknown}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, roles=())

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            f"{PROJECTS}/{uuid.uuid4()}/transitions", json={"kind": "finished"}
        )

        assert response.status_code == 401


def _open_memberships(session: Session, project_id: uuid.UUID, person: User) -> int:
    return len(
        session.scalars(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == person.id,
                ProjectMember.left_at.is_(None),
            )
        ).all()
    )


@pytest.mark.usefixtures("person")
class TestJoinProject:
    def test_joining_answers_the_head_with_the_caller_a_member(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        person: User,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(container, name="Recipe box", members=["ben"])
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 201
        body = response.get_json()
        assert body["member"] is True
        assert [member["handle"] for member in body["members"]] == ["ben", "ada"]
        assert _open_memberships(session, recipes, person) == 1

    def test_a_member_joining_again_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot join Recipe box because you are a member already"
        )

    def test_an_archived_project_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(container, name="Recipe box", members=["ben"], archived=True)
        _sign_in(client)

        assert client.post(f"{PROJECTS}/{recipes}/membership").status_code == 409

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, subject="subject-newcomer")

        response = client.post(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot join Recipe box because you have not chosen your handle yet"
        )

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{uuid.uuid4()}/membership")

        assert response.status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, roles=())

        assert client.post(f"{PROJECTS}/{recipes}/membership").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(f"{PROJECTS}/{uuid.uuid4()}/membership")

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestLeaveProject:
    def test_leaving_answers_the_head_with_the_caller_no_member(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        person: User,
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(container, name="Recipe box", members=["ben", "ada"])
        _sign_in(client)

        response = client.delete(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 200
        body = response.get_json()
        assert body["member"] is False
        assert [member["handle"] for member in body["members"]] == ["ben"]
        assert _open_memberships(session, recipes, person) == 0

    def test_a_person_who_is_no_member_leaving_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        container.test_data_service().person("ben", "Ben Example")
        recipes = _make(container, name="Recipe box", members=["ben"])
        _sign_in(client)

        response = client.delete(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot leave Recipe box because you are no member"
        )

    def test_an_archived_project_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box", archived=True)
        _sign_in(client)

        assert client.delete(f"{PROJECTS}/{recipes}/membership").status_code == 409

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, subject="subject-newcomer")

        response = client.delete(f"{PROJECTS}/{recipes}/membership")

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot leave Recipe box because you have not chosen your handle yet"
        )

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.delete(f"{PROJECTS}/{uuid.uuid4()}/membership")

        assert response.status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client, roles=())

        assert client.delete(f"{PROJECTS}/{recipes}/membership").status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.delete(f"{PROJECTS}/{uuid.uuid4()}/membership")

        assert response.status_code == 401
