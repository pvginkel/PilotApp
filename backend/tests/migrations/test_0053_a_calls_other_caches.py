"""Revision 0053: the Calls stored gain their other caches' columns, with
none derived, and its downgrade takes them, a Transcript's two times and the
Step Transcripts' index."""

from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.models import Call, Transcript
from tests.support import transcripts
from tests.support.revisions import run_revision
from tests.support.transcripts import STARTED

COLUMNS = text(
    "SELECT table_name || '.' || column_name FROM information_schema.columns"
    " WHERE (table_name, column_name) IN (('calls', 'waited_seconds'),"
    " ('calls', 'rewind'), ('calls', 'cache_miss'), ('calls', 'past_ttl'),"
    " ('calls', 'launch_id'), ('transcripts', 'first_call_at'),"
    " ('transcripts', 'last_call_at'))"
    " ORDER BY 1"
)
INDEXES = text(
    "SELECT indexname FROM pg_indexes WHERE indexname IN ('ix_calls_underived',"
    " 'ix_calls_launch_id', 'ix_step_transcripts_session_id') ORDER BY 1"
)


def _stored(db: DbSession) -> int:
    """A Call stored with its caches, made in a Launch of its Transcript,
    which holds its two times."""
    thread = transcripts.transcript(
        db,
        transcripts.component_version(db),
        first_call_at=STARTED,
        last_call_at=STARTED,
    )
    launch = transcripts.launch(db, thread)
    return transcripts.call(
        db,
        thread,
        1,
        waited_seconds=12.5,
        rewind=False,
        cache_miss=True,
        past_ttl=False,
        launch_id=launch.id,
    ).id


class TestTheDowngrade:
    def test_a_calls_caches_and_a_transcripts_times_go(
        self, session: DbSession
    ) -> None:
        call_id = _stored(session)

        run_revision(session, "0053", "downgrade")

        assert session.scalars(COLUMNS).all() == []
        assert session.scalars(INDEXES).all() == []
        assert session.scalars(
            text("SELECT message_id FROM calls WHERE id = :id"), {"id": call_id}
        ).all() == ["msg_0001"]


class TestTheUpgrade:
    def test_a_stored_call_gains_no_cache_and_its_transcript_no_time(
        self, session: DbSession
    ) -> None:
        """The step after the revisions derives them
        (`CallCacheService.derive`)."""
        call_id = _stored(session)

        run_revision(session, "0053", "downgrade")

        run_revision(session, "0053", "upgrade")

        assert session.scalars(COLUMNS).all() == [
            "calls.cache_miss",
            "calls.launch_id",
            "calls.past_ttl",
            "calls.rewind",
            "calls.waited_seconds",
            "transcripts.first_call_at",
            "transcripts.last_call_at",
        ]
        assert session.scalars(INDEXES).all() == [
            "ix_calls_launch_id",
            "ix_calls_underived",
            "ix_step_transcripts_session_id",
        ]
        assert session.execute(
            select(
                Call.waited_seconds,
                Call.rewind,
                Call.cache_miss,
                Call.past_ttl,
                Call.launch_id,
            ).where(Call.id == call_id)
        ).all() == [(None, None, None, None, None)]
        assert session.execute(
            select(Transcript.first_call_at, Transcript.last_call_at)
        ).all() == [(None, None)]
