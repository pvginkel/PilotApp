"""Session, Turn, Session Record, Effect and Writer Question: what a row must
hold."""

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.models import (
    Attachment,
    Block,
    Document,
    Effect,
    Environment,
    Item,
    Project,
    Session,
    SessionRecord,
    Turn,
    User,
    WriterQuestion,
)
from app.models.reference import (
    AttachmentSource,
    BlockKind,
    EffectKind,
    RecordKind,
    SessionState,
)
from tests.support.database import violated_constraint

SENT_AT = datetime(2026, 10, 19, 9, 30, tzinfo=UTC)

ASSISTANT_LINE = {
    "type": "assistant",
    "message": {"content": [{"type": "text", "text": "Reading the client."}]},
    "parent_tool_use_id": None,
}


def _session(
    project: Project, environment: Environment, **overrides: object
) -> Session:
    values: dict[str, object] = {
        "project_id": project.id,
        "environment_id": environment.id,
        "kind_code": "work",
        "cwd": "/work/Example",
        "token_hash": "0" * 64,
        "state_code": SessionState.STARTING,
    }
    values.update(overrides)
    return Session(**values)


def _turn(run: Session, **overrides: object) -> Turn:
    values: dict[str, object] = {
        "session_id": run.id,
        "seq": 1,
        "message": "Fix the client for v4.",
        "started_at": SENT_AT,
    }
    values.update(overrides)
    return Turn(**values)


def _record(run: Session, **overrides: object) -> SessionRecord:
    values: dict[str, object] = {
        "session_id": run.id,
        "seq": 1,
        "kind_code": RecordKind.SERVER,
        "payload": {"text": "Starting Example-1…"},
    }
    values.update(overrides)
    return SessionRecord(**values)


def _block(document: Document) -> Block:
    return Block(
        document_id=document.id,
        local_id="D1",
        position=1,
        kind_code=BlockKind.DECISION,
    )


@pytest.fixture
def turn(session: DbSession, project_session: Session) -> Turn:
    """The first Turn of ``project_session``, the server's brief."""
    brief = _turn(project_session)
    session.add(brief)
    session.flush()
    return brief


class TestSession:
    def test_a_session_is_written(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        run = _session(project, environment)
        session.add(run)
        session.flush()
        session.refresh(run)

        assert run.turns == 0
        assert run.created_at is not None
        assert run.current_line is None

    def test_a_start_the_gate_holds_is_held(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        run = _session(project, environment, state_code=SessionState.HELD)
        session.add(run)
        session.flush()
        session.expire(run)

        assert run.state_code == SessionState.HELD

    def test_a_held_start_has_no_environment_yet(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        run = _session(
            project, environment, environment_id=None, state_code=SessionState.HELD
        )
        session.add(run)
        session.flush()
        session.expire(run)

        assert run.environment_id is None

    def test_its_kind_is_a_session_kind(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        session.add(_session(project, environment, kind_code="other"))

        assert violated_constraint(session) == "sessions_kind_code_fkey"

    def test_a_token_names_one_session(
        self, session: DbSession, project: Project, environment: Environment
    ) -> None:
        session.add_all([_session(project, environment) for _ in range(2)])

        assert violated_constraint(session) == "uq_sessions_token_hash"

    def test_the_current_line_is_one_jsonb_value(
        self, session: DbSession, project_session: Session
    ) -> None:
        line = {
            "state": "working",
            "since": "2026-10-19T09:31:00Z",
            "step": {"tool": "Read", "input": {"file_path": "client.py"}},
        }
        project_session.current_line = line
        session.flush()
        session.expire(project_session)

        assert project_session.current_line == line

    def test_no_current_line_is_sql_null(
        self, session: DbSession, project_session: Session
    ) -> None:
        """Null between turns is the column's NULL, not a JSON `null`."""
        project_session.current_line = {"state": "thinking"}
        session.flush()
        project_session.current_line = None
        session.flush()

        assert session.scalar(
            text("SELECT current_line IS NULL FROM sessions WHERE id = :id"),
            {"id": project_session.id},
        )


class TestTurn:
    def test_a_persons_turn_is_written(
        self,
        session: DbSession,
        project_session: Session,
        person: User,
        item: Item,
    ) -> None:
        message = (
            f'<quoted_item id="{item.id}">Which colour for the badge?'
            f'</quoted_item id="{item.id}"> Blue, please.'
        )
        sent = _turn(
            project_session,
            author_user_id=person.id,
            message=message,
            words=message,
            quote_item_id=item.id,
        )
        session.add(sent)
        session.flush()

        assert sent.id is not None
        assert sent.ended_at is None
        assert sent.error is None

    def test_a_persons_words_are_kept_beside_what_was_sent(
        self, session: DbSession, project_session: Session, person: User
    ) -> None:
        """A chat's first Turn sends its brief before the words (DB 251)."""
        words = "Blue, please."
        sent = _turn(
            project_session,
            author_user_id=person.id,
            message=f"The chat's brief.\n\n{words}",
            words=words,
        )
        session.add(sent)
        session.flush()
        session.expire(sent)

        assert (sent.message, sent.words) == (f"The chat's brief.\n\n{words}", words)

    @pytest.mark.parametrize(
        ("authored", "words"),
        [
            pytest.param(True, None, id="a-persons-without-words"),
            pytest.param(False, "Blue, please.", id="the-servers-with-words"),
        ],
    )
    def test_a_turn_has_words_exactly_when_a_person_wrote_it(
        self,
        session: DbSession,
        project_session: Session,
        person: User,
        authored: bool,
        words: str | None,
    ) -> None:
        session.add(
            _turn(
                project_session,
                author_user_id=person.id if authored else None,
                words=words,
            )
        )

        assert violated_constraint(session) == "ck_turns_words"

    def test_the_servers_own_turn_quotes_nothing(
        self, session: DbSession, project_session: Session, item: Item
    ) -> None:
        """A quote is read from a person's words (DB 159, 251)."""
        session.add(_turn(project_session, quote_item_id=item.id))

        assert violated_constraint(session) == "ck_turns_words"

    def test_a_seq_is_one_turn_of_its_session(
        self, session: DbSession, project_session: Session, turn: Turn
    ) -> None:
        session.add(_turn(project_session))

        assert violated_constraint(session) == "turns_session_id_seq_key"

    def test_seq_counts_from_one(
        self, session: DbSession, project_session: Session
    ) -> None:
        session.add(_turn(project_session, seq=0))

        assert violated_constraint(session) == "ck_turns_seq"

    def test_it_quotes_an_item_or_a_block_never_both(
        self,
        session: DbSession,
        project_session: Session,
        person: User,
        item: Item,
        draft_document: Document,
    ) -> None:
        block = _block(draft_document)
        session.add(block)
        session.flush()
        session.add(
            _turn(
                project_session,
                author_user_id=person.id,
                words="Fix the client for v4.",
                quote_item_id=item.id,
                quote_block_id=block.id,
            )
        )

        assert violated_constraint(session) == "ck_turns_quote"

    def test_a_removed_draft_block_leaves_the_turn_quoting_none(
        self,
        session: DbSession,
        project_session: Session,
        person: User,
        draft_document: Document,
    ) -> None:
        block = _block(draft_document)
        session.add(block)
        session.flush()
        quoting = _turn(
            project_session,
            author_user_id=person.id,
            words="Fix the client for v4.",
            quote_block_id=block.id,
        )
        session.add(quoting)
        session.flush()

        session.delete(block)
        session.flush()
        session.expire(quoting)

        assert quoting.quote_block_id is None
        assert quoting.words == "Fix the client for v4."


class TestSessionRecord:
    def test_a_line_of_the_stream_is_written(
        self, session: DbSession, project_session: Session, turn: Turn
    ) -> None:
        record = _record(
            project_session,
            turn_id=turn.id,
            kind_code=RecordKind.CLAUDE,
            payload=ASSISTANT_LINE,
            raw_offset=4096,
            controller_session="example-env-1-headless-1",
        )
        session.add(record)
        session.flush()
        session.refresh(record)

        assert record.payload == ASSISTANT_LINE
        assert record.at is not None

    def test_the_workers_result_frame_is_written(
        self, session: DbSession, project_session: Session, turn: Turn
    ) -> None:
        frame = {"turn": 1, "result": "Done.", "isError": False, "interrupted": False}
        session.add(
            _record(
                project_session,
                turn_id=turn.id,
                kind_code=RecordKind.RESULT,
                payload=frame,
                raw_offset=8192,
                controller_session="example-env-1-headless-1",
            )
        )
        session.flush()

        assert session.scalars(select(SessionRecord.payload)).one() == frame

    def test_a_line_that_is_not_json_is_kept_as_printed(
        self, session: DbSession, project_session: Session, turn: Turn
    ) -> None:
        session.add(
            _record(
                project_session,
                turn_id=turn.id,
                kind_code=RecordKind.CLAUDE,
                payload="warning: not a JSON line",
                raw_offset=25,
                controller_session="example-env-1-headless-1",
            )
        )
        session.flush()

        assert (
            session.scalars(select(SessionRecord.payload)).one()
            == "warning: not a JSON line"
        )

    def test_a_server_record_may_fall_outside_any_turn(
        self, session: DbSession, project_session: Session
    ) -> None:
        record = _record(project_session)
        session.add(record)
        session.flush()

        assert record.turn_id is None

    def test_a_seq_is_one_record_of_its_session(
        self, session: DbSession, project_session: Session
    ) -> None:
        session.add_all([_record(project_session), _record(project_session)])

        assert violated_constraint(session) == "session_records_session_id_seq_key"

    def test_seq_counts_from_one(
        self, session: DbSession, project_session: Session
    ) -> None:
        session.add(_record(project_session, seq=0))

        assert violated_constraint(session) == "ck_session_records_seq"

    def test_its_turn_is_of_its_own_session(
        self,
        session: DbSession,
        project: Project,
        environment: Environment,
        turn: Turn,
    ) -> None:
        other = _session(project, environment)
        session.add(other)
        session.flush()
        session.add(_record(other, turn_id=turn.id))

        assert violated_constraint(session) == "session_records_session_id_turn_id_fkey"

    @pytest.mark.parametrize(
        ("kind", "in_turn", "raw_offset", "controller_session"),
        [
            pytest.param(
                RecordKind.CLAUDE, True, None, "headless-1", id="claude-no-offset"
            ),
            pytest.param(RecordKind.CLAUDE, True, 25, None, id="claude-no-controller"),
            pytest.param(
                RecordKind.CLAUDE, False, 25, "headless-1", id="claude-no-turn"
            ),
            pytest.param(
                RecordKind.RESULT, True, None, "headless-1", id="result-no-offset"
            ),
            pytest.param(
                RecordKind.RESULT, False, 25, "headless-1", id="result-no-turn"
            ),
            pytest.param(RecordKind.SERVER, False, 25, None, id="server-with-offset"),
            pytest.param(
                RecordKind.SERVER,
                False,
                None,
                "headless-1",
                id="server-with-controller",
            ),
        ],
    )
    def test_only_a_line_of_the_stream_carries_its_place_in_the_raw_file(
        self,
        session: DbSession,
        project_session: Session,
        turn: Turn,
        kind: RecordKind,
        in_turn: bool,
        raw_offset: int | None,
        controller_session: str | None,
    ) -> None:
        session.add(
            _record(
                project_session,
                kind_code=kind,
                turn_id=turn.id if in_turn else None,
                payload=ASSISTANT_LINE,
                raw_offset=raw_offset,
                controller_session=controller_session,
            )
        )

        assert violated_constraint(session) == "ck_session_records_stream"

    @pytest.mark.parametrize("parent_tool_use_id", [None, "toolu_01"])
    def test_a_partial_line_is_never_stored(
        self,
        session: DbSession,
        project_session: Session,
        turn: Turn,
        parent_tool_use_id: str | None,
    ) -> None:
        """Neither the main thread's partials nor a sub-agent's."""
        partial = {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta"}},
            "parent_tool_use_id": parent_tool_use_id,
        }
        session.add(
            _record(
                project_session,
                turn_id=turn.id,
                kind_code=RecordKind.CLAUDE,
                payload=partial,
                raw_offset=25,
                controller_session="headless-1",
            )
        )

        assert violated_constraint(session) == "ck_session_records_partial"

    def test_a_persons_message_is_placed_by_a_send_without_payload(
        self, session: DbSession, project_session: Session, person: User
    ) -> None:
        sent = _turn(
            project_session,
            author_user_id=person.id,
            message="Go with v4.",
            words="Go with v4.",
        )
        session.add(sent)
        session.flush()
        record = _record(
            project_session, turn_id=sent.id, kind_code=RecordKind.SEND, payload=None
        )
        session.add(record)
        session.flush()

        assert session.scalar(
            text("SELECT payload IS NULL FROM session_records WHERE id = :id"),
            {"id": record.id},
        )

    @pytest.mark.parametrize(
        ("kind", "in_turn", "payload"),
        [
            pytest.param(
                RecordKind.SEND, True, {"text": "Go with v4."}, id="send-with-payload"
            ),
            pytest.param(RecordKind.SEND, False, None, id="send-outside-a-turn"),
            pytest.param(RecordKind.SERVER, False, None, id="server-without-payload"),
        ],
    )
    def test_only_a_send_has_no_payload_and_it_falls_in_its_turn(
        self,
        session: DbSession,
        project_session: Session,
        turn: Turn,
        kind: RecordKind,
        in_turn: bool,
        payload: object,
    ) -> None:
        session.add(
            _record(
                project_session,
                kind_code=kind,
                turn_id=turn.id if in_turn else None,
                payload=payload,
            )
        )

        assert violated_constraint(session) == "ck_session_records_send"

    def test_a_turn_has_one_send(
        self, session: DbSession, project_session: Session, turn: Turn
    ) -> None:
        session.add_all(
            [
                _record(
                    project_session,
                    seq=seq,
                    turn_id=turn.id,
                    kind_code=RecordKind.SEND,
                    payload=None,
                )
                for seq in (1, 2)
            ]
        )

        assert violated_constraint(session) == "uq_session_records_send_turn_id"


@pytest.fixture
def placing(session: DbSession, project_session: Session, turn: Turn) -> SessionRecord:
    """The `server` record of ``turn`` that places a call's Effects."""
    record = _record(
        project_session,
        turn_id=turn.id,
        payload={"type": "effect", "toolUseId": "toolu_01", "effect": {}},
    )
    session.add(record)
    session.flush()
    return record


def _effect(turn: Turn, record: SessionRecord, **overrides: object) -> Effect:
    values: dict[str, object] = {
        "turn_id": turn.id,
        "record_id": record.id,
        "kind_code": EffectKind.FINISHED,
    }
    values.update(overrides)
    return Effect(**values)


def _attachment(
    session: DbSession, project: Project, filename: str = "palette.md"
) -> Attachment:
    content = b"# Palette\n"
    attachment = Attachment(
        project_id=project.id,
        batch=1,
        title="Palette",
        filename=filename,
        content_type="text/markdown",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        source_code=AttachmentSource.DRAFT,
        copied_at=SENT_AT,
    )
    session.add(attachment)
    session.flush()
    return attachment


class TestEffect:
    @pytest.mark.parametrize(
        ("kind", "names"),
        [
            (EffectKind.ADDED, "item"),
            (EffectKind.MARKED, "item"),
            (EffectKind.STOPPED, "item"),
            (EffectKind.REGISTERED, "item"),
            (EffectKind.ANSWERED, "block"),
            (EffectKind.ATTACHED, "attachment"),
            (EffectKind.FINISHED, None),
        ],
    )
    def test_each_kind_names_what_it_changed(
        self,
        session: DbSession,
        project: Project,
        turn: Turn,
        placing: SessionRecord,
        item: Item,
        draft_document: Document,
        kind: EffectKind,
        names: str | None,
    ) -> None:
        block = _block(draft_document)
        session.add(block)
        session.flush()
        named = {
            "item": {"item_id": item.id},
            "block": {"block_id": block.id},
            "attachment": {"attachment_id": _attachment(session, project).id},
            None: {},
        }[names]
        effect = _effect(turn, placing, kind_code=kind, **named)
        session.add(effect)
        session.flush()
        session.refresh(effect)

        assert effect.kind_code == kind
        assert effect.at is not None

    @pytest.mark.parametrize(
        ("kind", "names"),
        [
            pytest.param(EffectKind.ADDED, (), id="added-naming-nothing"),
            pytest.param(EffectKind.REGISTERED, ("block",), id="registered-a-block"),
            pytest.param(
                EffectKind.MARKED, ("item", "attachment"), id="marked-and-attached"
            ),
            pytest.param(EffectKind.ANSWERED, ("item",), id="answered-an-item"),
            pytest.param(EffectKind.ATTACHED, (), id="attached-naming-nothing"),
            pytest.param(EffectKind.ATTACHED, ("item",), id="attached-an-item"),
            pytest.param(EffectKind.FINISHED, ("block",), id="finished-a-block"),
            pytest.param(EffectKind.FINISHED, ("item",), id="finished-an-item"),
        ],
    )
    def test_what_it_names_follows_its_kind(
        self,
        session: DbSession,
        project: Project,
        turn: Turn,
        placing: SessionRecord,
        item: Item,
        draft_document: Document,
        kind: EffectKind,
        names: tuple[str, ...],
    ) -> None:
        """DB assertion 160."""
        block = _block(draft_document)
        session.add(block)
        session.flush()
        named: dict[str, object] = {}
        if "item" in names:
            named["item_id"] = item.id
        if "block" in names:
            named["block_id"] = block.id
        if "attachment" in names:
            named["attachment_id"] = _attachment(session, project).id
        session.add(_effect(turn, placing, kind_code=kind, **named))

        assert violated_constraint(session) == "ck_effects_names"

    def test_one_record_places_every_effect_of_a_call(
        self,
        session: DbSession,
        project: Project,
        turn: Turn,
        placing: SessionRecord,
    ) -> None:
        """A folder attached: an Effect per file, one record (DB 216)."""
        effects = [
            _effect(
                turn,
                placing,
                kind_code=EffectKind.ATTACHED,
                attachment_id=_attachment(session, project, filename).id,
            )
            for filename in ("palette.md", "notes.md")
        ]
        session.add_all(effects)
        session.flush()

        assert {effect.record_id for effect in effects} == {placing.id}

    def test_a_removed_draft_block_leaves_its_answer_s_effect(
        self,
        session: DbSession,
        turn: Turn,
        placing: SessionRecord,
        draft_document: Document,
    ) -> None:
        """The agent removes a draft Block with its answers (F47.4); the
        Effect of the answer stays, its record keeping the line."""
        block = _block(draft_document)
        session.add(block)
        session.flush()
        answered = _effect(
            turn, placing, kind_code=EffectKind.ANSWERED, block_id=block.id
        )
        session.add(answered)
        session.flush()

        session.delete(block)
        session.flush()
        session.expire(answered)

        assert (answered.kind_code, answered.block_id) == (EffectKind.ANSWERED, None)


class TestWriterQuestion:
    def test_a_question_is_written_with_its_stamp(
        self, session: DbSession, turn: Turn, draft_document: Document
    ) -> None:
        block = _block(draft_document)
        session.add(block)
        session.flush()
        question = WriterQuestion(
            turn_id=turn.id,
            block_id=block.id,
            question="Which OpenBao path does 'the key' go to?",
        )
        session.add(question)
        session.flush()
        session.refresh(question)

        assert question.question == "Which OpenBao path does 'the key' go to?"
        assert question.asked_at is not None

    def test_a_block_is_asked_about_once(
        self,
        session: DbSession,
        project_session: Session,
        turn: Turn,
        draft_document: Document,
    ) -> None:
        """One question per Block in version 1 (DB assertion 250), even
        from a later Turn."""
        block = _block(draft_document)
        later = _turn(project_session, seq=2)
        session.add_all([block, later])
        session.flush()
        session.add_all(
            [
                WriterQuestion(turn_id=turn.id, block_id=block.id, question="Which?"),
                WriterQuestion(turn_id=later.id, block_id=block.id, question="And?"),
            ]
        )

        assert violated_constraint(session) == "uq_writer_questions_block_id"
