"""The tally's figures (F122.2): the scenario for exact figures loaded on two
projects, read through the dashboard's rows route as the page reads it and
through its quick filters' counts. They are the figures the screen's specs
assert, so a change to the tally or to the engine that moves one shows
here first."""

from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from pilot_scenario import TALLY
from sqlalchemy.orm import Session as DbSession

from app.models import Project, User
from app.models.reference import UserKind
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer


@pytest.fixture
def ben(session: DbSession) -> User:
    user = User(
        kind_code=UserKind.PERSON,
        subject="subject-ben",
        handle="ben",
        name="Ben Example",
        avatar_slot=2,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def projects(
    container: ServiceContainer, person: User, ben: User
) -> tuple[Project, Project]:
    """The tally loaded: its `recipe-box` the project "Recipes", its
    `bike-log` "Bikes", each made as a spec makes one, its opening #1."""
    made = container.test_data_service()
    recipes = made.project(InventedProjectCreateSchema(name="Recipes", members=["ada"]))
    bikes = made.project(InventedProjectCreateSchema(name="Bikes", members=["ada"]))
    container.scenario_service().load(
        TALLY, {"recipe-box": recipes.id, "bike-log": bikes.id}
    )
    return recipes, bikes


def _chip(projects: tuple[Project, Project]) -> str:
    return "c=project:" + ",".join(str(project.id) for project in projects)


def _rows(client: FlaskClient, state: str) -> dict[str, Any]:
    response = client.get("/api/dashboard/rows", query_string={"state": state})
    assert response.status_code == 200, response.get_json()
    answer: dict[str, Any] = response.get_json()
    return answer


def _table(answer: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [(row["label"], *row["values"]) for row in answer["rows"]]


class TestTheTallysFigures:
    def test_by_project_its_cost_its_calls_and_its_turns(
        self, client: FlaskClient, projects: tuple[Project, Project]
    ) -> None:
        answer = _rows(
            client,
            f"t=all&by=project&m=cost.sum&m=calls.count&m=turns.count&{_chip(projects)}",
        )

        assert answer["all"]["values"] == [2.285275, 16, 5]
        assert _table(answer) == [
            ("Bikes", 1.178595, 3, 1),
            ("Recipes", 1.10668, 13, 4),
        ]

    def test_by_pilot_session_a_work_item_a_job_and_a_chat_named(
        self, client: FlaskClient, projects: tuple[Project, Project]
    ) -> None:
        answer = _rows(
            client, f"t=all&by=psession&m=cost.sum&m=calls.count&{_chip(projects)}"
        )

        assert _table(answer) == [
            ("#2 Tidy the ride notes", 1.178595, 3),
            ("#2 Sort the spices", 0.859005, 10),
            ("Project chat", 0.247675, 3),
        ]
        assert all(row["at"] is not None for row in answer["rows"])

    def test_by_pilot_turn_each_named_by_its_number_and_cause(
        self, client: FlaskClient, projects: tuple[Project, Project]
    ) -> None:
        answer = _rows(
            client, f"t=all&by=pturn&m=cost.sum&m=calls.count&{_chip(projects)}"
        )

        assert _table(answer) == [
            ("Turn 1 · brief", 1.178595, 3),
            ("Turn 1 · brief", 0.591465, 8),
            ("Turn 2 · continuation", 0.26754, 2),
            ("Turn 1 · person", 0.211245, 2),
            ("Turn 2 · person", 0.03643, 1),
        ]

    def test_by_conversation_the_main_threads_and_the_sub_agent(
        self, client: FlaskClient, projects: tuple[Project, Project]
    ) -> None:
        answer = _rows(
            client, f"t=all&by=conversation&m=cost.sum&m=calls.count&{_chip(projects)}"
        )

        assert _table(answer) == [
            ("Main thread", 1.178595, 3),
            ("Main thread", 0.846295, 7),
            ("Main thread", 0.247675, 3),
            ("Explore · Find where the jars are counted", 0.01271, 3),
        ]

    def test_by_call_one_costs_more_than_a_dollar_and_a_turns_figure_is_refused(
        self, client: FlaskClient, projects: tuple[Project, Project]
    ) -> None:
        answer = _rows(
            client, f"t=all&by=call&m=cost.sum&m=turns.count&{_chip(projects)}"
        )

        assert [measure["refused"] for measure in answer["measures"]] == [
            None,
            "turns is a figure of Pilot turns, which have no call",
        ]
        assert answer["total_rows"] == 16
        assert answer["rows"][0]["label"] == "Call 1"
        assert answer["rows"][0]["values"] == [1.0535, None]
        assert [row["values"][0] > 1 for row in answer["rows"]].count(True) == 1

    def test_a_ratio_of_two_counts_calls_over_turns(
        self, client: FlaskClient, projects: tuple[Project, Project]
    ) -> None:
        answer = _rows(
            client,
            "t=all&by=project&m=cost.sum&m=r:Calls a turn:calls.count/turns.count&"
            + _chip(projects),
        )

        assert answer["all"]["values"] == [2.285275, 3.2]
        assert _table(answer) == [("Bikes", 1.178595, 3), ("Recipes", 1.10668, 3.25)]

    def test_each_seeded_quick_filter_counts_something(
        self, container: ServiceContainer, projects: tuple[Project, Project]
    ) -> None:
        """By Call, the one expensive Call is the outlier row; by project,
        two rows, none is."""

        def counted(by: str) -> dict[str, tuple[int, float | None]]:
            view = container.address_service().view(
                f"t=all&by={by}&m=cost.sum&{_chip(projects)}"
            )
            return {
                count.key: (count.count, count.amount)
                for count in container.counts_service().quick_filters(
                    view, datetime.now(UTC)
                )
            }

        assert counted("call") == {
            "past_ttl": (1, 0.24425),
            "misses": (2, 0.4935),
            "compactions": (1, None),
            "outliers": (1, None),
            "expensive": (1, 1.0535),
        }
        assert counted("project")["outliers"] == (0, None)
