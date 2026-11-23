"""/api/dashboard's writes of what the dashboard stores (F155): the saved
views saved, renamed and removed, a system view by no one; a person's stars
and favourite dimensions; the quick filters made and removed; the ratios a
person made, made, changed and removed, a loaded one by no one; and the load
of the workflow's views and ratios, the service user's alone, on an invented
file (F155.3)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import CustomRatio, QuickFilter, SavedView, User
from app.models.reference import Origin, UserKind
from tests.support import workflow_views

VIEWS = "/api/dashboard/saved-views"
FAVOURITES = "/api/dashboard/favourites"
DIMENSIONS = "/api/dashboard/favourites/dimensions"
QUICK_FILTERS = "/api/dashboard/quick-filters"
RATIOS = "/api/dashboard/custom-ratios"
WORKFLOW = "/api/dashboard/workflow"
STATE = "t=d7&by=model&m=cost.sum&col=none"
OTHER_STATE = "t=qw&by=project&m=cost.sum&col=none"
EARLIER = datetime(2026, 11, 1, 9, tzinfo=UTC)
NOWHERE = uuid.UUID("00000000-0000-4000-8000-000000000000")
"""An id no row has."""


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


def _error(response: Any) -> str:
    message: str = response.get_json()["error"]
    return message


def _stored(client: FlaskClient) -> dict[str, Any]:
    response = client.get("/api/dashboard/catalogue", query_string={"part": "stored"})
    assert response.status_code == 200
    body: dict[str, Any] = response.get_json()
    return body


def _system(db: DbSession, name: str = "Projects") -> SavedView:
    return db.scalars(
        select(SavedView).where(SavedView.system.is_(True), SavedView.name == name)
    ).one()


def _save(client: FlaskClient, name: str = "Opus", state: str = STATE) -> Any:
    return client.post(VIEWS, json={"name": name, "state": state})


def _loaded_ratio(db: DbSession) -> CustomRatio:
    ratio = CustomRatio(
        origin_code=Origin.WORKFLOW,
        key="per_crate",
        name="Cost per crate",
        numerator="cost.sum",
        denominator="calls.count",
        saved_at=EARLIER,
    )
    db.add(ratio)
    db.flush()
    return ratio


class TestSaveView:
    def test_a_view_one_person_saves_opens_whole_for_another(
        self, client: FlaskClient, session: DbSession, person: User
    ) -> None:
        """F155: a view is passed on by saving it."""
        _sign_in(client)

        response = client.post(
            VIEWS,
            json={
                "name": " Opus ",
                "state": "#dash/m=cost.sum&by=model&t=d7&roll=5,5",
                "note": "The big model's week",
            },
        )

        assert response.status_code == 201
        body = response.get_json()
        view = body["view"]
        assert {key: value for key, value in view.items() if key != "saved_at"} == {
            "id": view["id"],
            "system": False,
            "origin": "person",
            "key": None,
            "name": "Opus",
            "address": "#dash/" + STATE + "&roll=5,5",
            "note": "The big model's week",
        }
        assert body["notes"] == []

        _sign_in(client, subject="subject-bea")
        listed = [one for one in _stored(client)["saved_views"] if not one["system"]]
        assert listed == [view]
        opened = client.get(
            "/api/dashboard/address", query_string={"state": view["address"]}
        )
        assert opened.get_json()["address"] == view["address"]

    def test_a_save_under_a_saved_views_name_replaces_it(
        self, client: FlaskClient
    ) -> None:
        first = _save(client).get_json()["view"]

        response = _save(client, state=OTHER_STATE)

        assert response.status_code == 200
        replaced = response.get_json()["view"]
        assert (replaced["id"], replaced["address"]) == (
            first["id"],
            "#dash/" + OTHER_STATE,
        )

    def test_a_system_views_name_saves_one_beside_it(self, client: FlaskClient) -> None:
        assert _save(client, name="Projects").status_code == 201

        names = [(one["system"], one["name"]) for one in _stored(client)["saved_views"]]
        assert names.count((True, "Projects")) == 1
        assert names.count((False, "Projects")) == 1

    def test_a_part_dropped_has_a_note(self, client: FlaskClient) -> None:
        body = _save(client, state=STATE + "&b=shelf").get_json()

        assert body["view"]["address"] == "#dash/" + STATE
        assert body["notes"] == [
            'b=shelf: no quick filter has the key "shelf", so it is dropped.'
        ]

    def test_a_state_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = _save(client, state="by=projet")

        assert response.status_code == 400
        assert _error(response) == (
            "Cannot read the view because its state has 1 fault.\n"
            '- by=projet: "projet" is no dimension. Did you mean "project"? By '
            "takes a part or an attribute; the catalogue's dimensions list them.\n"
            "A By reads by=<dimension>, as in by=project."
        )

    @pytest.mark.parametrize(
        "body", [{"state": STATE}, {"name": "  ", "state": STATE}, {"name": "Opus"}]
    )
    def test_no_name_or_no_state_is_refused(
        self, client: FlaskClient, body: dict[str, str]
    ) -> None:
        assert client.post(VIEWS, json=body).status_code == 400


class TestRenameView:
    def test_a_saved_view_is_renamed(self, client: FlaskClient) -> None:
        view = _save(client).get_json()["view"]

        response = client.patch(f"{VIEWS}/{view['id']}", json={"name": "Opus week"})

        assert response.status_code == 200
        assert response.get_json() == {**view, "name": "Opus week"}

    def test_no_name_is_refused(self, client: FlaskClient) -> None:
        view = _save(client).get_json()["view"]

        assert client.patch(f"{VIEWS}/{view['id']}", json={}).status_code == 400

    def test_no_view_is_not_found(self, client: FlaskClient) -> None:
        response = client.patch(f"{VIEWS}/{uuid.uuid4()}", json={"name": "Mine"})

        assert response.status_code == 404

    def test_a_system_view_is_refused(
        self, client: FlaskClient, session: DbSession
    ) -> None:
        response = client.patch(f"{VIEWS}/{_system(session).id}", json={"name": "Mine"})

        assert response.status_code == 409
        assert _error(response) == (
            'Cannot rename the view "Projects" because it is a system view, which '
            "the system manages: a star is all a person changes of it"
        )

    def test_another_saved_views_name_is_refused(self, client: FlaskClient) -> None:
        view = _save(client).get_json()["view"]
        _save(client, name="Fable")

        response = client.patch(f"{VIEWS}/{view['id']}", json={"name": "Fable"})

        assert response.status_code == 409
        assert _error(response) == 'A saved view with the name "Fable" already exists'


class TestRemoveView:
    def test_a_saved_view_is_removed(self, client: FlaskClient) -> None:
        view = _save(client).get_json()["view"]

        assert client.delete(f"{VIEWS}/{view['id']}").status_code == 204
        assert view["id"] not in [one["id"] for one in _stored(client)["saved_views"]]

    def test_no_view_is_not_found(self, client: FlaskClient) -> None:
        assert client.delete(f"{VIEWS}/{uuid.uuid4()}").status_code == 404

    def test_a_system_view_is_refused(
        self, client: FlaskClient, session: DbSession
    ) -> None:
        assert client.delete(f"{VIEWS}/{_system(session).id}").status_code == 409


class TestStars:
    def test_a_person_stars_a_system_view_and_a_saved_one(
        self, client: FlaskClient, session: DbSession, person: User
    ) -> None:
        _sign_in(client)
        saved = _save(client).get_json()["view"]
        shipped = str(_system(session).id)

        assert client.put(f"{VIEWS}/{shipped}/star").status_code == 204
        assert client.put(f"{VIEWS}/{saved['id']}/star").status_code == 204
        assert client.put(f"{VIEWS}/{shipped}/star").status_code == 204

        assert client.get(FAVOURITES).get_json()["views"] == [shipped, saved["id"]]

    def test_a_star_taken_off(
        self, client: FlaskClient, session: DbSession, person: User
    ) -> None:
        _sign_in(client)
        shipped = _system(session).id
        client.put(f"{VIEWS}/{shipped}/star")

        assert client.delete(f"{VIEWS}/{shipped}/star").status_code == 204
        assert client.get(FAVOURITES).get_json()["views"] == []

    @pytest.mark.parametrize("method", ["put", "delete"])
    def test_no_view_is_not_found(
        self, client: FlaskClient, person: User, method: str
    ) -> None:
        _sign_in(client)

        response = getattr(client, method)(f"{VIEWS}/{uuid.uuid4()}/star")

        assert response.status_code == 404

    @pytest.mark.parametrize("method", ["put", "delete"])
    def test_one_who_has_not_chosen_a_handle_is_refused(
        self, client: FlaskClient, session: DbSession, method: str
    ) -> None:
        _sign_in(client, subject="subject-new")

        response = getattr(client, method)(f"{VIEWS}/{_system(session).id}/star")

        assert response.status_code == 409


class TestFavourites:
    def test_a_person_reads_their_own(
        self, client: FlaskClient, session: DbSession, person: User
    ) -> None:
        _sign_in(client)
        for menu, dimension in (("by", "project"), ("color", "token_kind")):
            response = client.post(
                DIMENSIONS, json={"menu": menu, "dimension": dimension}
            )
            assert response.status_code == 204

        assert client.get(FAVOURITES).get_json() == {
            "views": [],
            "by": ["project"],
            "color": ["token_kind"],
        }

        session.add(
            User(
                kind_code=UserKind.PERSON,
                subject="subject-bea",
                handle="bea",
                name="Bea Example",
                avatar_slot=2,
            )
        )
        session.flush()
        _sign_in(client, subject="subject-bea")
        assert client.get(FAVOURITES).get_json() == {
            "views": [],
            "by": [],
            "color": [],
        }

    def test_a_favourite_taken_off(self, client: FlaskClient, person: User) -> None:
        _sign_in(client)
        client.post(DIMENSIONS, json={"menu": "by", "dimension": "project"})

        response = client.delete(
            DIMENSIONS, query_string={"menu": "by", "dimension": "project"}
        )

        assert response.status_code == 204
        assert client.get(FAVOURITES).get_json()["by"] == []

    def test_a_dimension_the_list_does_not_offer_is_refused(
        self, client: FlaskClient, person: User
    ) -> None:
        _sign_in(client)

        response = client.post(DIMENSIONS, json={"menu": "color", "dimension": "day"})

        assert response.status_code == 400
        assert _error(response) == (
            'Cannot mark "day" a favourite in Color\'s list because a color is a '
            "part, an attribute or token_kind."
        )

    @pytest.mark.parametrize(
        "body", [{"menu": "shelf", "dimension": "project"}, {"menu": "by"}]
    )
    def test_no_list_or_no_dimension_is_refused(
        self, client: FlaskClient, person: User, body: dict[str, str]
    ) -> None:
        _sign_in(client)

        assert client.post(DIMENSIONS, json=body).status_code == 400
        assert client.delete(DIMENSIONS, query_string=body).status_code == 400

    def test_one_who_has_not_chosen_a_handle_is_refused(
        self, client: FlaskClient
    ) -> None:
        _sign_in(client, subject="subject-new")
        favourite = {"menu": "by", "dimension": "project"}

        assert client.get(FAVOURITES).status_code == 409
        assert client.post(DIMENSIONS, json=favourite).status_code == 409
        assert client.delete(DIMENSIONS, query_string=favourite).status_code == 409


class TestQuickFilters:
    def test_one_is_made_for_everyone(self, client: FlaskClient) -> None:
        response = client.post(
            QUICK_FILTERS,
            json={"label": "Opus only", "chip": "~model:claude-opus-5-5"},
        )

        assert response.status_code == 201
        made = response.get_json()
        assert {
            key: value for key, value in made.items() if key not in ("id", "saved_at")
        } == {
            "key": made["key"],
            "label": "Opus only",
            "condition": "model:claude-opus-5-5",
            "marks": True,
            "amount": None,
            "note": None,
            "offered": True,
        }
        assert _stored(client)["quick_filters"][-1] == made

    def test_a_chip_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            QUICK_FILTERS, json={"label": "Fable", "chip": "modle:x"}
        )

        assert response.status_code == 400
        assert _error(response).startswith(
            "Cannot read the view because its state has 1 fault.\n- c=modle:x:"
        )

    @pytest.mark.parametrize(
        "body",
        [
            {"chip": "miss:1"},
            {"label": "Misses"},
            {"label": "Misses", "chip": "miss:1", "amount": "cots"},
        ],
    )
    def test_no_label_no_chip_or_an_amount_no_figure_has_is_refused(
        self, client: FlaskClient, body: dict[str, str]
    ) -> None:
        assert client.post(QUICK_FILTERS, json=body).status_code == 400

    def test_one_is_removed(self, client: FlaskClient, session: DbSession) -> None:
        shipped = session.scalars(
            select(QuickFilter).where(QuickFilter.code == "misses")
        ).one()

        assert client.delete(f"{QUICK_FILTERS}/{shipped.id}").status_code == 204
        assert "misses" not in [one["key"] for one in _stored(client)["quick_filters"]]

    def test_no_quick_filter_is_not_found(self, client: FlaskClient) -> None:
        assert client.delete(f"{QUICK_FILTERS}/{uuid.uuid4()}").status_code == 404


class TestCustomRatios:
    def test_one_is_made_for_everyone(self, client: FlaskClient) -> None:
        response = client.post(
            RATIOS,
            json={
                "name": "Cost per turn",
                "numerator": "reported_cost.sum",
                "denominator": "turns",
            },
        )

        assert response.status_code == 201
        made = response.get_json()
        assert {
            key: value for key, value in made.items() if key not in ("id", "saved_at")
        } == {
            "system": False,
            "origin": "person",
            "key": "person_cost_per_turn",
            "name": "Cost per turn",
            "numerator": "reported_cost.sum",
            "denominator": "turns.count",
            "note": None,
            "offered": True,
        }
        assert _stored(client)["custom_ratios"] == [made]

    def test_a_side_with_faults_is_refused_with_every_fault(
        self, client: FlaskClient
    ) -> None:
        response = client.post(
            RATIOS,
            json={"name": "Broken", "numerator": "cots.sum", "denominator": "turnz"},
        )

        assert response.status_code == 400
        assert _error(response).startswith(
            "Cannot read the view because its state has 2 faults.\n- m=cots.sum:"
        )

    def test_a_change_with_faults_is_refused_with_its_text(
        self, client: FlaskClient
    ) -> None:
        made = client.post(
            RATIOS,
            json={"name": "Cost per turn", "numerator": "cost", "denominator": "turns"},
        ).get_json()

        response = client.put(
            f"{RATIOS}/{made['id']}",
            json={
                "name": "Cost per turn",
                "numerator": "cots.sum",
                "denominator": "turns",
            },
        )

        assert response.status_code == 400
        assert _error(response).startswith(
            "Cannot read the view because its state has 1 fault.\n- m=cots.sum:"
        )

    def test_a_persons_name_taken_is_refused(self, client: FlaskClient) -> None:
        ratio = {"name": "Cost per turn", "numerator": "cost", "denominator": "turns"}
        client.post(RATIOS, json=ratio)

        assert client.post(RATIOS, json=ratio).status_code == 409

    @pytest.mark.parametrize(
        "body",
        [
            {"numerator": "cost.sum", "denominator": "turns.count"},
            {"name": "Cost per turn", "numerator": "cost.sum"},
        ],
    )
    def test_no_name_or_a_side_missing_is_refused(
        self, client: FlaskClient, body: dict[str, str]
    ) -> None:
        assert client.post(RATIOS, json=body).status_code == 400

    def test_one_is_changed_under_its_key(self, client: FlaskClient) -> None:
        made = client.post(
            RATIOS,
            json={"name": "Cost per turn", "numerator": "cost", "denominator": "turns"},
        ).get_json()

        response = client.put(
            f"{RATIOS}/{made['id']}",
            json={
                "name": "Turn cost",
                "numerator": "reported_cost.sum",
                "denominator": "turns.count",
                "note": "As the turns reported it",
            },
        )

        assert response.status_code == 200
        changed = response.get_json()
        assert (changed["id"], changed["key"], changed["name"], changed["note"]) == (
            made["id"],
            "person_cost_per_turn",
            "Turn cost",
            "As the turns reported it",
        )

    def test_one_is_removed(self, client: FlaskClient) -> None:
        made = client.post(
            RATIOS,
            json={"name": "Cost per turn", "numerator": "cost", "denominator": "turns"},
        ).get_json()

        assert client.delete(f"{RATIOS}/{made['id']}").status_code == 204
        assert _stored(client)["custom_ratios"] == []

    @pytest.mark.parametrize("method", ["put", "delete"])
    def test_a_loaded_one_is_neither_changed_nor_removed(
        self, client: FlaskClient, session: DbSession, method: str
    ) -> None:
        loaded = _loaded_ratio(session)
        change = {"name": "Mine", "numerator": "cost", "denominator": "turns"}

        response = getattr(client, method)(f"{RATIOS}/{loaded.id}", json=change)

        assert response.status_code == 409
        assert _error(response).endswith(
            "because it was loaded with the workflow's views, and nobody changes "
            "or removes a loaded ratio"
        )

    def test_no_ratio_is_not_found(self, client: FlaskClient) -> None:
        change = {"name": "Mine", "numerator": "cost", "denominator": "turns"}

        assert client.put(f"{RATIOS}/{uuid.uuid4()}", json=change).status_code == 404
        assert client.delete(f"{RATIOS}/{uuid.uuid4()}").status_code == 404


def _entries(views: list[dict[str, Any]] | None = None, **ratio: Any) -> Any:
    """The invented file, its views `views` where given, and its first ratio
    with `ratio`'s fields."""
    written = workflow_views.arguments()
    if views is not None:
        written["views"] = views
    written["ratios"][0] |= ratio
    return written


class TestLoadWorkflow:
    def test_the_service_user_loads_the_file_and_every_person_reads_it(
        self, client: FlaskClient, service_user: User, person: User
    ) -> None:
        _sign_in(client, service_user.subject)

        response = client.put(WORKFLOW, json=workflow_views.arguments())

        assert response.status_code == 200
        assert response.get_json() == {
            "views": {"added": 3, "changed": 0, "removed": 0},
            "ratios": {"added": 2, "changed": 0, "removed": 0},
            "notes": [],
        }
        _sign_in(client)
        stored = _stored(client)
        assert [
            (view["key"], view["name"], view["address"])
            for view in stored["saved_views"]
            if view["origin"] == "workflow"
        ] == [
            (
                "errands",
                "Errands",
                "#dash/t=l8&by=project&m=cost.sum&m=r:per_serving&col=model",
            ),
            (
                "legs",
                "Legs",
                "#dash/t=qw&by=conversation&m=cost.median&col=none&roll=5,5",
            ),
            (
                "rides",
                "Rides",
                "#dash/t=d7&by=project&p=time,day&m=cost.sum&m=r:per_ride&col=source",
            ),
        ]
        assert [
            (ratio["key"], ratio["system"], ratio["offered"])
            for ratio in stored["custom_ratios"]
        ] == [("per_ride", True, True), ("per_serving", True, True)]

    def test_a_loaded_ratio_under_a_built_in_key_is_listed_as_not_offered(
        self, client: FlaskClient, session: DbSession, person: User
    ) -> None:
        """A ratio loaded under a key a later release builds in: the
        catalogue offers the built-in one under it."""
        loaded = _loaded_ratio(session)
        loaded.key = "per_call"
        session.flush()
        _sign_in(client)

        stored = _stored(client)

        assert [
            (ratio["key"], ratio["system"], ratio["offered"])
            for ratio in stored["custom_ratios"]
        ] == [("per_call", True, False)]

    def test_a_dropped_part_is_a_note(
        self, client: FlaskClient, service_user: User
    ) -> None:
        _sign_in(client, service_user.subject)
        views = [{"key": "errands", "name": "Errands", "state": "by=model&b=pantry"}]

        response = client.put(WORKFLOW, json=_entries(views))

        assert response.status_code == 200
        assert response.get_json()["notes"] == [
            'view "errands", b=pantry: no quick filter has the key "pantry", so it '
            "is dropped."
        ]

    def test_a_person_is_refused(self, client: FlaskClient, person: User) -> None:
        _sign_in(client)

        response = client.put(WORKFLOW, json=workflow_views.arguments())

        assert response.status_code == 409
        assert _error(response) == (
            "Cannot load the workflow's views and ratios because you do not call "
            "as a service user"
        )

    def test_a_load_with_faults_is_refused_with_its_text_and_writes_nothing(
        self, client: FlaskClient, session: DbSession, service_user: User
    ) -> None:
        _sign_in(client, service_user.subject)

        response = client.put(WORKFLOW, json=_entries(key="person_serving"))

        assert response.status_code == 400
        assert response.get_json()["code"] == "STATE_REFUSED"
        assert _error(response) == (
            "Cannot load the views and ratios because their entries have 1 fault.\n"
            '- ratio "person_serving", key: a key that begins "person_" is a ratio '
            "a person made, and a loaded ratio's key is outside that space."
        )
        assert (
            session.scalars(
                select(SavedView).where(SavedView.origin_code == Origin.WORKFLOW)
            ).all()
            == []
        )

    @pytest.mark.parametrize(
        "entries",
        [
            _entries(key="per-serving"),
            _entries(name="Cost per\nserving"),
            _entries([{"key": "errands", "name": "Errands"}]),
            _entries(
                [
                    {"key": f"view_{number}", "name": f"View {number}", "state": "x"}
                    for number in range(201)
                ]
            ),
        ],
        ids=["a-key-with-a-hyphen", "a-name-of-two-lines", "no-state", "201-views"],
    )
    def test_an_entry_the_schema_takes_no_part_of_is_refused(
        self, client: FlaskClient, service_user: User, entries: Any
    ) -> None:
        _sign_in(client, service_user.subject)

        assert client.put(WORKFLOW, json=entries).status_code == 400


ROUTES = [
    ("post", VIEWS, {"name": "Opus", "state": STATE}),
    ("patch", f"{VIEWS}/{NOWHERE}", {"name": "Opus"}),
    ("delete", f"{VIEWS}/{NOWHERE}", None),
    ("put", f"{VIEWS}/{NOWHERE}/star", None),
    ("delete", f"{VIEWS}/{NOWHERE}/star", None),
    ("get", FAVOURITES, None),
    ("post", DIMENSIONS, {"menu": "by", "dimension": "project"}),
    ("delete", f"{DIMENSIONS}?menu=by&dimension=project", None),
    ("post", QUICK_FILTERS, {"label": "Misses", "chip": "miss:1"}),
    ("delete", f"{QUICK_FILTERS}/{NOWHERE}", None),
    ("post", RATIOS, {"name": "Mine", "numerator": "cost", "denominator": "turns"}),
    (
        "put",
        f"{RATIOS}/{NOWHERE}",
        {"name": "Mine", "numerator": "cost", "denominator": "turns"},
    ),
    ("delete", f"{RATIOS}/{NOWHERE}", None),
    ("put", WORKFLOW, {"views": [], "ratios": []}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_without_editor_each_route_is_refused(
    client: FlaskClient, method: str, path: str, body: dict[str, str] | None
) -> None:
    _sign_in(client, subject="someone", roles=())

    assert getattr(client, method)(path, json=body).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_without_a_token_each_route_is_unauthenticated(
    oidc_client: FlaskClient, method: str, path: str, body: dict[str, str] | None
) -> None:
    assert getattr(oidc_client, method)(path, json=body).status_code == 401
