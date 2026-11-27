"""Revision 0058: the Events and Context Parts stored are the collector's,
and its downgrade takes every label, the labeller's Events and Context Parts
with them."""

from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from app.models import (
    Call,
    ContextPart,
    ContextPartKind,
    Event,
    EventKind,
    Segment,
    SegmentKind,
)
from tests.support import labels, transcripts
from tests.support.revisions import run_revision
from tests.support.transcripts import STARTED

TABLES = text(
    "SELECT table_name FROM information_schema.tables WHERE table_name IN"
    " ('work_units', 'work_unit_measures', 'segments', 'rule_breaches',"
    " 'test_suites', 'tests', 'test_runs', 'test_failures', 'ci_builds',"
    " 'ci_waits')"
)
COLUMNS = text(
    "SELECT table_name || '.' || column_name FROM information_schema.columns"
    " WHERE (table_name, column_name) IN (('transcripts', 'labelled_under_id'),"
    " ('transcripts', 'records_stamp'), ('launches', 'work_unit_id'),"
    " ('calls', 'wait_cause_code'), ('calls', 'segment_position'),"
    " ('calls', 'call_class_code'), ('calls', 'avoidable_kind_code'),"
    " ('tool_calls', 'command_class_code'), ('tool_calls', 'effect_kind_code'),"
    " ('tool_calls', 'effect_subject'), ('documents', 'ask_category_code'),"
    " ('events', 'labelled'), ('context_parts', 'labelled'))"
    " ORDER BY 1"
)


def _first_call(db: DbSession) -> Call:
    """A main thread's first Call, with an Event and a Context Part the
    collector read off its file."""
    thread = transcripts.transcript(db, transcripts.component_version(db))
    request = transcripts.call(db, thread, 1)
    transcripts.reference(db, EventKind, "api_error", is_error=True)
    transcripts.reference(db, ContextPartKind, "system_prompt")
    db.add_all(
        [
            Event(call_id=request.id, kind_code="api_error", at=STARTED),
            ContextPart(call_id=request.id, kind_code="system_prompt", characters=9),
        ]
    )
    db.flush()
    return request


class TestTheDowngrade:
    def test_every_label_goes_and_the_collectors_rows_stay(
        self, session: DbSession
    ) -> None:
        request = _first_call(session)
        labels.declared(session, EventKind, "burnt", is_error=False)
        labels.declared(session, ContextPartKind, "recipe_card")
        labels.declared(session, SegmentKind, "cook")
        session.add_all(
            [
                Event(call_id=request.id, kind_code="burnt", at=STARTED, labelled=True),
                ContextPart(
                    call_id=request.id,
                    kind_code="recipe_card",
                    characters=4,
                    labelled=True,
                ),
                Segment(
                    transcript_id=request.transcript_id, position=1, kind_code="cook"
                ),
            ]
        )
        session.flush()
        request.segment_position = 1
        session.flush()

        run_revision(session, "0058", "downgrade")

        assert session.scalars(TABLES).all() == []
        assert session.scalars(COLUMNS).all() == []
        assert session.scalars(text("SELECT kind_code FROM events")).all() == [
            "api_error"
        ]
        assert session.scalars(text("SELECT kind_code FROM context_parts")).all() == [
            "system_prompt"
        ]


class TestTheUpgrade:
    def test_the_events_and_context_parts_held_are_the_collectors(
        self, session: DbSession
    ) -> None:
        _first_call(session)
        run_revision(session, "0058", "downgrade")

        run_revision(session, "0058", "upgrade")

        assert session.scalars(text("SELECT labelled FROM events")).all() == [False]
        assert session.scalars(text("SELECT labelled FROM context_parts")).all() == [
            False
        ]
        assert len(session.scalars(COLUMNS).all()) == 13
        assert len(session.scalars(TABLES).all()) == 10
