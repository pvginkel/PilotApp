"""The scenario's load (F122.2, F122.6): the invented scenario in the record,
published through the service a collector's call writes through, its Turn of
Pilot's on the project given for the scenario's, and held once however often
it is loaded."""

import uuid
from datetime import timedelta

import pytest
from pilot_scenario import SCENARIO
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.exceptions import (
    NoServiceUserException,
    RecordNotFoundException,
    ValidationException,
)
from app.models import (
    Call,
    Compaction,
    Document,
    Environment,
    Event,
    Launch,
    Model,
    Project,
    Repository,
    ToolCall,
    Transcript,
    Turn,
    User,
)
from app.models.reference import ProjectState, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.scenario_service import ScenarioService
from tests.support.database import Written, writes

RECIPES = "ben-recipebox-51f0c2"
"""The environment the scenario's Turn of Pilot's ran in."""


@pytest.fixture
def scenario_service(container: ServiceContainer) -> ScenarioService:
    return container.scenario_service()


pytestmark = pytest.mark.usefixtures("service_user")
"""The stage's service user, which the scenario's group has its adopted
Project made by."""


@pytest.fixture
def loaded(scenario_service: ScenarioService, project: Project) -> list[Transcript]:
    """The scenario loaded, its `recipe-box` the project: the thread Pilot
    ran, its sub-agent's and the thread Ada ran by hand."""
    return scenario_service.load({"recipe-box": project.id})


def _calls(db: DbSession, thread: Transcript) -> list[Call]:
    return list(
        db.scalars(
            select(Call).where(Call.transcript_id == thread.id).order_by(Call.position)
        )
    )


class TestLoad:
    def test_it_holds_each_thread_of_the_scenario(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        halving, counting, gears = loaded

        assert [thread.agent_id is None for thread in loaded] == [True, False, True]
        assert counting.session_id == halving.session_id != gears.session_id
        assert [len(_calls(session, thread)) for thread in loaded] == [6, 3, 5]
        assert session.scalar(select(func.count()).select_from(Transcript)) == 3

    def test_each_call_is_priced_at_its_own_models_public_rates(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        used = select(Call.model_code).distinct()

        assert session.scalar(select(func.count()).where(Call.cost.is_(None))) == 0
        assert session.scalar(select(func.min(Call.cost))) > 0
        assert session.execute(
            select(Model.code, Model.priced_as_code)
            .where(Model.code.in_(used))
            .order_by(Model.code)
        ).all() == [("claude-haiku-4-5-20251001", None), ("claude-opus-4-5", None)]

    def test_a_sub_agent_stands_under_its_main_thread_and_its_spawning_call(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        halving, counting, _ = loaded
        spawning = session.scalars(
            select(ToolCall).where(
                ToolCall.transcript_id == halving.id, ToolCall.tool_code == "Agent"
            )
        ).one()

        assert counting.main_id == halving.id
        assert counting.spawned_by_id == spawning.id
        assert counting.description == spawning.first_argument

    def test_the_turn_of_pilots_lands_on_the_project_given(
        self, session: DbSession, loaded: list[Transcript], project: Project
    ) -> None:
        halving = loaded[0]
        run = session.scalars(
            select(models.Session).where(
                models.Session.conversation_id == halving.session_id
            )
        ).one()
        turn = session.scalars(select(Turn).where(Turn.session_id == run.id)).one()
        launch = session.scalars(
            select(Launch).where(Launch.transcript_id == halving.id)
        ).one()

        assert (launch.session_id, launch.turn_seq) == (run.id, 1)
        assert (run.project_id, run.environment_id) == (project.id, RECIPES)
        assert (run.kind_code, run.cwd) == ("work", "/work/RecipeBox")
        assert (turn.seq, turn.author_user_id) == (1, None)
        assert turn.message == SCENARIO.sessions[0].turn.message
        assert turn.started_at <= launch.started_at <= turn.ended_at

    def test_the_session_of_pilots_is_over_since_its_turns_end(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        run = session.scalars(
            select(models.Session).where(
                models.Session.conversation_id == loaded[0].session_id
            )
        ).one()
        turn = session.scalars(select(Turn).where(Turn.session_id == run.id)).one()

        assert run.state_code is SessionState.ENDED
        assert run.turns == 1
        assert (run.started_at, run.turn_started_at) == (
            turn.started_at,
            turn.started_at,
        )
        assert (run.turn_ended_at, run.ended_at) == (turn.ended_at, turn.ended_at)

    def test_the_group_the_scenario_names_adopts_the_session_a_person_ran(
        self, session: DbSession, loaded: list[Transcript], service_user: User
    ) -> None:
        """F152.8: the group's adopted Project, made by the load."""
        halving, counting, gears = loaded

        adopted = session.scalars(
            select(Project).where(Project.adopted_group.is_not(None))
        ).one()
        assert (adopted.state_code, adopted.archived, adopted.adopted_group) == (
            ProjectState.ADOPTED,
            True,
            "bike-log-first-rides",
        )
        assert adopted.name == "Bike log: the first rides"
        assert adopted.created_by_user_id == service_user.id
        assert session.scalars(
            select(Document.published_text).where(Document.project_id == adopted.id)
        ).one() == (
            "---\n"
            "title: 'Bike log: the first rides'\n"
            "---\n"
            "\n"
            "The gear tables and ride notes Ada kept by hand, before Pilot kept the"
            " log.\n"
        )
        assert gears.adopted_project_id == adopted.id
        assert (halving.adopted_project_id, counting.adopted_project_id) == (None, None)

    def test_the_session_a_person_ran_lands_under_where_it_ran(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        gears = loaded[2]
        launch = session.scalars(
            select(Launch).where(Launch.transcript_id == gears.id)
        ).one()

        assert gears.environment_id == "ada-bikelog-3c9e1f"
        assert session.get_one(Repository, gears.repository_id).name == "BikeLog"
        assert (launch.session_id, launch.turn_seq) == (None, None)
        assert (
            session.scalar(
                select(func.count())
                .select_from(models.Session)
                .where(models.Session.conversation_id == gears.session_id)
            )
            == 0
        )

    def test_it_holds_what_happened_in_them(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        halving, _, gears = loaded
        compaction = session.scalars(
            select(Compaction).where(Compaction.transcript_id == halving.id)
        ).one()
        pilots = _calls(session, halving)
        adas = _calls(session, gears)
        error = session.scalars(select(Event)).one()

        assert [call.compaction_id for call in pilots] == [
            None,
            None,
            None,
            None,
            compaction.id,
            None,
        ]
        assert [call.miss_cause_code for call in pilots][4] == "compaction"
        assert [call.miss_cause_code for call in adas] == [
            None,
            None,
            None,
            "rewind",
            "ttl",
        ]
        assert adas[3].predecessor_id == adas[1].id
        assert (error.call_id, error.kind_code, error.detail) == (
            pilots[2].id,
            "api_retry",
            "529",
        )

    def test_its_last_moment_is_now(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        now = session.scalar(select(func.now()))

        assert max(thread.file_modified_at for thread in loaded) == now.replace(
            microsecond=now.microsecond // 1000 * 1000
        )
        assert all(thread.replayed_size == thread.file_size for thread in loaded)

    def test_a_second_load_writes_the_transcripts_rows_alone(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        loaded: list[Transcript],
        project: Project,
    ) -> None:
        with writes(session) as wrote:
            again = scenario_service.load({"recipe-box": project.id})

        assert [thread.id for thread in again] == [thread.id for thread in loaded]
        assert wrote == {"transcripts": Written(updated=3)}

    def test_a_second_load_finds_the_groups_project_by_its_key(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        loaded: list[Transcript],
        project: Project,
    ) -> None:
        adopted = loaded[2].adopted_project_id

        again = scenario_service.load({"recipe-box": project.id})

        assert again[2].adopted_project_id == adopted
        assert session.scalars(
            select(Project.id).where(Project.adopted_group.is_not(None))
        ).all() == [adopted]
        assert scenario_service.adopting(again) == {
            adopted: session.get_one(Project, adopted)
        }

    def test_a_stage_with_no_service_user_refuses_the_load(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        project: Project,
        service_user: User,
    ) -> None:
        service_user.kind_code = UserKind.PERSON
        service_user.avatar_slot = 3
        session.flush()

        with pytest.raises(NoServiceUserException):
            scenario_service.load({"recipe-box": project.id})

        assert session.scalars(select(Project.id)).all() == [project.id]

    def test_a_second_load_replaces_what_the_record_held_of_the_first(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        loaded: list[Transcript],
        project: Project,
    ) -> None:
        halving = loaded[0]
        run = session.scalars(
            select(models.Session).where(
                models.Session.conversation_id == halving.session_id
            )
        ).one()
        turn = session.scalars(select(Turn).where(Turn.session_id == run.id)).one()
        launch = session.scalars(
            select(Launch).where(Launch.transcript_id == halving.id)
        ).one()
        held = (turn.started_at, turn.ended_at, launch.started_at, launch.ended_at)
        earlier = timedelta(days=2)
        turn.started_at -= earlier
        turn.ended_at -= earlier
        run.started_at = run.turn_started_at = turn.started_at
        run.turn_ended_at = run.ended_at = turn.ended_at
        launch.started_at -= earlier
        launch.ended_at -= earlier
        session.delete(_calls(session, halving)[-1])
        session.flush()

        scenario_service.load({"recipe-box": project.id})

        session.expire_all()
        assert (
            turn.started_at,
            turn.ended_at,
            launch.started_at,
            launch.ended_at,
        ) == held
        assert (run.started_at, run.turn_started_at) == (held[0], held[0])
        assert (run.turn_ended_at, run.ended_at) == (held[1], held[1])
        assert (launch.session_id, launch.turn_seq) == (run.id, 1)
        assert [len(_calls(session, thread)) for thread in loaded] == [6, 3, 5]
        assert session.scalar(select(func.count()).select_from(Transcript)) == 3
        assert session.scalar(select(func.count()).select_from(Turn)) == 1

    def test_a_second_load_moves_the_turn_of_pilots_to_the_project_given(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        loaded: list[Transcript],
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()

        scenario_service.load({"recipe-box": other.id})

        run = session.scalars(
            select(models.Session).where(
                models.Session.conversation_id == loaded[0].session_id
            )
        ).one()
        launch = session.scalars(
            select(Launch).where(Launch.transcript_id == loaded[0].id)
        ).one()
        assert run.project_id == other.id
        assert (launch.session_id, launch.turn_seq) == (run.id, 1)

    def test_an_environment_pilot_holds_stands_as_it_is(
        self, session: DbSession, scenario_service: ScenarioService, project: Project
    ) -> None:
        session.add(Environment(id=RECIPES, name="Recipes", exempt=True))
        session.flush()

        scenario_service.load({"recipe-box": project.id})

        held = session.get_one(Environment, RECIPES)
        assert (held.name, held.exempt) == ("Recipes", True)

    def test_an_environment_pilot_never_touched_is_named_by_its_id(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        held = session.get_one(Environment, RECIPES)

        assert (held.name, held.exempt) == (RECIPES, False)

    @pytest.mark.parametrize(
        ("named", "given"),
        [
            pytest.param([], "none", id="none"),
            pytest.param(["bike-log"], "`bike-log`", id="another"),
            pytest.param(
                ["recipe-box", "bike-log"], "`bike-log`, `recipe-box`", id="one more"
            ),
        ],
    )
    def test_projects_other_than_those_a_turn_of_pilots_is_on_are_refused(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        project: Project,
        named: list[str],
        given: str,
    ) -> None:
        with writes(session) as wrote, pytest.raises(ValidationException) as refused:
            scenario_service.load(dict.fromkeys(named, project.id))

        assert refused.value.message == (
            f"Cannot load the scenario because `projects` gives a project for {given},"
            " and the scenario's Turns of Pilot's are on `recipe-box`"
        )
        assert wrote == {}

    def test_a_project_pilot_does_not_hold_is_not_found(
        self, session: DbSession, scenario_service: ScenarioService
    ) -> None:
        missing = uuid.UUID("00000000-0000-4000-8000-000000000000")

        with writes(session) as wrote, pytest.raises(RecordNotFoundException):
            scenario_service.load({"recipe-box": missing})

        assert wrote == {}
