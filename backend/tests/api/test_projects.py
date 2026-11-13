"""/api/projects: the project list, the archived projects and a project's
head, as the signed-in person reads them (F1, F2, F3, D012); a draft made
with its first message (F46.1, F47.1), or by a call with its brief (F150.9),
and their answers to its asks in place (F47.4); and what they change of a
project's standing, its transitions and their membership (F4.1, F5, F6, F127,
F128)."""

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from dependency_injector import providers
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.engine.views import utc_time
from app.models import (
    Block,
    Chat,
    Document,
    Environment,
    Item,
    Project,
    ProjectMember,
    ProjectTransition,
    Turn,
    User,
)
from app.models.reference import (
    AnswerChannel,
    ChatKind,
    DocumentRole,
    SessionState,
    TransitionKind,
)
from app.schemas.testing_record import InventedFileSchema, InventedProjectCreateSchema
from app.schemas.timeline import TimelineSchema
from app.services.auth_service import AuthContext
from app.services.caller_environment_service import (
    CALLER_ENVIRONMENT_HEADER,
    CallerEnvironmentService,
)
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.job_service import SETUP_TITLE
from app.services.session_scope import STORE_REPO
from tests.support.fake_controller import ServedFakeController
from tests.support.fake_sidecar import STORE_ENVIRONMENT_ID, FakeSidecar
from tests.support.starts import configured_starts
from tests.support.store_updates import hold
from tests.support.supervisor import Supervise

PROJECTS = "/api/projects"

BASE_URL = "http://localhost:3500"
"""The app's public address in the suite's settings (`baseurl`)."""

ADA = AuthContext(
    subject="subject-ada", email=None, name="Ada Example", roles={"editor"}
)
"""The person `_sign_in` signs in, as a service reads them."""


@pytest.fixture
def starts(container: ServiceContainer, supervise: Supervise) -> Iterator[None]:
    """The routes' session start with a controller and the store configured,
    its loops never run: Create starts the setup through it."""
    container.session_start_service.override(
        providers.Object(configured_starts(container, supervise))
    )
    try:
        yield
    finally:
        container.session_start_service.reset_last_overriding()


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
        assert [tab["address"] for tab in body["projects"]] == [
            f"draft-{session.get_one(Project, draft).number}",
            session.get_one(Project, recipes).slug,
            session.get_one(Project, finished).slug,
        ]
        for tab in body["projects"]:
            tab["address"] = "<its address>"
        assert datetime.fromisoformat(body["projects"][2]["finished_at"]) == finished_at
        body["projects"][2]["finished_at"] = "<the finish>"
        assert body == {
            "projects": [
                {
                    "id": str(draft),
                    "address": "<its address>",
                    "name": None,
                    "ticket": None,
                    "state": "draft",
                    "finished_at": None,
                    "status": None,
                    "member": True,
                    "progress": {"done": 0, "total": 0, "in_progress": []},
                    "badge": {"count": 0, "urgent": False},
                },
                {
                    "id": str(recipes),
                    "address": "<its address>",
                    "name": "Recipe box",
                    "ticket": "RB-12",
                    "state": "open",
                    "finished_at": None,
                    "status": "idle",
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
                    "address": "<its address>",
                    "name": "Bike log",
                    "ticket": None,
                    "state": "finished",
                    "finished_at": "<the finish>",
                    "status": None,
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


LOOKUP = f"{PROJECTS}/lookup"


@pytest.mark.usefixtures("person")
class TestLookupProject:
    def test_a_slug_finds_its_project(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        recipes = session.get_one(Project, _make(container, name="Recipe box"))
        _make(container, name="Bike log")
        _sign_in(client)

        response = client.get(LOOKUP, query_string={"address": recipes.slug})

        assert response.status_code == 200
        assert response.get_json() == {"id": str(recipes.id), "address": recipes.slug}

    def test_a_drafts_name_finds_it(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        draft = session.get_one(Project, _make(container, state="draft"))
        _sign_in(client)

        response = client.get(LOOKUP, query_string={"address": f"draft-{draft.number}"})

        assert response.status_code == 200
        assert response.get_json() == {
            "id": str(draft.id),
            "address": f"draft-{draft.number}",
        }

    def test_a_drafts_name_after_create_answers_the_slug(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        """A project's number is its draft's name for good: it is never
        handed out again."""
        recipes = session.get_one(Project, _make(container, name="Recipe box"))
        _sign_in(client)

        response = client.get(
            LOOKUP, query_string={"address": f"draft-{recipes.number}"}
        )

        assert response.status_code == 200
        assert response.get_json() == {"id": str(recipes.id), "address": recipes.slug}

    @pytest.mark.parametrize("state", ["open", "draft"])
    def test_an_id_finds_its_project_and_answers_its_address(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        state: str,
    ) -> None:
        project = session.get_one(Project, _make(container, state=state))
        _sign_in(client)

        response = client.get(LOOKUP, query_string={"address": str(project.id)})

        assert response.status_code == 200
        assert response.get_json() == {
            "id": str(project.id),
            "address": project.slug or f"draft-{project.number}",
        }

    def test_an_archived_project_is_found(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        album = session.get_one(
            Project, _make(container, name="Photo album", archived=True)
        )
        _sign_in(client)

        response = client.get(LOOKUP, query_string={"address": album.slug})

        assert response.status_code == 200
        assert response.get_json()["id"] == str(album.id)

    @pytest.mark.parametrize(
        "address",
        [
            pytest.param("recipe-box", id="slug"),
            pytest.param("draft-999999", id="draft"),
            pytest.param("draft-3000000000", id="draft-past-every-number"),
            pytest.param("draft-" + "9" * 5000, id="draft-past-int"),
            pytest.param("draft-07", id="draft-not-its-name"),
            pytest.param(str(uuid.UUID(int=7)), id="id"),
        ],
    )
    def test_an_address_no_project_is_at_is_not_found(
        self, client: FlaskClient, container: ServiceContainer, address: str
    ) -> None:
        _make(container, name="Bike log")
        _sign_in(client)

        response = client.get(LOOKUP, query_string={"address": address})

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {address} was not found"

    @pytest.mark.parametrize("query", [{}, {"address": ""}])
    def test_no_address_is_refused(
        self, client: FlaskClient, query: dict[str, str]
    ) -> None:
        _sign_in(client)

        assert client.get(LOOKUP, query_string=query).status_code == 400

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        recipes = session.get_one(Project, _make(container, name="Recipe box"))
        _sign_in(client, roles=())

        response = client.get(LOOKUP, query_string={"address": recipes.slug})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.get(LOOKUP, query_string={"address": "recipe-box"})

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestGetProject:
    def test_the_head_of_a_project(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
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
            "address": session.get_one(Project, recipes).slug,
            "name": "Recipe box",
            "ticket": "RB-12",
            "repo": "pvginkel/RecipeBox",
            "state": "open",
            "archived": False,
            "autopilot": True,
            "status": "idle",
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
            "running_work": [],
            "open_items": 2,
            "autopilot_may_take": 0,
            "create_refusal": "it is no draft",
            "url": f"{BASE_URL}/projects/{session.get_one(Project, recipes).slug}",
        }

    def test_the_running_work_is_named_for_the_finish_dialog(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        recipes = _make(
            container, name="Recipe box", open_items=1, environment_id=environment.id
        )
        project = session.get_one(Project, recipes)
        run = _run(session, project, environment)
        run.state_code = SessionState.RUNNING
        container.record_service().place_work(project, run, "Building the card page")
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{recipes}").get_json()

        work = session.get_one(Item, run.id)
        assert body["running_work"] == [
            {
                "id": str(run.id),
                "seq": work.seq,
                "title": "Building the card page",
                "environment": environment.name,
            }
        ]
        assert body["open_items"] == 1

    def test_a_work_item_held_at_the_gate_has_no_environment(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        recipes = _make(container, name="Recipe box", environment_id=environment.id)
        project = session.get_one(Project, recipes)
        run = _run(session, project, environment)
        run.state_code = SessionState.HELD
        run.environment_id = None
        container.record_service().place_work(project, run, "Building the card page")
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{recipes}").get_json()

        [work] = body["running_work"]
        assert (work["title"], work["environment"]) == ("Building the card page", None)

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


HEAD = f"{PROJECTS}/head"


@pytest.mark.usefixtures("person")
class TestGetProjectAtAddress:
    def test_a_slug_reads_its_projects_head(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        recipes = session.get_one(Project, _make(container, name="Recipe box"))
        _make(container, name="Bike log")
        _sign_in(client)

        response = client.get(HEAD, query_string={"address": recipes.slug})

        assert response.status_code == 200
        assert response.get_json() == client.get(f"{PROJECTS}/{recipes.id}").get_json()
        assert response.get_json()["url"] == f"{BASE_URL}/projects/{recipes.slug}"

    def test_an_id_reads_its_projects_head(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        recipes = _make(container, name="Recipe box")
        _sign_in(client)

        response = client.get(HEAD, query_string={"address": str(recipes)})

        assert response.status_code == 200
        assert response.get_json()["id"] == str(recipes)

    def test_a_drafts_folder_reads_its_head(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        draft = session.get_one(Project, _make(container, state="draft"))
        _sign_in(client)

        response = client.get(HEAD, query_string={"address": f"draft-{draft.number}"})

        assert response.status_code == 200
        body = response.get_json()
        assert (body["id"], body["address"], body["state"]) == (
            str(draft.id),
            f"draft-{draft.number}",
            "draft",
        )
        assert body["url"] == f"{BASE_URL}/projects/draft-{draft.number}"

    def test_a_drafts_folder_goes_on_reading_its_project_once_created(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        recipes = session.get_one(Project, _make(container, name="Recipe box"))
        _sign_in(client)

        response = client.get(HEAD, query_string={"address": f"draft-{recipes.number}"})

        assert response.status_code == 200
        body = response.get_json()
        assert (body["id"], body["address"]) == (str(recipes.id), recipes.slug)

    def test_an_archived_projects_head_is_read(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        album = session.get_one(
            Project, _make(container, name="Photo album", archived=True)
        )
        _sign_in(client)

        response = client.get(HEAD, query_string={"address": album.slug})

        assert response.status_code == 200
        assert response.get_json()["archived"] is True

    @pytest.mark.parametrize(
        "address",
        [
            pytest.param("recipe-box", id="slug"),
            pytest.param("draft-999999", id="draft"),
            pytest.param(str(uuid.UUID(int=7)), id="id"),
        ],
    )
    def test_an_address_no_project_is_at_is_not_found(
        self, client: FlaskClient, container: ServiceContainer, address: str
    ) -> None:
        _make(container, name="Bike log")
        _sign_in(client)

        response = client.get(HEAD, query_string={"address": address})

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {address} was not found"

    @pytest.mark.parametrize("query", [{}, {"address": ""}])
    def test_no_address_is_refused(
        self, client: FlaskClient, query: dict[str, str]
    ) -> None:
        _sign_in(client)

        assert client.get(HEAD, query_string=query).status_code == 400

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        recipes = session.get_one(Project, _make(container, name="Recipe box"))
        _sign_in(client, roles=())

        response = client.get(HEAD, query_string={"address": recipes.slug})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.get(HEAD, query_string={"address": "recipe-box"})

        assert response.status_code == 401


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


ITEMS = f"{PROJECTS}/items"


@pytest.mark.usefixtures("person")
class TestListItemsAtAddress:
    def test_the_open_items_are_indexed_in_seq_order(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        recipes = session.get_one(
            Project,
            _make(
                container,
                name="Recipe box",
                open_items=2,
                environment_id=environment.id,
            ),
        )
        opening, first, second = session.scalars(
            select(Item).where(Item.project_id == recipes.id).order_by(Item.seq)
        )
        first.urgent = True
        first.for_user_id = recipes.created_by_user_id
        second.done_at = datetime.now(UTC)
        second.done_cause_code = "marked"
        session.flush()
        _sign_in(client)

        response = client.get(ITEMS, query_string={"address": recipes.slug})

        assert response.status_code == 200
        assert response.get_json() == {
            "items": [
                {
                    "seq": 1,
                    "kind": "opening",
                    "title": "Recipe box",
                    "path": f"{recipes.slug}/items/1-recipe-box.md",
                    "created_at": utc_time(opening.created_at),
                    "done_cause": None,
                    "for_handle": None,
                    "urgent": False,
                },
                {
                    "seq": 2,
                    "kind": "notice",
                    "title": "Notice 1",
                    "path": f"{recipes.slug}/items/2-notice-1.md",
                    "created_at": utc_time(first.created_at),
                    "done_cause": None,
                    "for_handle": "ada",
                    "urgent": True,
                },
            ]
        }

    def test_open_false_indexes_every_item(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        recipes = _make(
            container, name="Recipe box", open_items=1, environment_id=environment.id
        )
        notice = session.scalars(
            select(Item).where(Item.project_id == recipes, Item.seq == 2)
        ).one()
        notice.done_at = datetime.now(UTC)
        notice.done_cause_code = "marked"
        session.flush()
        _sign_in(client)

        opened = client.get(ITEMS, query_string={"address": str(recipes)})
        every = client.get(
            ITEMS, query_string={"address": str(recipes), "open": "false"}
        )

        assert [item["seq"] for item in opened.get_json()["items"]] == [1]
        assert [
            (item["seq"], item["done_cause"]) for item in every.get_json()["items"]
        ] == [(1, None), (2, "marked")]

    def test_a_kind_indexes_its_items_alone(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        environment: Environment,
    ) -> None:
        recipes = _make(
            container, name="Recipe box", open_items=2, environment_id=environment.id
        )
        _sign_in(client)

        notices = client.get(
            ITEMS, query_string={"address": str(recipes), "kind": "notice"}
        )
        waits = client.get(
            ITEMS, query_string={"address": str(recipes), "kind": "card_wait"}
        )

        assert [item["seq"] for item in notices.get_json()["items"]] == [2, 3]
        assert (waits.status_code, waits.get_json()) == (200, {"items": []})

    def test_a_drafts_folder_names_it_and_starts_its_paths(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        draft = session.get_one(Project, _make(container, state="draft"))
        run = _run(session, draft, environment)
        container.document_service().bear_item(draft, "notice", "The palette", run)
        _sign_in(client)

        response = client.get(ITEMS, query_string={"address": f"draft-{draft.number}"})

        assert response.status_code == 200
        assert [item["path"] for item in response.get_json()["items"]] == [
            f"draft-{draft.number}/items/1-the-palette.md"
        ]

    def test_an_archived_projects_items_are_indexed(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        album = session.get_one(
            Project,
            _make(container, name="Photo album", state="finished", archived=True),
        )
        _sign_in(client)

        response = client.get(ITEMS, query_string={"address": album.slug})

        assert response.status_code == 200
        assert [item["kind"] for item in response.get_json()["items"]] == ["opening"]

    def test_an_address_no_project_is_at_is_not_found(
        self, client: FlaskClient
    ) -> None:
        _sign_in(client)

        response = client.get(ITEMS, query_string={"address": "bike-log"})

        assert response.status_code == 404
        assert response.get_json()["error"] == "Project bike-log was not found"

    @pytest.mark.parametrize(
        "query",
        [
            {},
            {"address": ""},
            {"address": "recipe-box", "open": "maybe"},
            {"address": "recipe-box", "kind": "memo"},
        ],
    )
    def test_no_address_or_a_value_that_is_none_of_its_own_is_refused(
        self, client: FlaskClient, query: dict[str, str]
    ) -> None:
        _sign_in(client)

        assert client.get(ITEMS, query_string=query).status_code == 400

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, roles=())

        response = client.get(ITEMS, query_string={"address": "recipe-box"})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.get(ITEMS, query_string={"address": "recipe-box"})

        assert response.status_code == 401


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
            "archive_question": None,
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
                    "summary": None,
                    "word_count": None,
                    "read_minutes": None,
                    "writing": False,
                    "awaiting_read": False,
                    "edited_at": None,
                    "attachments": [],
                    "clarifications": [],
                    "work": None,
                    "wait": None,
                    "pilots_work": None,
                    "cancel": None,
                    "job": None,
                    "after_turn": None,
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
                            "section": None,
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
                                "in_chat": None,
                                "done": None,
                                "claim": None,
                                "held": None,
                                "deferral": None,
                                "writer_asked": False,
                                "section": None,
                            },
                        },
                    ],
                    "summary": None,
                    "word_count": 24,
                    "read_minutes": 1,
                    "writing": False,
                    "awaiting_read": False,
                    "edited_at": None,
                    "attachments": [],
                    "clarifications": [],
                    "work": None,
                    "wait": None,
                    "pilots_work": None,
                    "cancel": None,
                    "job": None,
                    "after_turn": None,
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
                    "body": [
                        {"type": "prose", "markdown": "A storm comes.", "section": None}
                    ],
                    "summary": None,
                    "word_count": 3,
                    "read_minutes": 1,
                    "writing": False,
                    "awaiting_read": False,
                    "edited_at": None,
                    "attachments": [],
                    "clarifications": [],
                    "work": None,
                    "wait": None,
                    "pilots_work": None,
                    "cancel": None,
                    "job": None,
                    "after_turn": None,
                },
            ],
            "ready_after": None,
            "unhung_attachments": [],
        }

    def test_a_work_items_entry_carries_its_session(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        camp = session.get_one(Project, _make(container, name="Camp"))
        run = _run(session, camp, environment)
        container.record_service().place_work(camp, run, "Build the camp")
        run.state_code = SessionState.RUNNING
        run.started_at = datetime.fromisoformat("2026-10-24T09:00:00+00:00")
        run.current_line = {
            "state": "working",
            "since": "2026-10-24T09:01:00+00:00",
            "step": {"tool": "Read", "input": {"file_path": "/work/Camp/plan.json"}},
        }
        session.flush()
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{camp.id}/timeline").get_json()

        _opening, work = body["items"]
        assert (
            _stamped(work, ("work", "started_at")),
            _stamped(work, ("work", "current_line", "since")),
        ) == (run.started_at, datetime.fromisoformat("2026-10-24T09:01:00+00:00"))
        assert work["work"] == {
            "state": "running",
            "current_line": {
                "state": "working",
                "since": "<time>",
                "step": {
                    "tool": "Read",
                    "input": {"file_path": "/work/Camp/plan.json"},
                },
                "agent": None,
                "text": None,
            },
            "environment": {"id": environment.id, "name": "Example-1"},
            "started_at": "<time>",
            "error": None,
            "autopilot": False,
            "pilots_own": False,
            "setup": False,
            "held_reason": None,
            "held_running": None,
            "stopped_at": None,
            "stopped_by": None,
            "stopped_cause": None,
            "nudge_owed": False,
            "retried": None,
            "progress": [],
        }

    def test_a_block_s_own_section_rides_with_its_text(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        camp = session.get_one(Project, _make(container, name="Camp"))
        container.document_service().bear_item(
            camp,
            "document",
            "Camp kit",
            _run(session, camp, environment),
            "# Camp kit\n\nWhat we bring.\n\n## Which tent?\n\n"
            "```question id=Q1\n```\n",
        )
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{camp.id}/timeline").get_json()

        parts = body["items"][1]["body"]
        assert [
            (part["type"], part.get("markdown"), part.get("section")) for part in parts
        ] == [
            ("prose", "What we bring.", None),
            ("prose", "## Which tent?", "Q1"),
            ("block", None, None),
        ]
        assert parts[2]["block"]["section"] == {"heading": "Which tent?"}

    def test_a_documents_summary_writing_and_attachments_ride_with_it(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        camp = _make(container, name="Camp", environment_id=environment.id)
        data = container.test_data_service()
        item = data.item(
            camp,
            "review",
            "Camp kit",
            "---\ntitle: Camp kit\nsummary: What we bring.\n---\n\nBoots.\n",
        )
        data.save(
            item.id,
            "---\ntitle: Camp kit\nsummary: What we bring.\n---\n\nBoots, a tent.\n",
        )
        (sketch,) = data.attach(
            item.id,
            [
                InventedFileSchema.model_validate(
                    {
                        "title": "Sketch",
                        "filename": "sketch.md",
                        "content_type": "text/markdown",
                        "content": base64.b64encode(b"# Sketch\n").decode(),
                    }
                )
            ],
        )
        _sign_in(client)

        body = client.get(f"{PROJECTS}/{camp}/timeline").get_json()

        line = body["items"][1]
        assert _stamped(line, ("attachments", 0, "copied_at")) == sketch.copied_at
        assert {
            key: line[key]
            for key in (
                "summary",
                "word_count",
                "read_minutes",
                "writing",
                "edited_at",
                "attachments",
            )
        } == {
            "summary": "What we bring.",
            "word_count": 3,
            "read_minutes": 1,
            "writing": True,
            "edited_at": None,
            "attachments": [
                {
                    "id": str(sketch.id),
                    "title": "Sketch",
                    "filename": "sketch.md",
                    "content_type": "text/markdown",
                    "size": 9,
                    "batch": 1,
                    "copied_at": "<time>",
                    "source": f"{environment.id}:/work/Invented/sketch.md",
                }
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
        assert body["archive_question"] is None
        assert [item["kind"] for item in body["items"]] == ["opening"]

    def test_a_project_finished_by_finish_has_its_archive_question(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client)
        client.post(f"{PROJECTS}/{camp}/transitions", json={"kind": "finished"})

        body = client.get(f"{PROJECTS}/{camp}/timeline").get_json()

        assert body["items"][-1]["kind"] == "archive_question"
        assert body["archive_question"] == body["items"][-1]["id"]

    def test_the_timeline_is_answered_as_read_and_never_validated_again(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client)
        expected = container.timeline_service().timeline(camp).model_dump(mode="json")

        def validated_again(*_: object, **__: object) -> None:
            raise AssertionError("the timeline was validated again")

        monkeypatch.setattr(TimelineSchema, "model_validate", validated_again)
        monkeypatch.setattr(TimelineSchema, "model_validate_json", validated_again)
        response = client.get(f"{PROJECTS}/{camp}/timeline")

        assert response.status_code == 200
        assert response.get_json() == expected

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
class TestGetProjectDocuments:
    """The project's draft, `project.md`, and its handbook, read only."""

    def test_the_handbook_born_at_create_reads_empty_the_draft_its_name(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client)

        handbook = client.get(f"{PROJECTS}/{camp}/handbook")
        draft = client.get(f"{PROJECTS}/{camp}/draft")

        assert (handbook.status_code, handbook.get_json()) == (
            200,
            {"title": None, "body": [], "writing": False},
        )
        assert (draft.status_code, draft.get_json()) == (
            200,
            {"title": "Camp", "body": [], "writing": False},
        )

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_a_save_reads_as_drawn_while_pilot_writes_it(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        environment: Environment,
        document: str,
    ) -> None:
        camp = _make(container, name="Camp", environment_id=environment.id)
        container.test_data_service().save_project_document(
            camp, DocumentRole(document), "# Camp\n\nTwo tents.\n"
        )
        _sign_in(client)

        response = client.get(f"{PROJECTS}/{camp}/{document}")

        assert response.status_code == 200
        assert response.get_json() == {
            "title": "Camp",
            "body": [{"type": "prose", "markdown": "Two tents.", "section": None}],
            "writing": True,
        }

    def test_a_drafts_handbook_is_not_found(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        draft = _make(container, state="draft")
        _sign_in(client)

        response = client.get(f"{PROJECTS}/{draft}/handbook")

        assert response.status_code == 404
        assert response.get_json()["error"] == (
            f"Handbook of project {draft} was not found"
        )

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_an_unknown_project_is_not_found(
        self, client: FlaskClient, document: str
    ) -> None:
        _sign_in(client)
        unknown = uuid.uuid4()

        response = client.get(f"{PROJECTS}/{unknown}/{document}")

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Project {unknown} was not found"

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_an_id_that_is_no_uuid_is_not_found(
        self, client: FlaskClient, document: str
    ) -> None:
        _sign_in(client)

        assert client.get(f"{PROJECTS}/camp/{document}").status_code == 404

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer, document: str
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client, roles=())

        assert client.get(f"{PROJECTS}/{camp}/{document}").status_code == 403

    @pytest.mark.parametrize("document", ["draft", "handbook"])
    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient, document: str
    ) -> None:
        response = oidc_client.get(f"{PROJECTS}/{uuid.uuid4()}/{document}")

        assert response.status_code == 401


DRAFT_ASKS = """---
title: Camp
---

```question id=Q1
default: The lake
```

```action id=A1
```
"""


def _drafted(container: ServiceContainer, environment: Environment) -> uuid.UUID:
    """A draft whose `project.md` Pilot wrote with two asks."""
    draft = _make(container, state="draft", environment_id=environment.id)
    container.test_data_service().save_project_document(
        draft, DocumentRole.DRAFT, DRAFT_ASKS
    )
    return draft


def _draft_block(client: FlaskClient, project_id: uuid.UUID, local_id: str) -> Any:
    body = client.get(f"{PROJECTS}/{project_id}/draft").get_json()["body"]
    return next(
        part["block"]
        for part in body
        if part["type"] == "block" and part["block"]["id"] == local_id
    )


@pytest.mark.usefixtures("person")
class TestAnswerDraftBlock:
    """A person's answer to the draft's ask, in place (F47.4)."""

    def test_the_answer_is_written_into_the_draft(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{draft}/draft/blocks/Q1/answer",
            json={"answer": "The forest", "note": "Shade."},
        )

        assert response.status_code == 204
        block = _draft_block(client, draft, "Q1")
        assert (
            block["answer"],
            block["by"]["handle"],
            block["via"],
            block["note"],
        ) == (
            "The forest",
            "ada",
            "app",
            "Shade.",
        )

    def test_past_create_project_md_takes_no_answer(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{camp}/draft/blocks/Q1/answer", json={"answer": "The lake"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"].endswith(
            "because the project is no draft: its `project.md` takes no answer"
        )

    def test_an_unknown_project_or_ask_is_not_found(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        unknown = client.post(
            f"{PROJECTS}/{uuid.uuid4()}/draft/blocks/Q1/answer",
            json={"answer": "The lake"},
        )
        no_ask = client.post(
            f"{PROJECTS}/{draft}/draft/blocks/Q9/answer", json={"answer": "The lake"}
        )

        assert (unknown.status_code, no_ask.status_code) == (404, 404)

    def test_a_body_that_is_no_answer_is_refused(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{draft}/draft/blocks/Q1/answer", json={})

        assert response.status_code == 400

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client, roles=())

        response = client.post(
            f"{PROJECTS}/{draft}/draft/blocks/Q1/answer", json={"answer": "The lake"}
        )

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            f"{PROJECTS}/{uuid.uuid4()}/draft/blocks/Q1/answer",
            json={"answer": "The lake"},
        )

        assert response.status_code == 401


@pytest.mark.usefixtures("person")
class TestMarkDraftActionDone:
    """Done on the draft's action without options, in place (F47.4)."""

    def test_the_done_is_written_into_the_draft_with_the_paste_back(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{draft}/draft/blocks/A1/done", json={"note": "Pitched."}
        )

        assert response.status_code == 204
        block = _draft_block(client, draft, "A1")
        assert (block["done"] is not None, block["by"]["handle"], block["note"]) == (
            True,
            "ada",
            "Pitched.",
        )

    def test_a_question_takes_no_done(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{draft}/draft/blocks/Q1/done", json={})

        assert response.status_code == 409
        assert response.get_json()["error"].endswith(
            "because block Q1 is a question, not an action"
        )

    def test_past_create_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        camp = _make(container, name="Camp")
        _sign_in(client)

        response = client.post(f"{PROJECTS}/{camp}/draft/blocks/A1/done", json={})

        assert response.status_code == 409

    def test_an_unknown_project_is_not_found(self, client: FlaskClient) -> None:
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{uuid.uuid4()}/draft/blocks/A1/done", json={}
        )

        assert response.status_code == 404

    def test_without_editor_it_is_refused(
        self, client: FlaskClient, container: ServiceContainer, environment: Environment
    ) -> None:
        draft = _drafted(container, environment)
        _sign_in(client, roles=())

        response = client.post(f"{PROJECTS}/{draft}/draft/blocks/A1/done", json={})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(
            f"{PROJECTS}/{uuid.uuid4()}/draft/blocks/A1/done", json={}
        )

        assert response.status_code == 401


CAMP_DRAFT = "---\ntitle: Camp site\nslug: camp-site\n---\n\nNear a lake.\n"


def _definition_chat(
    session: Session, draft: Project, author: User, words: str
) -> None:
    """The draft's definition chat, idle after `author`'s first message."""
    run = models.Session(
        project_id=draft.id,
        kind_code="chat",
        cwd=STORE_REPO,
        token_hash=uuid.uuid4().hex * 2,
        state_code=SessionState.IDLE,
    )
    session.add(run)
    session.flush()
    session.add(
        Chat(
            id=run.id,
            project_id=draft.id,
            session_kind_code="chat",
            kind_code=ChatKind.DEFINITION,
        )
    )
    now = datetime.now(UTC)
    session.add(
        Turn(
            session_id=run.id,
            seq=1,
            author_user_id=author.id,
            message=words,
            words=words,
            started_at=now,
            ended_at=now,
        )
    )
    session.flush()


_PUSH = """---
title: Push the release
---

```decision id=C1
type: confirmation
because: rider
proposal: Push with the map fix riding along.
```
"""


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
        ) == ("finished", False, False, True, 1)
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
                    Item.project_id == recipes,
                    Item.kind_code.not_in(["opening", "archive_question"]),
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

    def test_auto_pilot_on_with_the_yes_answers_the_confirmations_it_takes(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
        person: User,
    ) -> None:
        recipes = _make(container, name="Recipe box")
        project = session.get_one(Project, recipes)
        item = container.document_service().bear_item(
            project,
            "decision",
            "Push the release",
            _run(session, project, environment),
            _PUSH,
        )
        _sign_in(client)
        assert client.get(f"{PROJECTS}/{recipes}").get_json()["autopilot_may_take"] == 1

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions",
            json={"kind": "autopilot_on", "answer_confirmations": True},
        )

        assert response.status_code == 201
        body = response.get_json()
        assert (body["autopilot"], body["autopilot_may_take"]) == (True, 0)
        block = session.scalars(select(Block).where(Block.document_id == item.id)).one()
        assert (block.answer, block.answered_by_user_id, block.via_code) == (
            "Yes",
            person.id,
            AnswerChannel.AUTOPILOT,
        )

    def test_auto_pilot_on_without_the_yes_leaves_them_open(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        session: Session,
        environment: Environment,
    ) -> None:
        recipes = _make(container, name="Recipe box")
        project = session.get_one(Project, recipes)
        container.document_service().bear_item(
            project,
            "decision",
            "Push the release",
            _run(session, project, environment),
            _PUSH,
        )
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions",
            json={"kind": "autopilot_on", "answer_confirmations": False},
        )

        assert response.status_code == 201
        body = response.get_json()
        assert (body["autopilot"], body["autopilot_may_take"]) == (True, 1)

    @pytest.mark.parametrize("kind", ["finished", "autopilot_off", "paused"])
    def test_the_yes_with_another_kind_is_refused(
        self, client: FlaskClient, container: ServiceContainer, kind: str
    ) -> None:
        recipes = _make(container, name="Recipe box", autopilot=True)
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{recipes}/transitions",
            json={"kind": kind, "answer_confirmations": True},
        )

        assert response.status_code == 400

    def test_a_pause_and_a_resume_answer_the_head_with_its_status(
        self, client: FlaskClient, container: ServiceContainer, session: Session
    ) -> None:
        recipes = _make(container, name="Recipe box", autopilot=True)
        _sign_in(client)

        paused = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "paused"}
        )
        again = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "paused"}
        )
        resumed = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "resumed"}
        )

        assert (paused.status_code, again.status_code, resumed.status_code) == (
            201,
            409,
            201,
        )
        assert [
            (body["status"], body["autopilot"])
            for body in (paused.get_json(), resumed.get_json())
        ] == [("paused", True), ("idle", True)]
        assert again.get_json()["error"] == (
            "Cannot pause Recipe box because it is paused already"
        )
        assert [
            transition.kind_code
            for transition in session.scalars(
                select(ProjectTransition)
                .where(ProjectTransition.project_id == recipes)
                .order_by(ProjectTransition.at, ProjectTransition.id)
            )
        ][-2:] == [TransitionKind.PAUSED, TransitionKind.RESUMED]

    def test_archive_and_bring_back_move_the_folder_out_of_the_stores_tree_and_back(
        self,
        client: FlaskClient,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
    ) -> None:
        recipes = _make(container, name="Recipe box")
        fake_sidecar.connect()
        fake_sidecar.drain()
        synced = set(fake_sidecar.tree)
        _sign_in(client)

        archived = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "archived"}
        )
        fake_sidecar.drain()

        assert archived.status_code == 201
        assert set(fake_sidecar.tree) == {"reference.json"} != synced

        brought_back = client.post(
            f"{PROJECTS}/{recipes}/transitions", json={"kind": "brought_back"}
        )
        fake_sidecar.drain()

        assert brought_back.status_code == 201
        tree = container.tree_service()
        assert fake_sidecar.tree == {
            entry.path: tree.read(entry.path).content for entry in tree.manifest()
        }
        assert set(fake_sidecar.tree) == synced

    @pytest.mark.usefixtures("starts")
    def test_create_project_opens_the_draft_and_moves_its_folder(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        person: User,
    ) -> None:
        fake_sidecar.connect()
        _sign_in(client)
        draft = container.project_service().create(ADA)
        _definition_chat(session, draft, person, "Find us a camp site.")
        container.document_service().publish(
            session.scalars(
                select(Document).where(
                    Document.project_id == draft.id,
                    Document.role_code == DocumentRole.DRAFT,
                )
            ).one(),
            CAMP_DRAFT,
        )
        fake_sidecar.drain()

        response = client.post(
            f"{PROJECTS}/{draft.id}/transitions", json={"kind": "opened"}
        )
        fake_sidecar.drain()

        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        assert (
            body["name"],
            body["address"],
            body["state"],
            body["create_refusal"],
        ) == ("Camp site", "camp-site", "open", "it is no draft")
        assert client.get(
            f"{PROJECTS}/lookup", query_string={"address": f"draft-{draft.number}"}
        ).get_json() == {"id": str(draft.id), "address": "camp-site"}
        assert sorted(fake_sidecar.tree) == [
            "camp-site/attachments/1/project.md",
            "camp-site/chat.md",
            "camp-site/handbook.md",
            "camp-site/items/1-ada-example-started-this-project.md",
            "camp-site/plan.json",
            "camp-site/project.md",
            "camp-site/timeline.json",
            "reference.json",
        ]
        tree = container.tree_service()
        assert fake_sidecar.tree == {
            entry.path: tree.read(entry.path).content for entry in tree.manifest()
        }
        (opening, setup) = client.get(f"{PROJECTS}/{draft.id}/timeline").get_json()[
            "items"
        ]
        assert (opening["kind"], opening["words"]) == (
            "opening",
            "Find us a camp site.",
        )
        assert (setup["kind"], setup["title"]) == ("work", SETUP_TITLE)
        assert (
            setup["work"]["state"],
            setup["work"]["pilots_own"],
            setup["work"]["environment"],
        ) == ("starting", True, None)

    def test_create_project_is_refused_with_its_reason(
        self, client: FlaskClient, container: ServiceContainer
    ) -> None:
        draft = container.project_service().create(ADA).id
        _sign_in(client)

        response = client.post(
            f"{PROJECTS}/{draft}/transitions", json={"kind": "opened"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot create the untitled project because nothing is drafted"
        )
        assert client.get(f"{PROJECTS}/{draft}").get_json()["state"] == "draft"

    @pytest.mark.parametrize(
        "body",
        [{"kind": "pausing"}, {"kind": None}, {}],
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
class TestCreateProject:
    def test_the_first_message_makes_the_draft_answers_its_head_and_starts_its_chat(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        starts: None,
    ) -> None:
        fake_sidecar.connect()
        fake_sidecar.drain()
        _sign_in(client)

        response = client.post(PROJECTS, json={"words": "Plan the summer trip."})
        fake_sidecar.drain()

        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        draft = session.get_one(Project, uuid.UUID(body["id"]))
        assert body == {
            "id": body["id"],
            "address": f"draft-{draft.number}",
            "name": None,
            "ticket": None,
            "repo": None,
            "state": "draft",
            "archived": False,
            "autopilot": False,
            "status": None,
            "member": True,
            "members": [
                {
                    "handle": "ada",
                    "name": "Ada Example",
                    "initials": "AE",
                    "avatar_slot": 1,
                }
            ],
            "progress": {"done": 0, "total": 0, "in_progress": []},
            "tasks": [],
            "notes": [],
            "running_work": [],
            "open_items": 0,
            "autopilot_may_take": 0,
            "create_refusal": "Pilot is writing",
            "url": f"{BASE_URL}/projects/draft-{draft.number}",
        }
        (chat,) = session.scalars(select(Chat)).all()
        assert (chat.project_id, chat.kind_code) == (draft.id, ChatKind.DEFINITION)
        turn = session.scalars(select(Turn)).one()
        assert (turn.session_id, turn.words) == (chat.id, "Plan the summer trip.")
        assert turn.message.endswith("\n\nThe message:\nPlan the summer trip.")
        assert session.get_one(models.Session, chat.id).state_code is (
            SessionState.STARTING
        )
        assert fake_sidecar.tree[f"draft-{draft.number}/project.md"] == b""
        tree = container.tree_service()
        assert fake_sidecar.tree == {
            entry.path: tree.read(entry.path).content for entry in tree.manifest()
        }
        listed = client.get(PROJECTS).get_json()["projects"]
        assert [
            (tab["id"], tab["name"], tab["state"], tab["member"]) for tab in listed
        ] == [(body["id"], None, "draft", True)]

    @pytest.mark.parametrize("payload", [{"words": "  \n"}, {"words": ""}, {}])
    def test_a_message_without_words_is_400_and_makes_no_draft(
        self,
        client: FlaskClient,
        session: Session,
        starts: None,
        payload: dict[str, str],
    ) -> None:
        _sign_in(client)

        response = client.post(PROJECTS, json=payload)

        assert response.status_code == 400
        assert session.scalars(select(Project)).all() == []

    def test_a_caller_without_a_handle_is_a_conflict(
        self, client: FlaskClient, session: Session, starts: None
    ) -> None:
        _sign_in(client, subject="subject-newcomer")

        response = client.post(PROJECTS, json={"words": "Hi"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot start a new project because you have not chosen your handle yet"
        )
        assert session.scalars(select(Project)).all() == []

    def test_a_message_while_pilot_updates_its_store_is_a_conflict_and_leaves_no_draft(
        self, client: FlaskClient, session: Session, starts: None
    ) -> None:
        _sign_in(client)
        hold(session)

        response = client.post(PROJECTS, json={"words": "Hi"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot send a message to Pilot in the untitled project because Pilot"
            " is updating"
        )
        assert session.scalars(select(Project)).all() == []
        assert session.scalars(select(Chat)).all() == []

    def test_a_message_with_no_controller_configured_is_a_conflict_and_leaves_no_draft(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        supervise: Supervise,
    ) -> None:
        container.session_start_service.override(
            providers.Object(
                configured_starts(container, supervise, controller_configured=False)
            )
        )
        try:
            _sign_in(client)

            response = client.post(PROJECTS, json={"words": "Hi"})
        finally:
            container.session_start_service.reset_last_overriding()

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot send a message to Pilot in the untitled project because no"
            " controller is configured"
        )
        assert session.scalars(select(Project)).all() == []
        assert session.scalars(select(ProjectMember)).all() == []
        assert session.scalars(select(Document)).all() == []
        assert session.scalars(select(Chat)).all() == []

    def test_without_editor_it_is_refused(self, client: FlaskClient) -> None:
        _sign_in(client, roles=())

        response = client.post(PROJECTS, json={"words": "Hi"})

        assert response.status_code == 403

    def test_without_a_token_it_is_unauthenticated(
        self, oidc_client: FlaskClient
    ) -> None:
        response = oidc_client.post(PROJECTS, json={"words": "Hi"})

        assert response.status_code == 401


BRIEF = "Sort the inbox.\n\nStart with the oldest card."

CALLER = "example-recipebox-1a2b3c"
"""The id of the environment a call comes from, which Pilot has no row of."""


def _call(
    client: FlaskClient, payload: dict[str, Any], environment: str | None = CALLER
) -> Any:
    """A call's create as Pilot's MCP process makes it: the plus's route, with
    the calling environment's id in its header where the caller sent one."""
    headers = {} if environment is None else {CALLER_ENVIRONMENT_HEADER: environment}
    return client.post(PROJECTS, json=payload, headers=headers)


def _members(session: Session, project_id: uuid.UUID) -> list[str]:
    return list(
        session.scalars(
            select(User.handle)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.id)
        )
    )


def _started(session: Session) -> str:
    """Who started the one draft there is, as its definition chat's brief
    says it: the sentence after the draft's own."""
    message = session.scalars(select(Turn.message)).one()
    (line,) = [line for line in message.splitlines() if line.startswith("The draft: ")]
    return line.removeprefix("The draft: project.md, empty. ")


@pytest.mark.usefixtures("person", "starts")
class TestCreateProjectByCall:
    """`POST /api/projects` as a service user: a call's draft (F150.9, F150.13;
    DB 339; V18 to V20). The successor of the refusal `test_service_user.py`
    pinned for this route until slice 045's P5."""

    @pytest.fixture(autouse=True)
    def _as_the_service_user(self, client: FlaskClient, service_user: User) -> None:
        _sign_in(client, subject=service_user.subject)

    def test_the_call_makes_the_service_users_draft_and_starts_its_chat_with_the_brief(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        fake_sidecar: FakeSidecar,
        service_user: User,
    ) -> None:
        fake_sidecar.connect()
        fake_sidecar.drain()

        response = _call(
            client, {"words": BRIEF, "title": "Sort the inbox", "for": "ada"}
        )
        fake_sidecar.drain()

        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        draft = session.get_one(Project, uuid.UUID(body["id"]))
        assert body == {
            "id": body["id"],
            "address": f"draft-{draft.number}",
            "name": "Sort the inbox",
            "ticket": None,
            "repo": None,
            "state": "draft",
            "archived": False,
            "autopilot": False,
            "status": None,
            "member": False,
            "members": [
                {
                    "handle": "ada",
                    "name": "Ada Example",
                    "initials": "AE",
                    "avatar_slot": 1,
                }
            ],
            "progress": {"done": 0, "total": 0, "in_progress": []},
            "tasks": [],
            "notes": [],
            "running_work": [],
            "open_items": 0,
            "autopilot_may_take": 0,
            "create_refusal": "Pilot is writing",
            "url": f"{BASE_URL}/projects/draft-{draft.number}",
        }
        assert draft.created_by_user_id == service_user.id
        assert session.scalars(select(ProjectTransition)).all() == []
        (chat,) = session.scalars(select(Chat)).all()
        assert (chat.project_id, chat.kind_code) == (draft.id, ChatKind.DEFINITION)
        turn = session.scalars(select(Turn)).one()
        assert (turn.session_id, turn.seq, turn.author_user_id, turn.words) == (
            chat.id,
            1,
            service_user.id,
            BRIEF,
        )
        assert turn.message == (
            "/create\n\n"
            'Pilot\'s brief · the definition chat · project "Sort the inbox" ·'
            f" /work/Projects/draft-{draft.number} · {utc_time(turn.started_at)}\n\n"
            f"The draft: project.md. Started by a call from {CALLER}, for ada.\n"
            "Attachments so far: none.\n\n"
            "The message:\n"
            f"{BRIEF}"
        )
        assert session.get_one(models.Session, chat.id).state_code is (
            SessionState.STARTING
        )
        assert fake_sidecar.tree[f"draft-{draft.number}/project.md"] == (
            b"---\ntitle: Sort the inbox\n---\n"
        )
        tree = container.tree_service()
        assert fake_sidecar.tree == {
            entry.path: tree.read(entry.path).content for entry in tree.manifest()
        }

    def test_a_member_reads_the_calls_draft_and_its_chat_the_service_user_its_author(
        self, client: FlaskClient
    ) -> None:
        draft = _call(client, {"words": BRIEF, "for": "ada"}).get_json()["id"]
        _sign_in(client)

        head = client.get(f"{PROJECTS}/{draft}")
        timeline = client.get(f"{PROJECTS}/{draft}/timeline")
        chats = client.get(f"{PROJECTS}/{draft}/chats")

        assert (head.status_code, timeline.status_code, chats.status_code) == (
            200,
            200,
            200,
        )
        assert head.get_json()["member"] is True
        (chat,) = chats.get_json()["chats"]
        assert chat["kind"] == "definition"

    def test_its_members_are_the_person_for_names_and_everyone_whose_switch_is_on(
        self, client: FlaskClient, session: Session, container: ServiceContainer
    ) -> None:
        people = container.people_service()
        ben = container.test_data_service().person("ben", "Ben Example")
        people.switch_join_calls(ben, False)
        cy = container.test_data_service().person("cy", "Cy Example")
        people.switch_join_calls(cy, False)

        response = _call(client, {"words": BRIEF, "for": "cy"})

        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        assert [member["handle"] for member in body["members"]] == ["ada", "cy"]
        assert _members(session, uuid.UUID(body["id"])) == ["ada", "cy"]

    def test_a_call_with_nobody_to_join_still_makes_its_draft(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        person: User,
    ) -> None:
        container.people_service().switch_join_calls(person, False)

        response = _call(client, {"words": BRIEF})

        assert response.status_code == 201, response.get_json()
        body = response.get_json()
        assert (body["name"], body["member"], body["members"]) == (None, False, [])
        assert _members(session, uuid.UUID(body["id"])) == []
        assert session.scalars(select(Turn.words)).one() == BRIEF

    def test_an_environment_neither_pilot_nor_the_controller_knows_is_named_by_its_id(
        self, client: FlaskClient, session: Session
    ) -> None:
        response = _call(client, {"words": BRIEF})

        assert response.status_code == 201, response.get_json()
        assert _started(session) == f"Started by a call from {CALLER}."

    def test_pilots_own_row_names_the_environment(
        self, client: FlaskClient, session: Session, environment: Environment
    ) -> None:
        response = _call(client, {"words": BRIEF, "for": "ada"}, STORE_ENVIRONMENT_ID)

        assert response.status_code == 201, response.get_json()
        assert _started(session) == "Started by a call from Example-1, for ada."

    def test_the_controllers_report_names_an_environment_pilot_has_no_row_of(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        controller_client: ControllerClient,
        fake_controller: ServedFakeController,
    ) -> None:
        fake_controller.add_environment(CALLER, name="RecipeBox-2")
        container.caller_environment_service.override(
            providers.Factory(
                CallerEnvironmentService,
                db=container.db_session,
                controller_client=container.controller_client.provider,
                controller_configured=True,
            )
        )
        try:
            response = _call(client, {"words": BRIEF})
        finally:
            container.caller_environment_service.reset_last_overriding()

        assert response.status_code == 201, response.get_json()
        assert _started(session) == "Started by a call from RecipeBox-2."
        assert session.scalars(select(Environment)).all() == []

    @pytest.mark.parametrize("environment", [None, ""])
    def test_a_call_that_names_no_environment_names_none_in_its_brief(
        self, client: FlaskClient, session: Session, environment: str | None
    ) -> None:
        response = _call(client, {"words": BRIEF, "for": "ada"}, environment)

        assert response.status_code == 201, response.get_json()
        assert _started(session) == "Started by a call, for ada."

    @pytest.mark.parametrize("handle", ["nobody", "fleet", "agent"])
    def test_a_for_that_names_no_person_is_not_found_and_makes_no_draft(
        self, client: FlaskClient, session: Session, handle: str
    ) -> None:
        response = _call(client, {"words": BRIEF, "for": handle})

        assert response.status_code == 404
        assert response.get_json()["error"] == f"Person {handle} was not found"
        assert session.scalars(select(Project)).all() == []

    @pytest.mark.parametrize(
        "payload",
        [
            {"words": "  \n"},
            {},
            {"words": BRIEF, "title": "  "},
            {"words": BRIEF, "title": "Sort\nthe inbox"},
            {"words": BRIEF, "for": ""},
        ],
    )
    def test_a_call_without_a_brief_or_with_a_title_or_for_that_is_none_is_400(
        self, client: FlaskClient, session: Session, payload: dict[str, str]
    ) -> None:
        response = _call(client, payload)

        assert response.status_code == 400
        assert session.scalars(select(Project)).all() == []

    def test_a_call_while_pilot_updates_its_store_is_a_conflict_and_leaves_no_draft(
        self, client: FlaskClient, session: Session
    ) -> None:
        hold(session)

        response = _call(client, {"words": BRIEF, "title": "Sort the inbox"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot send a message to Pilot in Sort the inbox because Pilot is updating"
        )
        assert session.scalars(select(Project)).all() == []
        assert session.scalars(select(Chat)).all() == []

    @pytest.mark.parametrize(
        "named", [{"title": "Sort the inbox"}, {"for": "ada"}], ids=["title", "for"]
    )
    def test_a_person_names_no_title_and_no_for(
        self, client: FlaskClient, session: Session, named: dict[str, str]
    ) -> None:
        _sign_in(client)

        response = client.post(PROJECTS, json={"words": "Hi"} | named)

        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "Cannot start a new project with a title or for a person because a"
            " call alone names them"
        )
        assert session.scalars(select(Project)).all() == []

    @pytest.mark.parametrize(
        "named", [{"title": "Sort the inbox"}, {"for": "ada"}], ids=["title", "for"]
    )
    def test_a_caller_with_no_row_naming_a_title_or_for_is_told_of_the_row(
        self, client: FlaskClient, session: Session, named: dict[str, str]
    ) -> None:
        _sign_in(client, subject="subject-newcomer")

        response = client.post(PROJECTS, json={"words": "Hi"} | named)

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot start a new project because you have not chosen your handle yet"
        )
        assert session.scalars(select(Project)).all() == []

    def test_a_persons_create_reads_no_calling_environment(
        self, client: FlaskClient, session: Session
    ) -> None:
        _sign_in(client)

        response = _call(client, {"words": "Plan the summer trip."})

        assert response.status_code == 201, response.get_json()
        assert _started(session) == "The person who started it: ada (member)."


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
