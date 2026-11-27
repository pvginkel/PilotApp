"""A publication's labelling, written with its facts in one transaction:
every label of the Transcript replaced together, the Work Units, Test Suites
and CI Builds written by their keys and kept (F152.3, F152.6, F152.7; DB
decision 81, assertion 561).

The rules that protect the most: a publication's facts never remove or
overwrite a label, nor its labels a fact (`TestFactsAndLabels`, slice 047's
I2), and a call with no labelling keeps every label Pilot holds, holding no
stamp (`TestNoLabelling`). A Call's labelled Context Parts are carved out of
its opening prompt's (`TestCarved`, D266). An appended call's labelling
replaces the labels from its boundary on alone, and is taken only where it
continues those Pilot holds (`TestAppended`, F152.15)."""

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from pilot_collection.publication import PublicationSchema
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import aliased

from app.exceptions import (
    PublicationInvalidException,
    PublicationNotAppendableException,
)
from app.models import (
    Call,
    CIBuild,
    CIWait,
    ComponentVersion,
    ContextPart,
    Document,
    Event,
    Launch,
    RuleBreach,
    Segment,
    Test,
    TestFailure,
    TestRun,
    TestSuite,
    ToolCall,
    Transcript,
    WorkUnit,
    WorkUnitMeasure,
)
from app.services.container import ServiceContainer
from app.services.publication_service import PublicationService
from tests.support.database import Written, writes
from tests.support.publications import (
    STAMP,
    appended,
    builds_on,
    call,
    context_part,
    event,
    labelling,
    launch,
    prompt,
    sub_agent,
    tool_call,
    whole,
)
from tests.support.transcripts import STARTED, SUB_AGENT
from tests.support.vocabularies import (
    NESTING,
    VERSION,
    listed,
    lists,
    nesting,
    vocabularies,
)

LOGGER = "app.services.publication_service"

OPENING = (
    "Cook the spring menu's soup, and taste it before it goes out.\n\n"
    "# Orientation digest — the soup\n\n"
    "## The menu\n\nFour dishes, the soup first; the guests come at eight.\n\n"
    "## The pantry (as stocked this morning)\n\nLeeks, stock and cream.\n"
)
"""An invented opening prompt that holds a digest, as a dispatch's does."""

SUITE = "RecipeBox/backend/test"
JOB = "RecipeBox/Build-Main"
DEPLOY = "RecipeBox/Deploy"
MENU, STARTERS, SOUP, AGAIN, BREAD = (
    "spring",
    "spring|starters",
    "spring|starters|soup",
    "spring|starters|soup.2",
    "spring|starters|bread",
)


def _at(minutes: float) -> str:
    return (STARTED + timedelta(minutes=minutes)).isoformat()


def _digest(text: str) -> list[dict[str, Any]]:
    """The digest's sections as the labeller's page reads them: one per
    `## ` heading of the block that opens `# Orientation digest —`, named by
    its heading up to its first ` (`, its characters the section's length
    with its heading."""
    block = text[text.index("# Orientation digest —") :]
    sections = block.split("\n## ")[1:]
    return [
        {
            "name": section.split("\n", 1)[0].split(" (", 1)[0],
            "characters": len(("## " + section).rstrip("\n")),
        }
        for section in sections
    ]


SECTIONS = _digest(OPENING)


def _published(**overrides: Any) -> PublicationSchema:
    """The main thread: two Launches, three Calls. The first Call carries
    the opening prompt, the second places an order and runs a timer, the
    third runs the tests and waits on a build, each Call an Event of the
    collector's but the second."""
    values: dict[str, Any] = {
        "launches": [
            launch(ended_at=_at(2.5), prompts=[prompt(characters=len(OPENING))]),
            launch(started_at=_at(2.6), prompts=[prompt(received_at=_at(2.6))]),
        ],
        "calls": [
            call(
                1,
                prompt=1,
                tool_calls=[tool_call(1)],
                events=[event(at=_at(0.5))],
                context_parts=[
                    context_part(),
                    context_part(kind="prompt", characters=len(OPENING)),
                ],
            ),
            call(
                2,
                prompt=1,
                predecessor="msg_0001",
                tool_calls=[tool_call(2), tool_call(3)],
            ),
            call(
                3,
                prompt=2,
                predecessor="msg_0002",
                tool_calls=[tool_call(4), tool_call(5)],
                events=[event(at=_at(3.5))],
                context_parts=[context_part(kind="prompt", characters=212)],
            ),
        ],
    }
    return whole(**values | overrides)


def _grown(**overrides: Any) -> PublicationSchema:
    """`_published`'s file grown by a fourth Call under its second Launch,
    taken appended from that Call on."""
    values: dict[str, Any] = {
        "call": 4,
        "launch": 2,
        "prompt": 2,
        "launches": [
            launch(started_at=_at(2.6), prompts=[prompt(received_at=_at(2.6))])
        ],
        "calls": [call(4, prompt=2, predecessor="msg_0003")],
    }
    return appended(**values | overrides)


def _regrown(**overrides: Any) -> PublicationSchema:
    """`_published`'s file grown by a fourth Call under its second Launch,
    which runs a timer, taken appended from the third Call on: the one the
    labeller had not settled."""
    third = _published().model_dump(mode="json")["calls"][2]
    values: dict[str, Any] = {
        "call": 3,
        "launch": 2,
        "prompt": 2,
        "launches": [
            launch(started_at=_at(2.6), prompts=[prompt(received_at=_at(2.6))])
        ],
        "calls": [
            third,
            call(4, prompt=2, predecessor="msg_0003", tool_calls=[tool_call(6)]),
        ],
    }
    return appended(**values | overrides)


def _units() -> list[dict[str, Any]]:
    """The spring menu, its starters, and the soup sent back and cooked
    again."""
    return [
        {
            "key": MENU,
            "kind": "menu",
            "title": "The spring menu",
            "started_at": _at(0),
            "measures": [{"measure": "planned_dishes", "amount": 4}],
        },
        {"key": STARTERS, "kind": "course", "part_of": MENU, "title": "Starters"},
        {
            "key": SOUP,
            "kind": "dish",
            "part_of": STARTERS,
            "title": "Soup",
            "role": "cook",
            "round": 1,
            "outcome": "sent_back",
        },
        {
            "key": AGAIN,
            "kind": "dish",
            "part_of": STARTERS,
            "occasioned_by": SOUP,
            "rework_kind": "recooked",
            "title": "Soup again",
            "variant": "thicker",
            "role": "cook",
            "round": 2,
            "outcome": "served",
            "started_at": _at(2.6),
            "ended_at": _at(4),
            "card": "KITCHEN-12",
            "measures": [{"measure": "tastings", "amount": 3}],
        },
    ]


def _labels(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "launches": [{"n": 1, "work_unit": SOUP}, {"n": 2, "work_unit": AGAIN}],
        "calls": [
            {
                "id": "msg_0001",
                "segment": 1,
                "call_class": "chop",
                "wait_cause": "delivery",
            },
            {"id": "msg_0002", "segment": 2, "call_class": "stir"},
            {
                "id": "msg_0003",
                "segment": 2,
                "call_class": "other",
                "avoidable_kind": "spilt",
                "wait_cause": "oven",
            },
        ],
        "segments": [{"position": 1, "kind": "prep"}, {"position": 2, "kind": "cook"}],
        "tool_calls": [
            {
                "tool_use_id": "toolu_0002",
                "command_class": "timer",
                "rules": ["no_tasting_from_the_pot"],
            },
            {
                "tool_use_id": "toolu_0003",
                "effect_kind": "order_placed",
                "effect_subject": "ORDER-12",
            },
            {"tool_use_id": "toolu_0004", "command_class": "timer"},
        ],
        "events": [
            {"call": "msg_0003", "kind": "burnt", "at": _at(3.6), "detail": "the sauce"}
        ],
        "context_parts": [
            {"call": "msg_0001", "kind": "recipe_card", **section}
            for section in SECTIONS
        ],
        "test_runs": [
            {
                "tool_use_id": "toolu_0004",
                "suite": SUITE,
                "passed": False,
                "tests": 12,
                "retries_allowed": 1,
                "started_at": _at(3),
                "ended_at": _at(3.2),
                "failures": [
                    {
                        "test": "tests/test_scale.py::test_halves",
                        "attempts": 2,
                        "flaky": True,
                    },
                    {
                        "test": "tests/test_scale.py::test_doubles",
                        "attempts": 2,
                        "flaky": False,
                    },
                ],
            },
            {"work_unit": STARTERS, "suite": SUITE, "passed": True, "tests": 12},
        ],
        "ci_waits": [
            {"tool_use_id": "toolu_0005", "job": JOB, "number": 812},
            {"tool_use_id": "toolu_0005", "job": DEPLOY, "number": 40},
        ],
    }
    return values | overrides


def _labelling(**overrides: Any) -> dict[str, Any]:
    """The invented labeller's labels of `_published`'s transcript, every
    kind of label given."""
    values: dict[str, Any] = {
        "labels": _labels(),
        "units": _units(),
        "test_suites": [{"code": SUITE, "name": "RecipeBox backend test"}],
        "ci_builds": [
            {
                "job": JOB,
                "number": 812,
                "result": "DONE",
                "queued_at": _at(3.4),
                "started_at": _at(3.5),
                "ended_at": _at(9),
                "commit": "4f1c2a9",
                "deployed_at": _at(11),
            },
            {"job": DEPLOY, "number": 40, "result": "DONE"},
        ],
    }
    return labelling(**values | overrides)


def _appended_labels(**overrides: Any) -> dict[str, Any]:
    """The labeller's labels of `_regrown`'s calls, from the third on: the
    second Launch carries out no unit now, the third Call stirs in the
    second Segment and the fourth plates in a third, its timer breaks a
    rule and the sauce burns under it; the build's wait no longer names the
    deploy, and the starters' run stands."""
    values: dict[str, Any] = {
        "launches": [{"n": 2}],
        "calls": [
            {
                "id": "msg_0003",
                "segment": 2,
                "call_class": "stir",
                "wait_cause": "oven",
            },
            {"id": "msg_0004", "segment": 3, "call_class": "other"},
        ],
        "segments": [
            {"position": 2, "kind": "cook"},
            {"position": 3, "kind": "plate"},
        ],
        "tool_calls": [
            {
                "tool_use_id": "toolu_0006",
                "command_class": "timer",
                "rules": ["no_tasting_from_the_pot"],
            }
        ],
        "events": [{"call": "msg_0004", "kind": "burnt", "at": _at(4.5)}],
        "test_runs": [
            {"work_unit": STARTERS, "suite": SUITE, "passed": True, "tests": 12}
        ],
        "ci_waits": [{"tool_use_id": "toolu_0005", "job": JOB, "number": 812}],
    }
    return values | overrides


def _appended_labelling(**overrides: Any) -> dict[str, Any]:
    """The invented labeller's labels of `_regrown`, from its boundary on,
    under the stamp `_labelling` gives."""
    whole_labelling = _labelling()
    values: dict[str, Any] = {
        "labels": _appended_labels(),
        "units": _units(),
        "test_suites": whole_labelling["test_suites"],
        "ci_builds": whole_labelling["ci_builds"][:1],
    }
    return labelling(**values | overrides)


def _rekinded(*, starters: str, dish: str = "dish") -> list[dict[str, Any]]:
    """`_units` with the starters of the kind `starters` and the soups of
    the kind `dish`."""
    units = _units()
    units[1]["kind"] = starters
    for unit in units[2:]:
        unit["kind"] = dish
    return units


def _bread(*, kind: str = "dish", starters: str = "course") -> PublicationSchema:
    """A sub-agent's thread whose labelling places the bread, a unit of the
    kind `kind`, among the starters, of the kind `starters`."""
    units = _rekinded(starters=starters)[:2] + [
        {"key": BREAD, "kind": kind, "part_of": STARTERS, "title": "Bread"}
    ]
    return sub_agent(calls=[call(1)], labelling=labelling(units=units))


def _declare_sides(container: ServiceContainer, *pairs: tuple[str, str]) -> None:
    """The invented declaration with the kinds `side` and `garnish`, a side
    in a menu, and `pairs`."""
    container.vocabulary_service().declare(
        vocabularies(
            lists=lists(
                work_unit_kind=listed("menu", "course", "dish", "side", "garnish")
            ),
            nesting=nesting(*NESTING, ("side", "menu"), *pairs),
        )
    )


def _placed(db: DbSession) -> dict[str, tuple[str, str | None, str | None]]:
    """Each Work Unit's kind, the key of the unit it sits in and that unit's
    kind as the unit holds it, by its key."""
    outer = aliased(WorkUnit)
    return {
        key: (kind, part_of, part_of_kind)
        for key, kind, part_of, part_of_kind in db.execute(
            select(
                WorkUnit.key, WorkUnit.kind_code, outer.key, WorkUnit.part_of_kind_code
            ).outerjoin(outer, outer.id == WorkUnit.part_of_id)
        )
    }


@pytest.fixture
def publications(container: ServiceContainer) -> PublicationService:
    container.vocabulary_service().declare(vocabularies())
    return container.publication_service()


def _count(db: DbSession, entity: type) -> int:
    return db.scalar(select(func.count()).select_from(entity)) or 0


def _calls(db: DbSession) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in db.execute(
            select(
                Call.message_id,
                Call.segment_position,
                Call.call_class_code,
                Call.avoidable_kind_code,
                Call.wait_cause_code,
            )
            .where(Call.transcript_id == Transcript.id, Transcript.agent_id.is_(None))
            .order_by(Call.position)
        )
    ]


def _labelled(db: DbSession, entity: type) -> list[tuple[Any, ...]]:
    """The labelled rows of an Event's or a Context Part's, by their Call."""
    columns = (
        (Event.kind_code, Event.at, Event.detail)
        if entity is Event
        else (ContextPart.kind_code, ContextPart.name, ContextPart.characters)
    )
    return [
        tuple(row)
        for row in db.execute(
            select(Call.message_id, *columns)
            .join(Call, Call.id == entity.call_id)
            .where(entity.labelled.is_(True))
            .order_by(entity.id)
        )
    ]


def _parts(db: DbSession, message_id: str) -> list[tuple[Any, ...]]:
    """The Context Parts of the Call, the collector's and the labeller's."""
    return [
        tuple(row)
        for row in db.execute(
            select(ContextPart.kind_code, ContextPart.characters, ContextPart.labelled)
            .join(Call, Call.id == ContextPart.call_id)
            .where(Call.message_id == message_id, Transcript.agent_id.is_(None))
            .join(Transcript, Transcript.id == Call.transcript_id)
            .order_by(ContextPart.id)
        )
    ]


def _ids(db: DbSession, entity: type, *where: Any) -> list[int]:
    return list(db.scalars(select(entity.id).where(*where).order_by(entity.id)))


class TestLabelled:
    """A whole publication's labelling, held as the Transcript's labels."""

    def test_the_transcript_is_labelled_under_the_labellers_version_with_its_stamp(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_published(labelling=_labelling()))

        version = session.get_one(ComponentVersion, thread.labelled_under_id)
        assert (version.component_code, version.version) == ("labeller", VERSION)
        assert thread.records_stamp == STAMP

    def test_each_row_of_the_transcript_holds_its_labels(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_published(labelling=_labelling()))

        units = dict(session.execute(select(WorkUnit.id, WorkUnit.key)).all())
        assert [
            units[row]
            for row in session.scalars(
                select(Launch.work_unit_id)
                .where(Launch.transcript_id == thread.id)
                .order_by(Launch.id)
            )
        ] == [SOUP, AGAIN]
        assert _calls(session) == [
            ("msg_0001", 1, "chop", None, "delivery"),
            ("msg_0002", 2, "stir", None, None),
            ("msg_0003", 2, "other", "spilt", "oven"),
        ]
        assert session.execute(
            select(Segment.position, Segment.kind_code).order_by(Segment.position)
        ).all() == [(1, "prep"), (2, "cook")]
        assert session.execute(
            select(
                ToolCall.tool_use_id,
                ToolCall.command_class_code,
                ToolCall.effect_kind_code,
                ToolCall.effect_subject,
            ).order_by(ToolCall.tool_use_id)
        ).all() == [
            ("toolu_0001", None, None, None),
            ("toolu_0002", "timer", None, None),
            ("toolu_0003", None, "order_placed", "ORDER-12"),
            ("toolu_0004", "timer", None, None),
            ("toolu_0005", None, None, None),
        ]
        assert session.execute(
            select(ToolCall.tool_use_id, RuleBreach.rule_code).join(
                ToolCall, ToolCall.id == RuleBreach.tool_call_id
            )
        ).all() == [("toolu_0002", "no_tasting_from_the_pot")]
        assert _labelled(session, Event) == [
            ("msg_0003", "burnt", STARTED + timedelta(minutes=3.6), "the sauce")
        ]
        assert _labelled(session, ContextPart) == [
            ("msg_0001", "recipe_card", "The menu", SECTIONS[0]["characters"]),
            ("msg_0001", "recipe_card", "The pantry", SECTIONS[1]["characters"]),
        ]

    def test_its_test_runs_ci_waits_and_what_they_name_are_held(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_published(labelling=_labelling()))

        suite = session.scalars(select(TestSuite)).one()
        assert (suite.code, suite.name) == (SUITE, "RecipeBox backend test")
        runs = session.execute(
            select(
                ToolCall.tool_use_id,
                WorkUnit.key,
                TestRun.suite_id,
                TestRun.passed,
                TestRun.tests,
                TestRun.retries_allowed,
                TestRun.transcript_id,
            )
            .outerjoin(ToolCall, ToolCall.id == TestRun.tool_call_id)
            .outerjoin(WorkUnit, WorkUnit.id == TestRun.work_unit_id)
            .order_by(TestRun.id)
        ).all()
        assert runs == [
            ("toolu_0004", None, suite.id, False, 12, 1, thread.id),
            (None, STARTERS, suite.id, True, 12, None, thread.id),
        ]
        assert session.execute(
            select(Test.name, TestFailure.attempts, TestFailure.flaky)
            .join(Test, Test.id == TestFailure.test_id)
            .order_by(Test.name)
        ).all() == [
            ("tests/test_scale.py::test_doubles", 2, False),
            ("tests/test_scale.py::test_halves", 2, True),
        ]
        built = session.scalars(select(CIBuild).order_by(CIBuild.number.desc())).first()
        assert built is not None
        assert (built.job, built.number, built.result_code, built.commit_sha) == (
            JOB,
            812,
            "DONE",
            "4f1c2a9",
        )
        assert built.deployed_at == STARTED + timedelta(minutes=11)
        assert sorted(
            session.execute(
                select(ToolCall.tool_use_id, CIBuild.job)
                .select_from(CIWait)
                .join(ToolCall, ToolCall.id == CIWait.tool_call_id)
                .join(CIBuild, CIBuild.id == CIWait.ci_build_id)
            ).all()
        ) == [("toolu_0005", JOB), ("toolu_0005", DEPLOY)]

    def test_its_work_units_sit_where_the_labelling_places_them(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))

        units = {row.key: row for row in session.scalars(select(WorkUnit))}
        again = units[AGAIN]
        assert (again.part_of_id, again.part_of_kind_code) == (
            units[STARTERS].id,
            "course",
        )
        assert (again.occasioned_by_id, again.rework_kind_code) == (
            units[SOUP].id,
            "recooked",
        )
        assert (again.title, again.variant, again.role, again.round) == (
            "Soup again",
            "thicker",
            "cook",
            2,
        )
        assert (again.outcome_code, again.card) == ("served", "KITCHEN-12")
        assert units[MENU].part_of_id is None
        assert sorted(
            session.execute(
                select(
                    WorkUnit.key, WorkUnitMeasure.measure_code, WorkUnitMeasure.amount
                ).join(WorkUnit, WorkUnit.id == WorkUnitMeasure.work_unit_id)
            ).all()
        ) == [(MENU, "planned_dishes", Decimal(4)), (AGAIN, "tastings", Decimal(3))]

    def test_a_documents_ask_category_is_its_labelling_s(
        self,
        session: DbSession,
        publications: PublicationService,
        draft_document: Document,
    ) -> None:
        named = [{"id": str(draft_document.id), "ask_category": "menu_question"}]
        publications.publish(
            _published(labelling=_labelling(labels=_labels(documents=named)))
        )
        session.refresh(draft_document)
        assert draft_document.ask_category_code == "menu_question"

        publications.publish(
            _published(
                labelling=_labelling(
                    labels=_labels(documents=[{"id": str(draft_document.id)}])
                )
            )
        )
        session.refresh(draft_document)
        assert draft_document.ask_category_code is None

    def test_a_sub_agents_thread_is_labelled_as_a_main_thread_is(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(
            sub_agent(
                calls=[call(1)],
                labelling=labelling(
                    labels={
                        "calls": [
                            {"id": "msg_0001", "segment": 1, "call_class": "chop"}
                        ],
                        "segments": [{"position": 1, "kind": "prep"}],
                    }
                ),
            )
        )

        assert thread.records_stamp == STAMP
        assert session.execute(
            select(Call.segment_position, Call.call_class_code).where(
                Call.transcript_id == thread.id
            )
        ).one() == (1, "chop")

    def test_the_same_labelling_again_writes_no_label(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))

        with writes(session) as wrote:
            publications.publish(_published(labelling=_labelling()))

        assert wrote == {"transcripts": Written(updated=1)}


class TestRelabelled:
    """A labelling replaces every label of the Transcript together, and
    nothing older is kept (assertion 561); the Work Units, Test Suites and CI
    Builds stand (`labeller.md`, "It never deletes one at a relabel")."""

    def test_a_relabel_naming_less_leaves_no_label_it_does_not_name(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_published(labelling=_labelling()))

        publications.publish(
            _published(
                labelling=labelling(
                    labels={
                        "calls": [
                            {"id": "msg_0001", "segment": 1},
                            {"id": "msg_0002", "segment": 1},
                            {"id": "msg_0003", "segment": 1, "call_class": "stir"},
                        ],
                        "segments": [{"position": 1, "kind": "cook"}],
                    }
                )
            )
        )

        assert session.scalars(
            select(Launch.work_unit_id).where(Launch.transcript_id == thread.id)
        ).all() == [None, None]
        assert _calls(session) == [
            ("msg_0001", 1, None, None, None),
            ("msg_0002", 1, None, None, None),
            ("msg_0003", 1, "stir", None, None),
        ]
        assert session.execute(select(Segment.position, Segment.kind_code)).all() == [
            (1, "cook")
        ]
        assert session.execute(
            select(ToolCall.command_class_code, ToolCall.effect_kind_code).distinct()
        ).all() == [(None, None)]
        for entity in (RuleBreach, TestRun, TestFailure, CIWait):
            assert _count(session, entity) == 0, entity
        assert _labelled(session, Event) == _labelled(session, ContextPart) == []
        assert (
            _count(session, WorkUnit),
            _count(session, WorkUnitMeasure),
            _count(session, TestSuite),
            _count(session, Test),
            _count(session, CIBuild),
        ) == (4, 2, 1, 2, 2)

    def test_a_label_given_again_otherwise_keeps_its_row(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        held = {entity: _ids(session, entity) for entity in (Segment, TestRun, Event)}
        changed = _labels(
            segments=[
                {"position": 1, "kind": "plate"},
                {"position": 2, "kind": "cook"},
            ],
            events=[{"call": "msg_0003", "kind": "burnt", "at": _at(3.7)}],
        )
        changed["test_runs"][0] |= {"passed": True, "failures": []}

        with writes(session) as wrote:
            publications.publish(_published(labelling=_labelling(labels=changed)))

        assert {entity: _ids(session, entity) for entity in held} == held
        assert wrote == {
            "transcripts": Written(updated=1),
            "segments": Written(updated=1),
            "test_runs": Written(updated=1),
            "test_failures": Written(deleted=2),
            "events": Written(updated=1),
        }

    def test_a_unit_named_again_takes_its_new_row_and_its_measures(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        units = _units()
        units[0] |= {"title": "The summer menu", "measures": []}
        units[3] |= {
            "outcome": "sent_back",
            "measures": [
                {"measure": "tastings", "amount": 5},
                {"measure": "planned_dishes", "amount": 1},
            ],
        }

        publications.publish(_published(labelling=_labelling(units=units)))

        menu = session.scalars(select(WorkUnit).where(WorkUnit.key == MENU)).one()
        assert menu.title == "The summer menu"
        assert sorted(
            session.execute(
                select(
                    WorkUnit.key, WorkUnitMeasure.measure_code, WorkUnitMeasure.amount
                ).join(WorkUnit, WorkUnit.id == WorkUnitMeasure.work_unit_id)
            ).all()
        ) == [(AGAIN, "planned_dishes", Decimal(1)), (AGAIN, "tastings", Decimal(5))]
        assert (
            session.scalars(
                select(WorkUnit.outcome_code).where(WorkUnit.key == AGAIN)
            ).one()
            == "sent_back"
        )

    def test_a_unit_given_another_kind_takes_the_units_in_it_along(
        self,
        session: DbSession,
        container: ServiceContainer,
        publications: PublicationService,
    ) -> None:
        """A unit sits in another as the kind that one has now (DB 551),
        whichever transcript's labelling placed it."""
        _declare_sides(container, ("dish", "side"))
        publications.publish(_published(labelling=_labelling()))
        publications.publish(_bread())

        publications.publish(
            _published(labelling=_labelling(units=_rekinded(starters="side")))
        )

        assert _placed(session) == {
            MENU: ("menu", None, None),
            STARTERS: ("side", MENU, "menu"),
            SOUP: ("dish", STARTERS, "side"),
            AGAIN: ("dish", STARTERS, "side"),
            BREAD: ("dish", STARTERS, "side"),
        }

    def test_units_given_other_kinds_together_stand_as_the_labelling_places_them(
        self,
        session: DbSession,
        container: ServiceContainer,
        publications: PublicationService,
    ) -> None:
        """No nesting pairs a `dish` in a `side`: the starters and the
        dishes in them change their kinds in one write."""
        _declare_sides(container, ("garnish", "side"))
        publications.publish(_published(labelling=_labelling()))

        publications.publish(
            _published(
                labelling=_labelling(units=_rekinded(starters="side", dish="garnish"))
            )
        )

        assert _placed(session) == {
            MENU: ("menu", None, None),
            STARTERS: ("side", MENU, "menu"),
            SOUP: ("garnish", STARTERS, "side"),
            AGAIN: ("garnish", STARTERS, "side"),
        }

    def test_a_unit_no_nesting_lets_follow_sits_nowhere_until_its_labelling_places_it(
        self,
        session: DbSession,
        container: ServiceContainer,
        publications: PublicationService,
    ) -> None:
        """Another transcript's `dish` cannot sit in a `side` (DB 551): it
        sits in no unit until that transcript's labelling places it again."""
        _declare_sides(container, ("garnish", "side"))
        publications.publish(_published(labelling=_labelling()))
        publications.publish(_bread())

        publications.publish(
            _published(
                labelling=_labelling(units=_rekinded(starters="side", dish="garnish"))
            )
        )
        stranded = _placed(session)[BREAD]
        publications.publish(_bread(kind="garnish", starters="side"))

        assert stranded == ("dish", None, None)
        assert _placed(session)[BREAD] == ("garnish", STARTERS, "side")

    def test_a_unit_moved_out_of_one_given_another_kind_takes_its_new_place(
        self,
        session: DbSession,
        container: ServiceContainer,
        publications: PublicationService,
    ) -> None:
        """The starters become a side and their soups move to the mains: the
        side's new kind follows into the soups' rows as the database holds
        them, and their write places them in the mains all the same."""
        _declare_sides(container)
        publications.publish(_published(labelling=_labelling()))
        mains = "spring|mains"
        units = _rekinded(starters="side")
        units.insert(
            2, {"key": mains, "kind": "course", "part_of": MENU, "title": "Mains"}
        )
        for unit in units[3:]:
            unit["part_of"] = mains

        publications.publish(_published(labelling=_labelling(units=units)))

        placed = _placed(session)
        assert placed[STARTERS] == ("side", MENU, "menu")
        assert placed[SOUP] == ("dish", mains, "course")
        assert placed[AGAIN] == ("dish", mains, "course")

    def test_a_test_run_of_another_suite_takes_its_failures_anew(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """A Test Failure carries its run's suite (DB 556)."""
        publications.publish(_published(labelling=_labelling()))
        other = "RecipeBox/frontend/test"
        changed = _labels()
        changed["test_runs"][0]["suite"] = other

        publications.publish(
            _published(
                labelling=_labelling(
                    labels=changed,
                    test_suites=[
                        {"code": SUITE, "name": "RecipeBox backend test"},
                        {"code": other, "name": "RecipeBox frontend test"},
                    ],
                )
            )
        )

        assert sorted(
            session.execute(
                select(TestSuite.code, Test.name)
                .join(TestFailure, TestFailure.test_id == Test.id)
                .join(TestSuite, TestSuite.id == TestFailure.suite_id)
            ).all()
        ) == [
            (other, "tests/test_scale.py::test_doubles"),
            (other, "tests/test_scale.py::test_halves"),
        ]

    def test_a_unit_another_transcript_named_stands_where_this_one_names_it_no_more(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))

        publications.publish(_published(labelling=labelling()))

        assert sorted(session.scalars(select(WorkUnit.key))) == sorted(
            [MENU, STARTERS, SOUP, AGAIN]
        )


class TestAppended:
    """An appended call's labelling is the labeller's answer from the call's
    boundary on: Pilot replaces exactly the labels from there on, and keeps
    those before it as they were (F152.15; DB decision 81). It is no
    relabel: it is taken only where it continues the labels Pilot holds,
    under their stamp and their version's major, and the Transcript is then
    labelled under its version."""

    @staticmethod
    def _held_then_grown(
        publications: PublicationService, **labelled: Any
    ) -> Transcript:
        publications.publish(_published(labelling=_labelling()))
        return publications.publish(_regrown(labelling=_appended_labelling(**labelled)))

    def test_the_calls_and_launches_before_its_boundary_keep_their_labels(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = self._held_then_grown(publications)

        assert _calls(session) == [
            ("msg_0001", 1, "chop", None, "delivery"),
            ("msg_0002", 2, "stir", None, None),
            ("msg_0003", 2, "stir", None, "oven"),
            ("msg_0004", 3, "other", None, None),
        ]
        assert session.execute(
            select(Segment.position, Segment.kind_code).order_by(Segment.position)
        ).all() == [(1, "prep"), (2, "cook"), (3, "plate")]
        assert [
            key
            for (key,) in session.execute(
                select(WorkUnit.key)
                .select_from(Launch)
                .outerjoin(WorkUnit, WorkUnit.id == Launch.work_unit_id)
                .where(Launch.transcript_id == thread.id)
                .order_by(Launch.id)
            )
        ] == [SOUP, None]

    def test_the_segments_from_the_one_its_boundarys_call_falls_in_are_replaced(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The Segment the Call before the boundary falls in takes the kind
        the labelling gives it, and one past the labelling's last goes."""
        publications.publish(
            _published(
                labelling=_labelling(
                    labels=_labels(
                        calls=[
                            {"id": "msg_0001", "segment": 1},
                            {"id": "msg_0002", "segment": 2},
                            {"id": "msg_0003", "segment": 3},
                        ],
                        segments=[
                            {"position": 1, "kind": "prep"},
                            {"position": 2, "kind": "cook"},
                            {"position": 3, "kind": "plate"},
                        ],
                    )
                )
            )
        )

        publications.publish(
            _regrown(
                labelling=_appended_labelling(
                    labels=_appended_labels(
                        calls=[
                            {"id": "msg_0003", "segment": 2},
                            {"id": "msg_0004", "segment": 2},
                        ],
                        segments=[{"position": 2, "kind": "plate"}],
                    )
                )
            )
        )

        assert session.execute(
            select(Segment.position, Segment.kind_code).order_by(Segment.position)
        ).all() == [(1, "prep"), (2, "plate")]
        assert [row[:2] for row in _calls(session)] == [
            ("msg_0001", 1),
            ("msg_0002", 2),
            ("msg_0003", 2),
            ("msg_0004", 2),
        ]

    def test_its_boundarys_call_may_open_the_segment_after_the_one_before(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """As a Call of another kind than the one before it does; the
        Segments before stand."""
        publications.publish(_published(labelling=_labelling()))

        publications.publish(
            _regrown(
                labelling=_appended_labelling(
                    labels=_appended_labels(
                        calls=[
                            {"id": "msg_0003", "segment": 3},
                            {"id": "msg_0004", "segment": 3},
                        ],
                        segments=[{"position": 3, "kind": "plate"}],
                    )
                )
            )
        )

        assert session.execute(
            select(Segment.position, Segment.kind_code).order_by(Segment.position)
        ).all() == [(1, "prep"), (2, "cook"), (3, "plate")]
        assert [row[:2] for row in _calls(session)] == [
            ("msg_0001", 1),
            ("msg_0002", 2),
            ("msg_0003", 3),
            ("msg_0004", 3),
        ]

    def test_one_from_the_first_call_starts_at_the_first_segment(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """No Call stands before its boundary, so it replaces every Segment."""
        publications.publish(
            sub_agent(
                calls=[call(1)],
                labelling=labelling(
                    labels={
                        "calls": [{"id": "msg_0001", "segment": 1}],
                        "segments": [{"position": 1, "kind": "prep"}],
                    }
                ),
            )
        )

        thread = publications.publish(
            sub_agent(
                file_size=61_000,
                appended={
                    "builds_on": builds_on(),
                    "boundary": {"call": 1, "launch": 1, "prompt": 1, "compaction": 1},
                },
                calls=[call(1), call(2, predecessor="msg_0001")],
                labelling=labelling(
                    labels={
                        "calls": [
                            {"id": "msg_0001", "segment": 1},
                            {"id": "msg_0002", "segment": 1},
                        ],
                        "segments": [{"position": 1, "kind": "cook"}],
                    }
                ),
            )
        )

        assert session.execute(
            select(Call.message_id, Call.segment_position)
            .where(Call.transcript_id == thread.id)
            .order_by(Call.position)
        ).all() == [("msg_0001", 1), ("msg_0002", 1)]
        assert session.execute(
            select(Segment.position, Segment.kind_code).where(
                Segment.transcript_id == thread.id
            )
        ).all() == [(1, "cook")]

    @staticmethod
    def _after_no_segment(
        publications: PublicationService, segments: list[dict[str, Any]]
    ) -> Transcript:
        """`_regrown` labelled with `segments`, after a labelling that put
        no Call in a Segment."""
        publications.publish(
            _published(
                labelling=_labelling(
                    labels=_labels(
                        calls=[{"id": f"msg_000{place}"} for place in (1, 2, 3)],
                        segments=[],
                    )
                )
            )
        )
        falls = {"segment": segments[0]["position"]} if segments else {}
        return publications.publish(
            _regrown(
                labelling=_appended_labelling(
                    labels=_appended_labels(
                        calls=[
                            {"id": "msg_0003", "call_class": "stir", **falls},
                            {"id": "msg_0004", "call_class": "other", **falls},
                        ],
                        segments=segments,
                    )
                )
            )
        )

    def test_one_after_a_call_held_in_no_segment_may_name_none(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        self._after_no_segment(publications, [])

        assert [row[:3] for row in _calls(session)] == [
            ("msg_0001", None, None),
            ("msg_0002", None, None),
            ("msg_0003", None, "stir"),
            ("msg_0004", None, "other"),
        ]
        assert _count(session, Segment) == 0

    def test_one_after_a_call_held_in_no_segment_naming_one_is_not_appended(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        with pytest.raises(PublicationNotAppendableException) as refused:
            self._after_no_segment(publications, [{"position": 1, "kind": "cook"}])

        assert refused.value.causes == [
            "the labelling's segments start at 1, and Pilot holds the call before"
            " its boundary in none"
        ]

    def test_the_rows_under_its_calls_take_its_labels_and_those_before_stand(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        self._held_then_grown(publications)

        assert session.execute(
            select(
                ToolCall.tool_use_id,
                ToolCall.command_class_code,
                ToolCall.effect_kind_code,
                ToolCall.effect_subject,
            ).order_by(ToolCall.tool_use_id)
        ).all() == [
            ("toolu_0001", None, None, None),
            ("toolu_0002", "timer", None, None),
            ("toolu_0003", None, "order_placed", "ORDER-12"),
            ("toolu_0004", None, None, None),
            ("toolu_0005", None, None, None),
            ("toolu_0006", "timer", None, None),
        ]
        assert sorted(
            session.execute(
                select(ToolCall.tool_use_id, RuleBreach.rule_code).join(
                    ToolCall, ToolCall.id == RuleBreach.tool_call_id
                )
            ).all()
        ) == [
            ("toolu_0002", "no_tasting_from_the_pot"),
            ("toolu_0006", "no_tasting_from_the_pot"),
        ]
        assert _labelled(session, Event) == [
            ("msg_0004", "burnt", STARTED + timedelta(minutes=4.5), None)
        ]
        assert _labelled(session, ContextPart) == [
            ("msg_0001", "recipe_card", "The menu", SECTIONS[0]["characters"]),
            ("msg_0001", "recipe_card", "The pantry", SECTIONS[1]["characters"]),
        ]
        assert session.execute(
            select(ToolCall.tool_use_id, CIBuild.job)
            .select_from(CIWait)
            .join(ToolCall, ToolCall.id == CIWait.tool_call_id)
            .join(CIBuild, CIBuild.id == CIWait.ci_build_id)
        ).all() == [("toolu_0005", JOB)]
        assert _count(session, CIBuild) == 2

    def test_its_test_runs_are_its_calls_and_the_units(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """A unit's run is given on every answer for the Transcript that
        carries it; a Tool Call's before the boundary stands."""
        runs = _labels()["test_runs"]
        ran_before = {**runs[0], "tool_use_id": "toolu_0002", "failures": []}
        publications.publish(
            _published(
                labelling=_labelling(labels=_labels(test_runs=[ran_before, *runs]))
            )
        )

        publications.publish(_regrown(labelling=_appended_labelling()))

        assert session.execute(
            select(ToolCall.tool_use_id, WorkUnit.key, TestRun.passed)
            .select_from(TestRun)
            .outerjoin(ToolCall, ToolCall.id == TestRun.tool_call_id)
            .outerjoin(WorkUnit, WorkUnit.id == TestRun.work_unit_id)
            .order_by(ToolCall.tool_use_id, WorkUnit.key)
        ).all() == [("toolu_0002", None, False), (None, STARTERS, True)]
        assert _count(session, TestFailure) == 0

    def test_its_documents_take_its_categories(
        self,
        session: DbSession,
        publications: PublicationService,
        draft_document: Document,
    ) -> None:
        publications.publish(_published(labelling=_labelling()))

        publications.publish(
            _regrown(
                labelling=_appended_labelling(
                    labels=_appended_labels(
                        documents=[
                            {
                                "id": str(draft_document.id),
                                "ask_category": "menu_question",
                            }
                        ]
                    )
                )
            )
        )

        session.refresh(draft_document)
        assert draft_document.ask_category_code == "menu_question"

    def test_the_prompt_of_a_call_it_labels_is_carved_and_those_before_stand(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        self._held_then_grown(
            publications,
            labels=_appended_labels(
                context_parts=[
                    {"call": "msg_0003", "kind": "recipe_card", "characters": 40}
                ]
            ),
        )

        assert _parts(session, "msg_0001")[1] == (
            "prompt",
            len(OPENING) - sum(section["characters"] for section in SECTIONS),
            False,
        )
        assert _parts(session, "msg_0003") == [
            ("prompt", 212 - 40, False),
            ("recipe_card", 40, True),
        ]

    @pytest.mark.parametrize(
        "version",
        [VERSION, "1.4.3", "1.5.0"],
        ids=["its own", "a newer patch", "a newer minor"],
    )
    def test_the_transcript_is_labelled_under_its_version_of_the_same_major(
        self, session: DbSession, publications: PublicationService, version: str
    ) -> None:
        thread = self._held_then_grown(publications, version=version)

        labelled_under = session.get_one(ComponentVersion, thread.labelled_under_id)
        assert (labelled_under.component_code, labelled_under.version) == (
            "labeller",
            version,
        )
        assert thread.records_stamp == STAMP

    @pytest.mark.parametrize(
        ("labelled", "cause"),
        [
            (
                {"stamp": "1:7e3f00c1"},
                "Pilot holds its labels under another stamp than the labelling's",
            ),
            (
                {"version": "2.0.0"},
                f"Pilot holds its labels under the labeller's {VERSION}, of another"
                " major than the labelling's 2.0.0",
            ),
            (
                {"version": "0.10.100"},
                f"Pilot holds its labels under the labeller's {VERSION}, of another"
                " major than the labelling's 0.10.100",
            ),
            (
                {
                    "labels": _appended_labels(
                        calls=[
                            {"id": "msg_0003", "segment": 1},
                            {"id": "msg_0004", "segment": 2},
                        ],
                        segments=[
                            {"position": 1, "kind": "prep"},
                            {"position": 2, "kind": "cook"},
                        ],
                    )
                },
                "the labelling's segments start at 1, and Pilot holds the call"
                " before its boundary in segment 2",
            ),
            (
                {
                    "labels": _appended_labels(
                        calls=[
                            {"id": "msg_0003", "segment": 4},
                            {"id": "msg_0004", "segment": 4},
                        ],
                        segments=[{"position": 4, "kind": "plate"}],
                    )
                },
                "the labelling's segments start at 4, and Pilot holds the call"
                " before its boundary in segment 2",
            ),
            (
                {
                    "labels": _appended_labels(
                        calls=[{"id": "msg_0003"}, {"id": "msg_0004"}], segments=[]
                    )
                },
                "the labelling names no segment, and Pilot holds the call before"
                " its boundary in segment 2",
            ),
        ],
        ids=[
            "another stamp",
            "a newer major",
            "an older major",
            "a segment before",
            "a segment past",
            "no segment",
        ],
    )
    def test_one_that_does_not_continue_the_labels_pilot_holds_is_not_appended(
        self,
        session: DbSession,
        publications: PublicationService,
        labelled: dict[str, Any],
        cause: str,
    ) -> None:
        """The collector then publishes it whole, and labelled whole."""
        publications.publish(_published(labelling=_labelling()))

        with (
            writes(session) as wrote,
            pytest.raises(PublicationNotAppendableException) as refused,
        ):
            publications.publish(_regrown(labelling=_appended_labelling(**labelled)))

        assert refused.value.causes == [cause]
        assert wrote == {}

    def test_one_after_a_call_with_no_labelling_is_not_appended(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """Pilot then holds no stamp, which no labelling continues."""
        publications.publish(_published(labelling=_labelling()))
        publications.publish(_published())

        with pytest.raises(PublicationNotAppendableException) as refused:
            publications.publish(_regrown(labelling=_appended_labelling()))

        assert refused.value.causes == ["Pilot holds its labels under no stamp"]

    def test_a_sub_agents_thread_is_labelled_from_its_boundary_on(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        def labelled(*calls: tuple[int, str]) -> dict[str, Any]:
            return labelling(
                labels={
                    "calls": [
                        {"id": f"msg_{place:04}", "segment": 1, "call_class": kind}
                        for place, kind in calls
                    ],
                    "segments": [{"position": 1, "kind": "prep"}],
                }
            )

        publications.publish(
            sub_agent(
                calls=[call(1), call(2)], labelling=labelled((1, "chop"), (2, "chop"))
            )
        )
        thread = publications.publish(
            sub_agent(
                file_size=61_000,
                appended={
                    "builds_on": builds_on(),
                    "boundary": {"call": 2, "launch": 1, "prompt": 1, "compaction": 1},
                },
                calls=[call(2), call(3, predecessor="msg_0002")],
                labelling=labelled((2, "stir"), (3, "other")),
            )
        )

        assert session.execute(
            select(Call.message_id, Call.segment_position, Call.call_class_code)
            .where(Call.transcript_id == thread.id)
            .order_by(Call.position)
        ).all() == [
            ("msg_0001", 1, "chop"),
            ("msg_0002", 1, "stir"),
            ("msg_0003", 1, "other"),
        ]


class TestNoLabelling:
    """A call no labeller answered for writes its facts and leaves every
    label Pilot holds of the Transcript as it stands, with no stamp, so that
    the labeller's next answer differs from it (F152.2, F152.6)."""

    @pytest.mark.parametrize("grown", [False, True], ids=["whole", "appended"])
    def test_it_keeps_every_label_and_holds_no_stamp(
        self, session: DbSession, publications: PublicationService, grown: bool
    ) -> None:
        thread = publications.publish(_published(labelling=_labelling()))
        held = (
            _calls(session),
            _labelled(session, Event),
            _labelled(session, ContextPart),
            _ids(session, Segment),
            _ids(session, TestRun),
            _count(session, RuleBreach),
            _count(session, CIWait),
        )
        labelled_under = thread.labelled_under_id

        if grown:
            publications.publish(_grown())
        else:
            publications.publish(_published())

        assert (
            _calls(session)[:3],
            _labelled(session, Event),
            _labelled(session, ContextPart),
            _ids(session, Segment),
            _ids(session, TestRun),
            _count(session, RuleBreach),
            _count(session, CIWait),
        ) == held
        session.refresh(thread)
        assert (thread.labelled_under_id, thread.records_stamp) == (
            labelled_under,
            None,
        )

    def test_a_transcript_no_labelling_covered_holds_its_facts_and_no_label(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        thread = publications.publish(_published())

        assert (thread.labelled_under_id, thread.records_stamp) == (None, None)
        assert {row[1:] for row in _calls(session)} == {(None, None, None, None)}
        assert _count(session, Segment) == 0
        assert _labelled(session, ContextPart) == []


class TestFactsAndLabels:
    """The facts are the Events and Context Parts the collector read, the
    labels those the labeller gave: neither writes the other's (slice 047's
    I2)."""

    @pytest.mark.parametrize("collected", [0, 1, 2], ids=["fewer", "the same", "more"])
    def test_the_collectors_events_under_a_call_leave_its_labelled_ones(
        self, session: DbSession, publications: PublicationService, collected: int
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        held = _ids(session, Event, Event.labelled.is_(True))
        labelled = _labelled(session, Event)
        published = _published()
        third = published.calls[2].model_dump(mode="json")
        third["events"] = [
            event(at=_at(3.5 + place / 10)) for place in range(collected)
        ]

        for labels in (None, _labelling()):
            publications.publish(
                _published(
                    calls=[*published.model_dump(mode="json")["calls"][:2], third],
                    labelling=labels,
                )
            )

            assert _ids(session, Event, Event.labelled.is_(True)) == held
            assert _labelled(session, Event) == labelled
            assert _count(session, Event) == 1 + collected + len(held)

    @pytest.mark.parametrize("collected", [1, 2, 3], ids=["fewer", "the same", "more"])
    def test_the_collectors_context_parts_under_a_call_leave_its_labelled_ones(
        self, session: DbSession, publications: PublicationService, collected: int
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        held = _ids(session, ContextPart, ContextPart.labelled.is_(True))
        labelled = _labelled(session, ContextPart)
        first = _published().calls[0].model_dump(mode="json")
        others = [
            context_part(),
            context_part(kind="tool_schemas", characters=45_300),
        ][: collected - 1]
        first["context_parts"] = [
            *others,
            context_part(kind="prompt", characters=len(OPENING)),
        ]
        rest = _published().model_dump(mode="json")["calls"][1:]

        publications.publish(_published(calls=[first, *rest]))

        assert _ids(session, ContextPart, ContextPart.labelled.is_(True)) == held
        assert _labelled(session, ContextPart) == labelled

    @pytest.mark.parametrize("labelled", [False, True], ids=["unlabelled", "labelled"])
    @pytest.mark.parametrize("collected", [0, 1, 2], ids=["fewer", "the same", "more"])
    def test_an_appended_calls_events_leave_the_labelled_ones_under_its_calls(
        self,
        session: DbSession,
        publications: PublicationService,
        collected: int,
        labelled: bool,
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        held = _ids(session, Event, Event.labelled.is_(True))
        labels = _labelled(session, Event)
        calls = _regrown().model_dump(mode="json")["calls"]
        calls[0]["events"] = [
            event(at=_at(3.5 + place / 10)) for place in range(collected)
        ]
        burnt = {"call": "msg_0003", "kind": "burnt", "at": _at(3.6)}

        publications.publish(
            _regrown(
                calls=calls,
                labelling=_appended_labelling(
                    labels=_appended_labels(events=[burnt | {"detail": "the sauce"}])
                )
                if labelled
                else None,
            )
        )

        assert _ids(session, Event, Event.labelled.is_(True)) == held
        assert _labelled(session, Event) == labels
        assert _count(session, Event) == 1 + collected + len(held)

    def test_a_relabel_leaves_the_collectors_rows(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        events = _ids(session, Event, Event.labelled.is_(False))
        parts = _ids(session, ContextPart, ContextPart.labelled.is_(False))

        with writes(session) as wrote:
            publications.publish(
                _published(
                    labelling=_labelling(
                        labels=_labels(
                            events=[
                                {"call": "msg_0001", "kind": "burnt", "at": _at(0.6)},
                                {"call": "msg_0003", "kind": "burnt", "at": _at(3.6)},
                            ]
                        )
                    )
                )
            )

        assert _ids(session, Event, Event.labelled.is_(False)) == events
        assert _ids(session, ContextPart, ContextPart.labelled.is_(False)) == parts
        assert wrote["events"] == Written(inserted=1, updated=1)


class TestCarved:
    """A dispatch's digest sections are carved out of its opening prompt's
    Context Part, not beside it: a first Call's parts add up to what it
    carried once (D266). The carve moves with the labels, and is made again
    from what the collector counted."""

    def test_the_digests_sections_are_carved_out_of_the_prompt_that_holds_them(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))

        carved = len(OPENING) - sum(section["characters"] for section in SECTIONS)
        assert _parts(session, "msg_0001") == [
            ("system_prompt", 9_100, False),
            ("prompt", carved, False),
            ("recipe_card", SECTIONS[0]["characters"], True),
            ("recipe_card", SECTIONS[1]["characters"], True),
        ]
        assert sum(characters for _, characters, _ in _parts(session, "msg_0001")) == (
            9_100 + len(OPENING)
        )

    def test_a_relabel_carves_again_from_what_the_collector_counted(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        menu = SECTIONS[0]

        publications.publish(
            _published(
                labelling=_labelling(
                    labels=_labels(
                        context_parts=[
                            {"call": "msg_0001", "kind": "recipe_card", **menu}
                        ]
                    )
                )
            )
        )
        assert _parts(session, "msg_0001")[1] == (
            "prompt",
            len(OPENING) - menu["characters"],
            False,
        )

        publications.publish(
            _published(labelling=_labelling(labels=_labels(context_parts=[])))
        )
        assert _parts(session, "msg_0001")[1] == ("prompt", len(OPENING), False)

    def test_a_publication_with_no_labelling_carves_with_the_parts_pilot_holds(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        held = _parts(session, "msg_0001")

        with writes(session) as wrote:
            publications.publish(_published())

        assert _parts(session, "msg_0001") == held
        assert wrote == {"transcripts": Written(updated=1)}

    def test_a_prompt_the_collector_counts_otherwise_is_carved_from_its_new_count(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        publications.publish(_published(labelling=_labelling()))
        first = _published().calls[0].model_dump(mode="json")
        first["context_parts"][1]["characters"] = len(OPENING) + 40
        rest = _published().model_dump(mode="json")["calls"][1:]

        publications.publish(_published(calls=[first, *rest]))

        carved = sum(section["characters"] for section in SECTIONS)
        assert _parts(session, "msg_0001")[1] == (
            "prompt",
            len(OPENING) + 40 - carved,
            False,
        )


class TestReplayedAtRest:
    """A labelled row the replay at rest changes is logged with its
    Transcript, beside the facts' rows, where the labelling is under the
    labeller's version and stamp Pilot held (F152.16)."""

    LATER = call(4, prompt=2, predecessor="msg_0003")
    GROWN = {"file_size": 61_000, "file_modified_at": _at(30)}

    def _held_appended(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """The transcript labelled whole, then grown by a fourth Call taken
        appended and labelled from it on, under the stamp the rest was
        labelled under: the fourth Call in the second Segment, and the
        starters' run, which every answer for the transcript gives."""
        publications.publish(_published(labelling=_labelling()))
        publications.publish(
            _grown(
                labelling=_appended_labelling(
                    labels={
                        "launches": [{"n": 2, "work_unit": AGAIN}],
                        "calls": [{"id": "msg_0004", "segment": 2}],
                        "segments": [{"position": 2, "kind": "cook"}],
                        "test_runs": _labels()["test_runs"][1:],
                    },
                    ci_builds=[],
                )
            )
        )

    def _at_rest(self, **overrides: Any) -> PublicationSchema:
        calls = _published().model_dump(mode="json")["calls"]
        return _published(calls=[*calls, self.LATER], **self.GROWN | overrides)

    def _logged(self, caplog: pytest.LogCaptureFixture) -> list[str]:
        return [r.getMessage() for r in caplog.records if r.name == LOGGER]

    def test_a_label_it_changes_is_logged_beside_the_facts(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        self._held_appended(session, publications)
        labels = _labels()
        labels["calls"].append({"id": "msg_0004", "segment": 2, "call_class": "stir"})

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(self._at_rest(labelling=_labelling(labels=labels)))

        assert self._logged(caplog) == [
            "The replay at rest of transcript"
            f" {_published().session_id}, 12888 of its 61000 bytes taken in parts,"
            " wrote labels that differ from what Pilot held: calls 1"
        ]

    def test_a_carve_that_moved_with_the_labels_is_no_fact_that_changed(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        self._held_appended(session, publications)
        labels = _labels(
            context_parts=[{"call": "msg_0001", "kind": "recipe_card", **SECTIONS[0]}]
        )
        labels["calls"].append({"id": "msg_0004", "segment": 2})

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(self._at_rest(labelling=_labelling(labels=labels)))

        assert self._logged(caplog) == [
            "The replay at rest of transcript"
            f" {_published().session_id}, 12888 of its 61000 bytes taken in parts,"
            " wrote labels that differ from what Pilot held: context_parts 1"
        ]

    @pytest.mark.parametrize(
        "held",
        [{"version": "1.4.3"}, {"version": "1.5.0"}, {"stamp": "1:7e3f00c1"}],
        ids=["a newer patch", "a newer minor", "another stamp"],
    )
    def test_one_under_another_version_or_stamp_logs_no_label(
        self,
        session: DbSession,
        publications: PublicationService,
        caplog: pytest.LogCaptureFixture,
        held: dict[str, str],
    ) -> None:
        """What a whole publication under a newer minor or patch improves is
        no replay difference."""
        self._held_appended(session, publications)
        labels = _labels()
        labels["calls"].append({"id": "msg_0004", "segment": 2, "call_class": "stir"})

        with caplog.at_level(logging.WARNING, LOGGER):
            publications.publish(
                self._at_rest(labelling=_labelling(labels=labels, **held))
            )

        assert self._logged(caplog) == []


class TestRefusedLabelling:
    """A labelling that contradicts its call or the record's rules for
    labels is a fault of the call, and nothing is written."""

    @staticmethod
    def _faults(
        session: DbSession,
        publications: PublicationService,
        publication: PublicationSchema,
    ) -> list[str]:
        with (
            writes(session) as wrote,
            pytest.raises(PublicationInvalidException) as raised,
        ):
            publications.publish(publication)
        assert wrote == {}
        return raised.value.faults

    @pytest.mark.parametrize(
        ("labelled", "fault"),
        [
            (
                {"labels": _labels(launches=[{"n": 3}])},
                "launch 3: the call has 2 launches",
            ),
            (
                {"labels": _labels(launches=[{"n": 1, "work_unit": "autumn"}])},
                "launch 1: the unit `autumn` is none of the call's `units`",
            ),
            (
                {
                    "labels": _labels(
                        calls=[*_labels()["calls"], {"id": "msg_0001", "segment": 1}]
                    )
                },
                "call `msg_0001` is labelled 2 times",
            ),
            (
                {"labels": _labels(calls=[*_labels()["calls"], {"id": "msg_0009"}])},
                "call `msg_0009`: no call of the call's",
            ),
            (
                {"labels": _labels(segments=[{"position": 2, "kind": "prep"}])},
                "the segments' positions are not 1 to their number, in order",
            ),
            (
                {
                    "labels": _labels(
                        calls=[
                            {"id": "msg_0001", "segment": 1},
                            {"id": "msg_0002", "segment": 2},
                            {"id": "msg_0003", "segment": 1},
                        ]
                    )
                },
                "call `msg_0003`: segment 1 follows segment 2",
            ),
            (
                {"labels": _labels(calls=[{"id": "msg_0001", "segment": 1}])},
                "call `msg_0002`: names no segment",
            ),
            (
                {
                    "labels": _labels(
                        segments=[
                            {"position": 1, "kind": "prep"},
                            {"position": 2, "kind": "cook"},
                            {"position": 3, "kind": "plate"},
                        ]
                    )
                },
                "segment 3 holds no call",
            ),
            (
                {"labels": _labels(tool_calls=[{"tool_use_id": "toolu_0099"}])},
                "tool call `toolu_0099`: no tool call of the call's",
            ),
            (
                {
                    "labels": _labels(
                        tool_calls=[
                            {"tool_use_id": "toolu_0003", "effect_subject": "ORDER-12"}
                        ]
                    )
                },
                "tool call `toolu_0003`: an `effect_subject` with no `effect_kind`",
            ),
            (
                {
                    "labels": _labels(
                        events=[{"call": "msg_0009", "kind": "burnt", "at": _at(1)}]
                    )
                },
                "call `msg_0009`: no call of the call's",
            ),
            (
                {
                    "labels": _labels(
                        context_parts=[
                            {
                                "call": "msg_0001",
                                "kind": "recipe_card",
                                "characters": len(OPENING) + 1,
                            }
                        ]
                    )
                },
                f"call `msg_0001`: its labelled context parts carry {len(OPENING) + 1}"
                f" characters, more than its opening `prompt`'s {len(OPENING)}",
            ),
            (
                {
                    "labels": _labels(
                        context_parts=[
                            {
                                "call": "msg_0002",
                                "kind": "recipe_card",
                                "characters": 10,
                            }
                        ]
                    )
                },
                "call `msg_0002`: its labelled context parts carry 10 characters, and"
                " it carries no `prompt` to carve them from",
            ),
            (
                {
                    "labels": _labels(
                        test_runs=[{"suite": SUITE, "passed": True, "tests": 1}]
                    )
                },
                "test run 1: run by exactly one of a tool call and a unit",
            ),
            (
                {
                    "labels": _labels(
                        test_runs=[
                            {
                                "work_unit": MENU,
                                "suite": "Pantry/test",
                                "passed": True,
                                "tests": 1,
                            }
                        ]
                    )
                },
                "test run 1: the suite `Pantry/test` is none of the call's `test_suites`",
            ),
            (
                {
                    "labels": _labels(
                        ci_waits=[
                            {"tool_use_id": "toolu_0005", "job": JOB, "number": 813}
                        ]
                    )
                },
                f"ci wait of `toolu_0005`: {JOB} #813 is none of the call's `ci_builds`",
            ),
            (
                {"units": [*_units(), _units()[0]]},
                f"unit `{MENU}` is labelled 2 times",
            ),
            (
                {"units": [_units()[1], _units()[0], *_units()[2:]]},
                f"unit `{STARTERS}`: its `part_of` `{MENU}` is no unit before it",
            ),
        ],
        ids=[
            "a launch past the call's",
            "a launch's unit not given",
            "a call twice",
            "a call not the call's",
            "segments not from 1",
            "a segment going back",
            "a call in no segment",
            "a segment of no call",
            "a tool call not the call's",
            "a subject of no effect",
            "an event of no call",
            "a carve past the prompt",
            "a carve of no prompt",
            "a run of no runner",
            "a suite not given",
            "a build not given",
            "a unit twice",
            "a unit before its own",
        ],
    )
    def test_a_labelling_that_contradicts_its_call_is_a_fault(
        self,
        session: DbSession,
        publications: PublicationService,
        labelled: dict[str, Any],
        fault: str,
    ) -> None:
        faults = self._faults(
            session, publications, _published(labelling=_labelling(**labelled))
        )

        assert fault in faults

    @pytest.mark.parametrize(
        ("labels", "fault"),
        [
            (
                _appended_labels(launches=[{"n": 1, "work_unit": SOUP}]),
                "launch 1: before the call's boundary, at launch 2",
            ),
            (
                _appended_labels(launches=[{"n": 3}]),
                "launch 3: the call has 2 launches",
            ),
            (
                _appended_labels(
                    segments=[
                        {"position": 2, "kind": "cook"},
                        {"position": 4, "kind": "plate"},
                    ]
                ),
                "the segments' positions do not follow one another, in order",
            ),
            (
                _appended_labels(
                    calls=[
                        {"id": "msg_0003", "segment": 1},
                        {"id": "msg_0004", "segment": 2},
                    ]
                ),
                "call `msg_0003`: names segment 1, of none",
            ),
            (
                _appended_labels(
                    calls=[
                        {"id": "msg_0003", "segment": 3},
                        {"id": "msg_0004", "segment": 3},
                    ]
                ),
                "call `msg_0003`: segment 3 follows segment 1",
            ),
            (
                _appended_labels(
                    calls=[
                        *_appended_labels()["calls"],
                        {"id": "msg_0001", "segment": 1},
                    ]
                ),
                "call `msg_0001`: no call of the call's",
            ),
            (
                _appended_labels(tool_calls=[{"tool_use_id": "toolu_0002"}]),
                "tool call `toolu_0002`: no tool call of the call's",
            ),
        ],
        ids=[
            "a launch before the boundary",
            "a launch past the call's",
            "segments with a gap",
            "the boundary's call in a segment before",
            "the boundary's call past the first segment",
            "a call before the boundary",
            "a tool call before the boundary",
        ],
    )
    def test_an_appended_labelling_labels_what_its_call_carries(
        self,
        session: DbSession,
        publications: PublicationService,
        labels: dict[str, Any],
        fault: str,
    ) -> None:
        publications.publish(_published(labelling=_labelling()))

        faults = self._faults(
            session,
            publications,
            _regrown(labelling=_appended_labelling(labels=labels)),
        )

        assert fault in faults

    @pytest.mark.parametrize("grown", [False, True], ids=["whole", "appended"])
    def test_a_group_with_no_labelling_is_a_fault(
        self, session: DbSession, publications: PublicationService, grown: bool
    ) -> None:
        group = {"key": "spring-menus", "name": "Spring menus", "summary": "Soups."}
        publications.publish(_published())

        publication = _grown(group=group) if grown else _published(group=group)
        assert self._faults(session, publications, publication) == [
            "a call with no labelling names no `group`"
        ]

    def test_a_value_no_list_declares_is_a_fault(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        labels = _labels()
        labels["calls"][0]["call_class"] = "simmer"
        labels["segments"][1]["kind"] = "garnish"

        assert self._faults(
            session, publications, _published(labelling=_labelling(labels=labels))
        ) == [
            "`segment_kind` `garnish`: no value the labeller declares",
            "`call_class` `simmer`: no value the labeller declares",
        ]

    def test_a_value_its_list_no_longer_declares_is_a_fault(
        self,
        session: DbSession,
        container: ServiceContainer,
        publications: PublicationService,
    ) -> None:
        """P1 keeps it, with no place, while a label names it."""
        publications.publish(_published(labelling=_labelling()))
        container.vocabulary_service().declare(
            vocabularies(lists=lists(call_class=lists()["call_class"][::2]))
        )

        assert self._faults(
            session, publications, _published(labelling=_labelling())
        ) == ["`call_class` `stir`: no value the labeller declares"]

    def test_a_unit_where_no_nesting_pairs_its_kind_is_a_fault(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        units = _units()
        units[2]["part_of"] = MENU

        assert self._faults(
            session, publications, _published(labelling=_labelling(units=units))
        ) == [f"unit `{SOUP}`: no nesting pairs a `dish` in a `menu`"]

    def test_a_document_pilot_does_not_hold_is_a_fault(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        named = "0b5e3c1a-0000-4f6e-9a18-2c4d6e8f0a1b"

        assert self._faults(
            session,
            publications,
            _published(labelling=_labelling(labels=_labels(documents=[{"id": named}]))),
        ) == [f"document `{named}`: no document Pilot holds"]

    def test_a_prompt_too_short_for_the_labels_pilot_holds_is_a_fault(
        self, session: DbSession, publications: PublicationService
    ) -> None:
        """Pilot keeps the labels of a call with no labelling, so the
        prompt they carve must hold them."""
        publications.publish(_published(labelling=_labelling()))
        first = _published().calls[0].model_dump(mode="json")
        first["context_parts"][1]["characters"] = 40
        rest = _published().model_dump(mode="json")["calls"][1:]
        carved = sum(section["characters"] for section in SECTIONS)

        assert self._faults(
            session, publications, _published(calls=[first, *rest])
        ) == [
            f"call `msg_0001`: the labelled context parts Pilot holds carry {carved}"
            " characters, more than its opening `prompt`'s 40"
        ]


def test_the_sub_agents_labels_name_no_document(
    session: DbSession, publications: PublicationService, draft_document: Document
) -> None:
    with pytest.raises(PublicationInvalidException) as raised:
        publications.publish(
            sub_agent(
                labelling=labelling(
                    labels={"documents": [{"id": str(draft_document.id)}]}
                )
            )
        )

    assert raised.value.faults == ["a sub-agent's thread labels no document"]
    assert (
        session.scalars(
            select(Transcript.id).where(Transcript.agent_id == SUB_AGENT)
        ).all()
        == []
    )
