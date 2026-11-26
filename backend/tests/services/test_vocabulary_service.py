"""The labeller's vocabularies, as a collector declares them: Pilot holds
every list as the labeller declares it, and writes only the rows that differ
(F152.6; DB decisions 79.12 and 79.40, assertion 585).

A value the labeller no longer declares stays while a row names it, with no
place in its list, and goes once none does (`TestNoLongerDeclared`). The
collector's values of Event Kind and Context Part Kind stand beside the
labeller's (`TestBesideTheCollectors`). A call that contradicts itself is
refused whole (`TestFaults`)."""

import logging
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.exceptions import VocabulariesInvalidException
from app.models import (
    AskCategory,
    AvoidableKind,
    BuildResult,
    Call,
    CallClass,
    CommandClass,
    ContextPart,
    ContextPartKind,
    Event,
    EventKind,
    File,
    FileClass,
    Model,
    Repository,
    ReworkKind,
    Rule,
    SegmentKind,
    ToolEffectKind,
    UnitMeasure,
    UnitOutcome,
    WaitCause,
    WorkUnit,
    WorkUnitKind,
    WorkUnitKindNesting,
)
from app.services.container import ServiceContainer
from app.services.vocabulary_service import LISTS, VocabularyService
from app.utils.after_commit import run_after_commit_callbacks
from tests.support import transcripts
from tests.support.database import Written, writes
from tests.support.transcripts import OPUS, STARTED
from tests.support.vocabularies import (
    NESTING,
    VERSION,
    listed,
    lists,
    nesting,
    value,
    vocabularies,
)

LOGGER = "app.services.vocabulary_service"


@pytest.fixture
def service(container: ServiceContainer) -> VocabularyService:
    return container.vocabulary_service()


@pytest.fixture
def request_(session: DbSession) -> Call:
    """A main thread's first Call."""
    transcripts.reference(session, Model, OPUS)
    thread = transcripts.transcript(session, transcripts.component_version(session))
    return transcripts.call(session, thread, 1)


def _held(session: DbSession, entity: type[Any]) -> list[dict[str, Any]]:
    """The entity's rows, each column by its name, by code."""
    columns = entity.__table__.columns
    return [
        dict(row)
        for row in session.execute(select(*columns).order_by(entity.code)).mappings()
    ]


def _places(session: DbSession, entity: type[Any]) -> list[tuple[str, int | None]]:
    return [
        (code, position)
        for code, position in session.execute(
            select(entity.code, entity.position).order_by(entity.code)
        )
    ]


def _nestings(session: DbSession) -> list[tuple[str, str]]:
    return [
        (inner, outer)
        for inner, outer in session.execute(
            select(
                WorkUnitKindNesting.inner_code, WorkUnitKindNesting.outer_code
            ).order_by(WorkUnitKindNesting.inner_code)
        )
    ]


def _commit(session: DbSession) -> None:
    """Check the deferred constraints as the request's commit does."""
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


class TestLists:
    def test_it_names_the_entity_of_every_list_the_call_names(self) -> None:
        assert LISTS == {
            "work_unit_kind": WorkUnitKind,
            "unit_outcome": UnitOutcome,
            "rework_kind": ReworkKind,
            "unit_measure": UnitMeasure,
            "segment_kind": SegmentKind,
            "wait_cause": WaitCause,
            "call_class": CallClass,
            "avoidable_kind": AvoidableKind,
            "command_class": CommandClass,
            "build_result": BuildResult,
            "file_class": FileClass,
            "tool_effect_kind": ToolEffectKind,
            "rule": Rule,
            "ask_category": AskCategory,
            "event_kind": EventKind,
            "context_part_kind": ContextPartKind,
        }


class TestDeclare:
    def test_every_list_and_every_nesting_is_held_as_declared(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())
        _commit(session)

        for name, entity in LISTS.items():
            assert _held(session, entity) == sorted(
                lists()[name], key=lambda declared: declared["code"]
            ), name
        assert _nestings(session) == sorted(NESTING)

    def test_a_declaration_pilot_holds_already_writes_nothing(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())

        with writes(session) as wrote:
            service.declare(vocabularies())

        assert wrote == {}

    def test_a_value_held_otherwise_is_the_one_row_written(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())
        changed = value("recipe", 1, counted=False, name="Recipes")

        with writes(session) as wrote:
            service.declare(
                vocabularies(
                    lists=lists(
                        file_class=[changed, value("shopping_list", 2, counted=False)]
                    )
                )
            )

        assert wrote == {"file_classes": Written(updated=1)}
        assert _held(session, FileClass)[0] == changed

    @pytest.mark.parametrize("fact", ["name", "description"])
    def test_a_values_words_are_the_labellers_latest(
        self, session: DbSession, service: VocabularyService, fact: str
    ) -> None:
        service.declare(vocabularies())

        service.declare(
            vocabularies(
                lists=lists(rework_kind=[value("recooked", 1, **{fact: "Again"})])
            )
        )

        [held] = _held(session, ReworkKind)
        assert held[fact] == "Again"

    def test_a_value_new_to_a_list_is_added_at_its_place(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())

        service.declare(
            vocabularies(lists=lists(wait_cause=listed("oven", "proving", "delivery")))
        )
        _commit(session)

        assert _places(session, WaitCause) == [
            ("delivery", 3),
            ("oven", 1),
            ("proving", 2),
        ]

    def test_a_list_reordered_moves_its_values_in_one_transaction(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())

        service.declare(
            vocabularies(lists=lists(segment_kind=listed("plate", "cook", "prep")))
        )
        _commit(session)

        assert _places(session, SegmentKind) == [
            ("cook", 2),
            ("plate", 1),
            ("prep", 3),
        ]

    def test_a_nesting_new_to_the_call_is_added(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())

        with writes(session) as wrote:
            service.declare(vocabularies(nesting=nesting(*NESTING, ("dish", "menu"))))

        assert wrote == {"work_unit_kind_nestings": Written(inserted=1)}
        assert _nestings(session) == [
            ("course", "menu"),
            ("dish", "course"),
            ("dish", "menu"),
        ]

    def test_the_labellers_version_and_what_was_written_are_logged(
        self,
        session: DbSession,
        service: VocabularyService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger=LOGGER):
            service.declare(vocabularies())

        [record] = [one for one in caplog.records if one.name == LOGGER]
        assert record.getMessage() == (
            f"Took the vocabularies of the labeller {VERSION}: 26 values written,"
            " 2 nestings written or removed, 0 values removed and 0 kept with no"
            " place, no longer declared"
        )


class TestTheCatalogue:
    def test_a_declaration_that_writes_drops_it_once_it_has_committed(
        self,
        session: DbSession,
        container: ServiceContainer,
        service: VocabularyService,
    ) -> None:
        catalogue = container.catalogue_service()
        before = catalogue.catalogue(session)

        service.declare(vocabularies())

        # Not before its transaction commits: a reader would assemble it
        # from a record that has not the rows yet.
        assert catalogue.catalogue(session) is before
        run_after_commit_callbacks()
        assert catalogue.catalogue(session) is not before

    def test_one_that_writes_nothing_leaves_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        service: VocabularyService,
    ) -> None:
        service.declare(vocabularies())
        run_after_commit_callbacks()
        catalogue = container.catalogue_service()
        held = catalogue.catalogue(session)

        service.declare(vocabularies())
        run_after_commit_callbacks()

        assert catalogue.catalogue(session) is held

    def test_one_that_only_removes_drops_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        service: VocabularyService,
    ) -> None:
        service.declare(vocabularies())
        run_after_commit_callbacks()
        catalogue = container.catalogue_service()
        held = catalogue.catalogue(session)

        service.declare(vocabularies(lists=lists(avoidable_kind=[])))
        run_after_commit_callbacks()

        assert catalogue.catalogue(session) is not held


class TestNoLongerDeclared:
    def test_a_value_no_row_names_is_removed(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())

        with writes(session) as wrote:
            service.declare(vocabularies(lists=lists(unit_outcome=listed("served"))))

        assert wrote == {"unit_outcomes": Written(deleted=1)}
        assert _places(session, UnitOutcome) == [("served", 1)]

    def test_a_value_a_row_names_stays_with_no_place(
        self, session: DbSession, service: VocabularyService, request_: Call
    ) -> None:
        service.declare(vocabularies())
        session.add(Event(call_id=request_.id, kind_code="burnt", at=STARTED))
        session.flush()

        service.declare(
            vocabularies(lists=lists(event_kind=[value("smoked", 1, is_error=True)]))
        )
        _commit(session)

        burnt = session.get(EventKind, "burnt")
        assert burnt is not None
        assert (burnt.description, burnt.position) == (
            "The burnt of the kitchen's work.",
            None,
        )
        assert _places(session, EventKind) == [("burnt", None), ("smoked", 1)]

    def test_it_goes_once_no_row_names_it(
        self, session: DbSession, service: VocabularyService, request_: Call
    ) -> None:
        service.declare(vocabularies())
        session.add(
            ContextPart(call_id=request_.id, kind_code="recipe_card", characters=80)
        )
        session.flush()
        service.declare(vocabularies(lists=lists(context_part_kind=[])))
        assert _places(session, ContextPartKind) == [("recipe_card", None)]
        session.execute(ContextPart.__table__.delete())

        service.declare(vocabularies(lists=lists(context_part_kind=[])))

        assert _places(session, ContextPartKind) == []

    def test_one_declared_again_takes_its_place_back(
        self, session: DbSession, service: VocabularyService, request_: Call
    ) -> None:
        service.declare(vocabularies())
        session.add(Event(call_id=request_.id, kind_code="burnt", at=STARTED))
        session.flush()
        service.declare(vocabularies(lists=lists(event_kind=[])))

        service.declare(vocabularies())
        _commit(session)

        assert _places(session, EventKind) == [("burnt", 1)]

    def test_a_nesting_no_longer_declared_is_removed_and_its_kind_with_it(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())

        service.declare(
            vocabularies(
                lists=lists(work_unit_kind=listed("menu", "course")),
                nesting=nesting(("course", "menu")),
            )
        )

        assert _nestings(session) == [("course", "menu")]
        assert _places(session, WorkUnitKind) == [("course", 2), ("menu", 1)]

    def test_a_value_a_label_names_stays_with_no_place(
        self, session: DbSession, service: VocabularyService, request_: Call
    ) -> None:
        service.declare(vocabularies())
        request_.wait_cause_code = "oven"
        session.flush()

        service.declare(vocabularies(lists=lists(wait_cause=listed("delivery"))))

        assert _places(session, WaitCause) == [("delivery", 1), ("oven", None)]

    def test_a_file_class_a_file_has_stays_with_no_place(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())
        kept = Repository(name="RecipeBox")
        session.add(kept)
        session.flush()
        session.add(
            File(repository_id=kept.id, path="recipes/stew.md", class_code="recipe")
        )
        session.flush()

        service.declare(
            vocabularies(lists=lists(file_class=[value("menu", 1, counted=True)]))
        )

        assert _places(session, FileClass) == [("menu", 1), ("recipe", None)]

    def test_a_nesting_a_unit_sits_in_stays_and_its_kinds_with_it(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(vocabularies())
        menu = WorkUnit(key="RecipeBox/autumn_menu", kind_code="menu", title="Autumn")
        session.add(menu)
        session.flush()
        session.add(
            WorkUnit(
                key="RecipeBox/autumn_menu|starter",
                kind_code="course",
                title="Starter",
                part_of_id=menu.id,
                part_of_kind_code="menu",
            )
        )
        session.flush()

        service.declare(
            vocabularies(lists=lists(work_unit_kind=listed("dish")), nesting=[])
        )

        assert _nestings(session) == [("course", "menu")]
        assert _places(session, WorkUnitKind) == [
            ("course", None),
            ("dish", 1),
            ("menu", None),
        ]


class TestBesideTheCollectors:
    def test_the_collectors_values_stand_as_they_are(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        transcripts.reference(session, EventKind, "api_error", is_error=True)
        transcripts.reference(session, ContextPartKind, "system_prompt")
        before = (_held(session, EventKind), _held(session, ContextPartKind))

        service.declare(vocabularies(lists=lists(event_kind=[], context_part_kind=[])))

        assert (_held(session, EventKind), _held(session, ContextPartKind)) == before

    def test_the_labellers_stand_beside_them(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        transcripts.reference(session, EventKind, "api_error", is_error=True)
        transcripts.reference(session, ContextPartKind, "system_prompt")

        service.declare(vocabularies())
        _commit(session)

        assert _held(session, EventKind) == [
            {
                "code": "api_error",
                "name": "api_error",
                "is_error": True,
                "description": None,
                "position": None,
            },
            value("burnt", 1, is_error=False),
        ]
        assert _places(session, ContextPartKind) == [
            ("recipe_card", 1),
            ("system_prompt", None),
        ]

    def test_a_code_the_collector_met_takes_the_labellers_words(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        transcripts.reference(session, EventKind, "burnt", is_error=True)

        service.declare(vocabularies())

        assert _held(session, EventKind) == [value("burnt", 1, is_error=False)]


class TestFaults:
    def _refused(
        self, session: DbSession, service: VocabularyService, **overrides: Any
    ) -> list[str]:
        with (
            writes(session) as wrote,
            pytest.raises(VocabulariesInvalidException) as refused,
        ):
            service.declare(vocabularies(**overrides))
        assert wrote == {}
        assert str(refused.value.message).startswith(
            f"Cannot take the vocabularies of the labeller {VERSION} because "
        )
        return refused.value.faults

    def test_a_code_declared_twice_in_a_list(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        twice = [value("timer", 1), value("timer", 2)]

        assert self._refused(session, service, lists=lists(command_class=twice)) == [
            "`command_class`: the code `timer` is declared 2 times"
        ]

    def test_a_place_given_twice_in_a_list(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        twice = [value("timer", 1), value("scales", 1)]

        assert self._refused(session, service, lists=lists(command_class=twice)) == [
            "`command_class`: the position 1 is given 2 times"
        ]

    def test_one_code_in_two_lists_is_two_values(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        service.declare(
            vocabularies(
                lists=lists(
                    rework_kind=listed("other"), tool_effect_kind=listed("other")
                )
            )
        )

        assert _places(session, ReworkKind) == [("other", 1)]
        assert _places(session, ToolEffectKind) == [("other", 1)]

    def test_an_event_kind_another_entity_records(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        """DB 560: those occurrences are no Event's."""
        kinds = [value("burnt", 1, is_error=False), value("refusal", 2, is_error=True)]

        assert self._refused(session, service, lists=lists(event_kind=kinds)) == [
            "`event_kind`: `refusal` is a kind another entity records, and no Event's"
        ]

    def test_a_nesting_given_twice(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        assert self._refused(
            session, service, nesting=nesting(*NESTING, ("course", "menu"))
        ) == ["the nesting of `course` in `menu` is given 2 times"]

    def test_a_nesting_of_a_kind_the_call_does_not_declare(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        assert self._refused(
            session,
            service,
            nesting=nesting(("pudding", "menu"), ("dish", "banquet"), ("tart", "tart")),
        ) == [
            "the nesting of `pudding` in `menu`: `pudding` is no Work Unit Kind"
            " the call declares",
            "the nesting of `dish` in `banquet`: `banquet` is no Work Unit Kind"
            " the call declares",
            "the nesting of `tart` in `tart`: `tart` is no Work Unit Kind the"
            " call declares",
        ]

    def test_every_fault_is_named_at_once(
        self, session: DbSession, service: VocabularyService
    ) -> None:
        faults = self._refused(
            session,
            service,
            lists=lists(
                segment_kind=[value("prep", 1), value("prep", 1)],
                event_kind=[value("denied", 1, is_error=True)],
            ),
            nesting=nesting(("pudding", "menu")),
        )

        assert faults == [
            "`segment_kind`: the code `prep` is declared 2 times",
            "`segment_kind`: the position 1 is given 2 times",
            "`event_kind`: `denied` is a kind another entity records, and no Event's",
            "the nesting of `pudding` in `menu`: `pudding` is no Work Unit Kind"
            " the call declares",
        ]
