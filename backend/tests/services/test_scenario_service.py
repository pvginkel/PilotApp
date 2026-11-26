"""The scenarios' load (F122.2, F122.6): an invented scenario in the record,
published through the service a collector's call writes through, what Pilot
holds of the sessions it ran on the projects given for the scenario's, and
held once however often it is loaded; and the dev seed's history, written the
same way at its own times."""

import uuid
from datetime import date, timedelta

import pytest
from pilot_scenario import SCENARIO, TALLY
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
    Chat,
    Compaction,
    Document,
    Environment,
    Event,
    Item,
    Launch,
    Model,
    Project,
    Repository,
    ToolCall,
    Transcript,
    Turn,
    User,
    Work,
)
from app.models.reference import (
    ChatKind,
    CloseCause,
    ProjectState,
    SessionState,
    TurnCause,
    UserKind,
    WorkTrigger,
)
from app.services.container import ServiceContainer
from app.services.scenario_service import HISTORY, HISTORY_DAYS, ScenarioService
from tests.support.database import Written, writes
from tests.support.workflow_words import workflow_words

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
    return scenario_service.load(SCENARIO, {"recipe-box": project.id})


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
        assert turn.message == SCENARIO.sessions[0].ran.turns[0].message
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

    def test_its_calls_hold_their_caches(
        self, session: DbSession, loaded: list[Transcript]
    ) -> None:
        """DB §7.4: Ada's fourth Call went back to her second, and her fifth
        waited past the cache's lifetime and missed it; each Call is in the
        Launch it was made in, a sub-agent's in its main thread's. A miss is
        read from the tokens (DB 546): the Call after the compaction and,
        in the scenario, Ada's rewind and the Call after her lapse each
        write what they might have read."""
        halving, counting, gears = loaded
        pilots = _calls(session, halving)
        adas = _calls(session, gears)
        launch = session.scalars(
            select(Launch).where(Launch.transcript_id == halving.id)
        ).one()

        assert [call.rewind for call in adas] == [False, False, False, True, False]
        assert [call.past_ttl for call in adas] == [False, False, False, False, True]
        assert [call.cache_miss for call in adas] == [False, False, False, True, True]
        assert [call.cache_miss for call in pilots] == [False] * 4 + [True, False]
        assert adas[0].waited_seconds is None
        assert (
            adas[4].waited_seconds
            == (adas[4].sent_at - adas[3].completed_at).total_seconds()
        )
        assert {call.launch_id for call in pilots} == {launch.id}
        assert {call.launch_id for call in _calls(session, counting)} == {launch.id}
        assert (halving.first_call_at, halving.last_call_at) == (
            pilots[0].completed_at,
            pilots[-1].completed_at,
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
            again = scenario_service.load(SCENARIO, {"recipe-box": project.id})

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

        again = scenario_service.load(SCENARIO, {"recipe-box": project.id})

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
            scenario_service.load(SCENARIO, {"recipe-box": project.id})

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

        scenario_service.load(SCENARIO, {"recipe-box": project.id})

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

    def test_a_load_on_another_project_is_a_scenario_of_its_own(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        loaded: list[Transcript],
        project: Project,
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()

        again = scenario_service.load(SCENARIO, {"recipe-box": other.id})

        runs = {
            run.conversation_id: run.project_id
            for run in session.scalars(select(models.Session))
        }
        launch = session.scalars(
            select(Launch).where(Launch.transcript_id == again[0].id)
        ).one()
        assert runs == {
            loaded[0].session_id: project.id,
            again[0].session_id: other.id,
        }
        assert session.scalar(select(func.count()).select_from(Transcript)) == 6
        assert launch.session_id is not None and launch.turn_seq == 1

    def test_an_environment_pilot_holds_stands_as_it_is(
        self, session: DbSession, scenario_service: ScenarioService, project: Project
    ) -> None:
        session.add(Environment(id=RECIPES, name="Recipes", exempt=True))
        session.flush()

        scenario_service.load(SCENARIO, {"recipe-box": project.id})

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
    def test_projects_other_than_those_pilot_ran_a_session_on_are_refused(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        project: Project,
        named: list[str],
        given: str,
    ) -> None:
        with writes(session) as wrote, pytest.raises(ValidationException) as refused:
            scenario_service.load(SCENARIO, dict.fromkeys(named, project.id))

        assert refused.value.message == (
            f"Cannot load the scenario because `projects` gives a project for {given},"
            " and the scenario's Sessions of Pilot's are on `recipe-box`"
        )
        assert wrote == {}

    def test_a_project_pilot_does_not_hold_is_not_found(
        self, session: DbSession, scenario_service: ScenarioService
    ) -> None:
        missing = uuid.UUID("00000000-0000-4000-8000-000000000000")

        with writes(session) as wrote, pytest.raises(RecordNotFoundException):
            scenario_service.load(SCENARIO, {"recipe-box": missing})

        assert wrote == {}


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
def bikes(session: DbSession, person: User) -> Project:
    project = Project(
        slug="bikes", state_code=ProjectState.OPEN, created_by_user_id=person.id
    )
    session.add(project)
    session.flush()
    return project


def _run(db: DbSession, conversation: str) -> models.Session:
    return db.scalars(
        select(models.Session).where(models.Session.conversation_id == conversation)
    ).one()


def _turns(db: DbSession, run: models.Session) -> list[Turn]:
    return list(
        db.scalars(select(Turn).where(Turn.session_id == run.id).order_by(Turn.seq))
    )


class TestLoadTheTally:
    @pytest.fixture
    def tallied(
        self,
        scenario_service: ScenarioService,
        project: Project,
        bikes: Project,
        ben: User,
    ) -> list[Transcript]:
        return scenario_service.load(
            TALLY, {"recipe-box": project.id, "bike-log": bikes.id}
        )

    def test_a_work_items_run_is_a_work_with_its_item_done_at_its_end(
        self, session: DbSession, tallied: list[Transcript], project: Project
    ) -> None:
        run = _run(session, tallied[0].session_id)
        item = session.get_one(Item, run.id)
        work = session.get_one(Work, run.id)
        turns = _turns(session, run)

        assert (run.kind_code, run.project_id, run.turns) == ("work", project.id, 2)
        assert (item.kind_code, item.seq, item.title) == ("work", 1, "Sort the spices")
        assert (work.session_kind_code, work.trigger_code) == ("work", None)
        assert item.created_at == run.started_at == turns[0].started_at
        assert item.done_at == run.ended_at == turns[-1].ended_at
        assert item.done_cause_code == "turn_ended"

    def test_each_turn_has_its_cause_and_places_the_launch_it_started(
        self, session: DbSession, tallied: list[Transcript]
    ) -> None:
        spices, _, chat, job = tallied

        for thread, causes in (
            (spices, [TurnCause.BRIEF, TurnCause.CONTINUATION]),
            (chat, [TurnCause.PERSON, TurnCause.PERSON]),
            (job, [TurnCause.BRIEF]),
        ):
            turns = _turns(session, _run(session, thread.session_id))
            launches = session.scalars(
                select(Launch)
                .where(Launch.transcript_id == thread.id)
                .order_by(Launch.started_at)
            ).all()
            assert [turn.cause_code for turn in turns] == causes
            assert [launch.turn_seq for launch in launches] == [
                turn.seq for turn in turns
            ]
            for turn, launch in zip(turns, launches, strict=True):
                assert turn.started_at <= launch.started_at <= turn.ended_at

    def test_a_chats_turns_are_its_peoples_and_it_closed_at_its_end(
        self,
        session: DbSession,
        tallied: list[Transcript],
        project: Project,
        person: User,
        ben: User,
    ) -> None:
        run = _run(session, tallied[2].session_id)
        chat = session.get_one(Chat, run.id)
        turns = _turns(session, run)

        assert (run.kind_code, run.project_id) == ("chat", project.id)
        assert (chat.kind_code, chat.close_cause_code) == (
            ChatKind.PROJECT,
            CloseCause.FINISHED,
        )
        assert chat.closed_at == run.ended_at
        assert [(turn.author_user_id, turn.words) for turn in turns] == [
            (person.id, "Which spices run out first?"),
            (ben.id, "And which do we buy most?"),
        ]
        assert session.get(Item, run.id) is None

    def test_a_job_is_a_work_with_its_trigger_on_the_other_project(
        self, session: DbSession, tallied: list[Transcript], bikes: Project
    ) -> None:
        run = _run(session, tallied[3].session_id)
        work = session.get_one(Work, run.id)

        assert (run.kind_code, run.project_id) == ("job", bikes.id)
        assert work.trigger_code is WorkTrigger.ITEM_DONE
        assert session.get_one(Item, run.id).title == "Tidy the ride notes"

    def test_a_second_load_holds_it_once_at_its_new_times(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        tallied: list[Transcript],
        project: Project,
        bikes: Project,
    ) -> None:
        run = _run(session, tallied[0].session_id)
        earlier = timedelta(hours=1)
        item = session.get_one(Item, run.id)
        item.created_at -= earlier
        item.done_at -= earlier
        session.flush()

        scenario_service.load(TALLY, {"recipe-box": project.id, "bike-log": bikes.id})

        assert session.scalar(select(func.count()).select_from(Item)) == 2
        assert session.scalar(select(func.count()).select_from(Turn)) == 5
        assert (item.created_at, item.done_at) == (run.started_at, run.ended_at)

    def test_a_load_on_other_projects_leaves_the_first_where_it_is(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        tallied: list[Transcript],
        project: Project,
        bikes: Project,
        person: User,
    ) -> None:
        others = [Project(created_by_user_id=person.id) for _ in range(2)]
        session.add_all(others)
        session.flush()

        scenario_service.load(
            TALLY, {"recipe-box": others[0].id, "bike-log": others[1].id}
        )

        assert sorted(
            (item.project_id, item.title)
            for item in session.scalars(select(Item).where(Item.kind_code == "work"))
        ) == sorted(
            [
                (project.id, "Sort the spices"),
                (bikes.id, "Tidy the ride notes"),
                (others[0].id, "Sort the spices"),
                (others[1].id, "Tidy the ride notes"),
            ]
        )

    def test_a_turn_by_a_person_the_record_has_not_is_not_found(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        project: Project,
        bikes: Project,
    ) -> None:
        with pytest.raises(RecordNotFoundException) as missing:
            scenario_service.load(
                TALLY, {"recipe-box": project.id, "bike-log": bikes.id}
            )

        assert missing.value.message == "Person ben was not found"


class TestHistory:
    def test_its_places_and_a_day_have_no_word_of_the_workflow(self) -> None:
        assert workflow_words(HISTORY) == set()
        assert workflow_words(HISTORY.draw(date(2026, 11, 17), 600).scenario) == set()

    def test_it_writes_its_days_up_to_now_on_its_places_projects(
        self,
        session: DbSession,
        scenario_service: ScenarioService,
        person: User,
        ben: User,
    ) -> None:
        places = {}
        for place in HISTORY.places:
            project = Project(
                slug=place.slug,
                state_code=ProjectState.OPEN,
                created_by_user_id=person.id,
            )
            session.add(project)
            session.flush()
            places[place.slug] = project.id
        now = session.scalar(select(func.now()))

        calls = scenario_service.history(places)

        assert session.scalar(select(func.count()).select_from(Call)) == calls > 0
        first, last = session.execute(
            select(func.min(Call.completed_at), func.max(Call.completed_at))
        ).one()
        assert last < now
        assert now - first > timedelta(days=HISTORY_DAYS - 2)
        assert set(
            session.scalars(
                select(models.Session.project_id).where(
                    models.Session.conversation_id.is_not(None)
                )
            )
        ) == set(places.values())
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transcript)
                .where(Transcript.adopted_project_id.is_not(None))
            )
            == 0
        )
