"""Block and Block Option: what a row must hold."""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import Block, BlockOption, Document, User
from app.models.reference import AnswerChannel, BlockKind
from tests.support.database import violated_constraint


def _block(document: Document, **overrides: object) -> Block:
    values: dict[str, object] = {
        "document_id": document.id,
        "local_id": "D1",
        "position": 1,
        "kind_code": BlockKind.DECISION,
    }
    values.update(overrides)
    return Block(**values)


class TestBlock:
    def test_a_block_is_written(
        self, session: DbSession, draft_document: Document
    ) -> None:
        block = _block(draft_document)
        session.add(block)
        session.flush()
        session.refresh(block)

        assert block.confirmation is False
        assert block.answer is None
        assert block.updated_at is not None

    def test_a_persons_answer_is_kept(
        self, session: DbSession, draft_document: Document, person: User
    ) -> None:
        block = _block(
            draft_document,
            answer="Yes",
            answered_by_user_id=person.id,
            via_code=AnswerChannel.CHAT,
            note="Fine by me.",
        )
        session.add(block)
        session.flush()

        assert block.answer == "Yes"

    def test_a_local_id_is_one_block_of_its_document(
        self, session: DbSession, draft_document: Document
    ) -> None:
        session.add_all(
            [_block(draft_document), _block(draft_document, kind_code=BlockKind.ACTION)]
        )

        assert violated_constraint(session) == "blocks_document_id_local_id_key"

    def test_a_confirmation_asks_with_a_reason_and_a_proposal(
        self, session: DbSession, draft_document: Document
    ) -> None:
        block = _block(
            draft_document,
            local_id="C1",
            confirmation=True,
            because_code="irreversible",
            proposal="Push the fix to main",
        )
        session.add(block)
        session.flush()

        assert block.because_code == "irreversible"

    def test_a_confirmation_has_a_reason(
        self, session: DbSession, draft_document: Document
    ) -> None:
        session.add(
            _block(draft_document, confirmation=True, proposal="Push the fix to main")
        )

        assert violated_constraint(session) == "ck_blocks_confirmation"

    def test_a_confirmation_has_a_proposal(
        self, session: DbSession, draft_document: Document
    ) -> None:
        session.add(_block(draft_document, confirmation=True, because_code="rider"))

        assert violated_constraint(session) == "ck_blocks_confirmation"

    def test_a_confirmation_is_a_decision(
        self, session: DbSession, draft_document: Document
    ) -> None:
        session.add(
            _block(
                draft_document,
                kind_code=BlockKind.ACTION,
                confirmation=True,
                because_code="rider",
                proposal="Push the fix to main",
            )
        )

        assert violated_constraint(session) == "ck_blocks_confirmation"

    def test_a_reason_is_a_confirmation_reason(
        self, session: DbSession, draft_document: Document
    ) -> None:
        session.add(_block(draft_document, because_code="hunch"))

        assert violated_constraint(session) == "blocks_because_code_fkey"

    def test_a_deferral_names_its_task(
        self, session: DbSession, draft_document: Document
    ) -> None:
        block = _block(draft_document, answer="deferred", deferred_to_task_id="fix")
        session.add(block)
        session.flush()

        assert block.deferred_to_task_id == "fix"

    def test_a_task_is_named_only_by_a_deferral(
        self, session: DbSession, draft_document: Document
    ) -> None:
        session.add(_block(draft_document, answer="Blue", deferred_to_task_id="fix"))

        assert violated_constraint(session) == "ck_blocks_deferred_to"


class TestBlockOption:
    def test_options_are_written_in_order(
        self, session: DbSession, draft_document: Document
    ) -> None:
        block = _block(draft_document)
        session.add(block)
        session.flush()
        session.add_all(
            [
                BlockOption(
                    block_id=block.id,
                    position=1,
                    label="Blue",
                    text="matches the logo, about an hour",
                    recommended=True,
                ),
                BlockOption(block_id=block.id, position=2, label="Green"),
            ]
        )
        session.flush()

        rows = session.execute(
            select(BlockOption.label, BlockOption.text, BlockOption.recommended)
            .where(BlockOption.block_id == block.id)
            .order_by(BlockOption.position)
        ).all()

        assert rows == [
            ("Blue", "matches the logo, about an hour", True),
            ("Green", None, False),
        ]

    def test_options_go_with_their_block(
        self, session: DbSession, draft_document: Document
    ) -> None:
        block = _block(draft_document)
        session.add(block)
        session.flush()
        session.add(BlockOption(block_id=block.id, position=1, label="Works"))
        session.flush()
        session.delete(block)
        session.flush()

        assert session.scalars(select(BlockOption)).all() == []
