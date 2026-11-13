"""The name of the environment a call to the projects surface came from
(F150.1): Pilot's own row's, else the controller's report's, else its id, and
no call refused for it (V09, V20)."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import Environment
from app.services.caller_environment_service import CallerEnvironmentService
from app.services.container import ServiceContainer
from app.services.controller_client import ControllerClient
from app.services.controller_outage import ControllerOutage
from tests.support.fake_controller import ServedFakeController

CALLER = "example-recipebox-1a2b3c"


@pytest.fixture
def names(
    session: DbSession,
    container: ServiceContainer,
    controller_outage: ControllerOutage,
    controller_client: ControllerClient,
) -> CallerEnvironmentService:
    """The service with a controller configured, the fake one, on an outage
    of the test's own."""
    return CallerEnvironmentService(
        db=session,
        controller_client=container.controller_client,
        controller_configured=True,
    )


def _rows(session: DbSession) -> list[str]:
    return list(session.scalars(select(Environment.id)))


class TestName:
    def test_pilots_own_row_names_it_and_the_controller_is_not_asked(
        self,
        session: DbSession,
        names: CallerEnvironmentService,
        fake_controller: ServedFakeController,
    ) -> None:
        session.add(Environment(id=CALLER, name="RecipeBox-2", exempt=False))
        session.flush()
        fake_controller.add_environment(CALLER, name="Renamed since")

        assert names.name(CALLER) == "RecipeBox-2"

    def test_without_a_row_the_controllers_report_names_it_and_no_row_is_written(
        self,
        session: DbSession,
        names: CallerEnvironmentService,
        fake_controller: ServedFakeController,
    ) -> None:
        fake_controller.add_environment(CALLER, name="RecipeBox-2")

        assert names.name(CALLER) == "RecipeBox-2"
        assert _rows(session) == []

    def test_an_environment_the_controller_reports_without_a_name_is_named_by_its_id(
        self, names: CallerEnvironmentService, fake_controller: ServedFakeController
    ) -> None:
        fake_controller.add_environment(CALLER)

        assert names.name(CALLER) == CALLER

    def test_an_environment_neither_knows_is_named_by_its_id(
        self, session: DbSession, names: CallerEnvironmentService
    ) -> None:
        assert names.name(CALLER) == CALLER
        assert _rows(session) == []

    def test_a_controller_that_does_not_answer_leaves_it_named_by_its_id(
        self, names: CallerEnvironmentService, fake_controller: ServedFakeController
    ) -> None:
        fake_controller.add_environment(CALLER, name="RecipeBox-2")
        fake_controller.outage()

        assert names.name(CALLER) == CALLER

    def test_with_no_controller_configured_none_is_asked(
        self, session: DbSession
    ) -> None:
        def no_client() -> ControllerClient:
            raise AssertionError("no controller is configured")

        names = CallerEnvironmentService(
            db=session, controller_client=no_client, controller_configured=False
        )

        assert names.name(CALLER) == CALLER
