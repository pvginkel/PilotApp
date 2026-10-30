"""The reference entities: the enum types, and the four tables' rows the revisions write."""

import pilot_dsl
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import ConfirmationReason, DoneCause, ItemKind, SessionKind
from app.models.reference import ENUM_TYPES, AnswerChannel, BlockKind
from tests.support.database import violated_constraint


class TestEnumTypes:
    def test_the_database_holds_the_models_enums(self, session: Session) -> None:
        """Every enum type, and its values in order, is the revisions' and the models'."""
        rows = session.execute(
            text(
                "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)"
                " FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"
                " GROUP BY t.typname"
            )
        ).all()

        assert dict(rows) == {enum.name: list(enum.enums) for enum in ENUM_TYPES}

    def test_the_enums_are_db_s_twenty(self) -> None:
        """With the four tables, 24 of the reference entities of DB §2.4."""
        assert {enum.name for enum in ENUM_TYPES} == {
            "user_kind",
            "overrule_kind",
            "project_state",
            "transition_kind",
            "document_role",
            "version_cause",
            "error_kind",
            "block_kind",
            "answer_channel",
            "work_trigger",
            "firing_cause",
            "attachment_source",
            "session_state",
            "record_kind",
            "chat_kind",
            "close_cause",
            "effect_kind",
            "task_status",
            "notification_priority",
            "condition",
        }


class TestTheBlockDsl:
    def test_its_answer_channels_are_the_record_s(self) -> None:
        assert {str(channel) for channel in pilot_dsl.AnswerChannel} == {
            str(channel) for channel in AnswerChannel
        }

    def test_its_block_kinds_are_the_record_s(self) -> None:
        assert {str(kind) for kind in pilot_dsl.BlockKind} == {
            str(kind) for kind in BlockKind
        }


class TestItemKind:
    def test_the_revisions_write_the_kinds(self, session: Session) -> None:
        rows = session.execute(
            select(ItemKind.code, ItemKind.name, ItemKind.form, ItemKind.icon)
        ).all()

        assert set(rows) == {
            ("opening", "Opening", "prose", "message"),
            ("decision", "Decision", "prose", "ask"),
            ("confirmation", "Confirmation", "prose", "shield"),
            ("question", "Question", "prose", "ask"),
            ("action", "Action", "prose", "hand"),
            ("notice", "Notice", "prose", "info"),
            ("document", "Document", "prose", "file"),
            ("review", "Review", "prose", "book"),
            ("archive_question", "Archive question", "prose", "archive"),
            ("work", "Work", "work", "terminal"),
            ("card_wait", "Card wait", "wait", "ticket"),
            ("timed_wait", "Timed wait", "wait", "hourglass"),
        }

    def test_form_is_prose_work_or_wait(self, session: Session) -> None:
        session.add(ItemKind(code="other", name="Other", form="other", icon="ask"))

        assert violated_constraint(session) == "ck_item_kinds_form"


class TestDoneCause:
    def test_the_revisions_write_the_causes(self, session: Session) -> None:
        rows = session.execute(
            select(DoneCause.code, DoneCause.name, DoneCause.undo_offered)
        ).all()

        assert set(rows) == {
            ("answered", "Answered", True),
            ("marked", "Marked", True),
            ("settled", "Settled", True),
            ("turn_ended", "Turn ended", False),
            ("finished", "Finished", False),
            ("withdrawn", "Withdrawn", False),
        }


class TestConfirmationReason:
    def test_the_revisions_write_the_reasons(self, session: Session) -> None:
        reasons = session.scalars(select(ConfirmationReason)).all()

        assert {
            (reason.code, reason.name, reason.asks_under_autopilot)
            for reason in reasons
        } == {
            ("auto-pilot-off", "Auto pilot off", False),
            ("rider", "Rider", False),
            ("irreversible", "Irreversible", True),
            ("product-hold", "Product hold", True),
            ("self-approval", "Self-approval", True),
            ("standing-grant", "Standing grant", True),
        }

    def test_every_reason_says_when_to_use_it_in_one_line(
        self, session: Session
    ) -> None:
        descriptions = session.scalars(select(ConfirmationReason.description)).all()

        assert len(descriptions) == 6
        assert all(
            description and "\n" not in description for description in descriptions
        )


class TestSessionKind:
    def test_the_revisions_write_the_kinds(self, session: Session) -> None:
        rows = session.execute(
            select(
                SessionKind.code,
                SessionKind.name,
                SessionKind.surface,
                SessionKind.on_timeline,
            )
        ).all()

        assert set(rows) == {
            ("chat", "Chat", "pilot-store", False),
            ("work", "Work", "pilot-work", True),
            ("job", "Job", "pilot-store", True),
        }

    def test_surface_is_pilot_store_or_pilot_work(self, session: Session) -> None:
        session.add(
            SessionKind(
                code="other", name="Other", surface="pilot-other", on_timeline=False
            )
        )

        assert violated_constraint(session) == "ck_session_kinds_surface"
