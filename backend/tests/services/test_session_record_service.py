"""A Session's records: the one read function and the writer (design 2 §10,
§11.4)."""

import ast
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

import app as app_package
from app import models
from app.database import scoped_session
from app.exceptions import RecordNotFoundException
from app.models import Environment, Project, SessionRecord, Turn, User
from app.models.reference import RecordKind, SessionState, UserKind
from app.services.container import ServiceContainer
from app.services.session_record_service import (
    RECORDS_WRITTEN_TOTAL,
    SessionRecordService,
    StreamPosition,
    last_record,
    read_records,
    stream_position,
)
from app.utils import after_commit as after_commit_module
from app.utils.after_commit import clear_after_commit_callbacks
from tests.support.supervisor import metric_value

APP_DIR = Path(app_package.__file__).parent
MODEL_MODULES = {APP_DIR / "models" / "session.py", APP_DIR / "models" / "__init__.py"}
RECORD_SERVICE = APP_DIR / "services" / "session_record_service.py"


@pytest.fixture(autouse=True)
def _no_callbacks() -> Iterator[None]:
    clear_after_commit_callbacks()
    yield
    clear_after_commit_callbacks()


@pytest.fixture
def records(container: ServiceContainer) -> SessionRecordService:
    return container.session_record_service()


def _turn(db: DbSession, run: models.Session, seq: int, author: User | None) -> Turn:
    turn = Turn(
        session_id=run.id,
        seq=seq,
        author_user_id=None if author is None else author.id,
        message=f"Message {seq}",
        started_at=datetime.now(UTC),
    )
    db.add(turn)
    db.flush()
    return turn


def _server(records: SessionRecordService, run: models.Session, words: str) -> None:
    records.append(run.id, RecordKind.SERVER, payload={"text": words})


def _seqs(stored: list) -> list[int]:
    return [entry.record.seq for entry in stored]


def _line(
    records: SessionRecordService,
    run: models.Session,
    turn: Turn,
    offset: int,
    controller_session: str = "claude-1",
    kind: RecordKind = RecordKind.CLAUDE,
) -> None:
    records.append(
        run.id,
        kind,
        payload={"type": "system", "subtype": "status"},
        turn_id=turn.id,
        raw_offset=offset,
        controller_session=controller_session,
    )


class TestReadRecords:
    def test_it_reads_the_records_after_a_seq_in_order_up_to_a_limit(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        for n in range(5):
            _server(records, project_session, f"Line {n}")

        assert _seqs(read_records(session, project_session.id, after=1, limit=3)) == [
            2,
            3,
            4,
        ]
        assert _seqs(read_records(session, project_session.id, limit=10)) == [
            1,
            2,
            3,
            4,
            5,
        ]
        assert read_records(session, project_session.id, after=5, limit=10) == []

    def test_it_reads_newest_first(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        for n in range(3):
            _server(records, project_session, f"Line {n}")

        assert _seqs(
            read_records(session, project_session.id, limit=2, newest_first=True)
        ) == [3, 2]

    def test_it_reads_before_a_seq(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        for n in range(5):
            _server(records, project_session, f"Line {n}")

        assert _seqs(
            read_records(
                session, project_session.id, before=4, limit=2, newest_first=True
            )
        ) == [3, 2]
        assert _seqs(
            read_records(session, project_session.id, after=1, before=4, limit=10)
        ) == [2, 3]

    def test_it_reads_one_kind_of_record(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        turn = _turn(session, project_session, 1, None)
        _server(records, project_session, "Starting")
        _line(records, project_session, turn, 10)
        _line(records, project_session, turn, 20, kind=RecordKind.RESULT)
        _line(records, project_session, turn, 30)

        assert _seqs(
            read_records(session, project_session.id, kind=RecordKind.CLAUDE, limit=10)
        ) == [2, 4]
        assert _seqs(
            read_records(
                session,
                project_session.id,
                kind=RecordKind.RESULT,
                limit=1,
                newest_first=True,
            )
        ) == [3]

    def test_it_reads_one_sessions_records_only(
        self,
        session: DbSession,
        records: SessionRecordService,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        other = models.Session(
            project_id=project.id,
            environment_id=environment.id,
            kind_code="work",
            cwd="/work/Example",
            token_hash="2" * 64,
            state_code=SessionState.RUNNING,
        )
        session.add(other)
        session.flush()
        _server(records, project_session, "Mine")
        _server(records, other, "Theirs")
        _server(records, project_session, "Mine again")

        mine = read_records(session, project_session.id, limit=10)

        assert [entry.record.payload["text"] for entry in mine] == [
            "Mine",
            "Mine again",
        ]
        assert _seqs(read_records(session, other.id, limit=10)) == [1]

    def test_it_reads_the_turns_number_and_a_sends_author_and_words(
        self,
        session: DbSession,
        records: SessionRecordService,
        person: User,
        project_session: models.Session,
    ) -> None:
        _server(records, project_session, "Starting")
        _turn(session, project_session, 1, author=None)
        turn = _turn(session, project_session, 2, author=person)
        records.append(project_session.id, RecordKind.SEND, turn_id=turn.id)
        records.append(
            project_session.id,
            RecordKind.CLAUDE,
            payload={"type": "assistant"},
            turn_id=turn.id,
            raw_offset=120,
            controller_session="pilot-1",
        )

        server, send, claude = read_records(session, project_session.id, limit=10)

        assert (server.turn, server.author, server.message) == (None, None, None)
        assert (send.turn, send.author, send.message) == (2, "ada", "Message 2")
        assert (claude.turn, claude.author, claude.message) == (2, None, None)
        assert claude.record.raw_offset == 120
        assert claude.record.controller_session == "pilot-1"

    def test_the_last_record_is_none_before_the_first(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        assert last_record(session, project_session.id) is None

        _server(records, project_session, "First")
        _server(records, project_session, "Second")

        last = last_record(session, project_session.id)
        assert last is not None
        assert last.record.seq == 2
        assert last.record.payload == {"text": "Second"}


class TestStreamPosition:
    def test_none_before_the_first_line(
        self,
        session: DbSession,
        records: SessionRecordService,
        person: User,
        project_session: models.Session,
    ) -> None:
        assert stream_position(session, project_session.id) is None

        turn = _turn(session, project_session, 1, author=person)
        records.append(project_session.id, RecordKind.SEND, turn_id=turn.id)
        _server(records, project_session, "Starting Example-1…")

        assert stream_position(session, project_session.id) is None

    def test_the_last_line_or_result_past_the_records_after_it(
        self,
        session: DbSession,
        records: SessionRecordService,
        person: User,
        project_session: models.Session,
    ) -> None:
        first = _turn(session, project_session, 1, author=None)
        _line(records, project_session, first, 120)
        _line(records, project_session, first, 300, kind=RecordKind.RESULT)
        second = _turn(session, project_session, 2, author=person)
        records.append(project_session.id, RecordKind.SEND, turn_id=second.id)
        # More than a page of the search's.
        for n in range(40):
            _server(records, project_session, f"Effect {n}")

        assert stream_position(session, project_session.id) == StreamPosition(
            "claude-1", 300
        )

    def test_a_new_controller_session_moves_it(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        turn = _turn(session, project_session, 1, author=None)
        _line(records, project_session, turn, 900)
        _line(records, project_session, turn, 80, controller_session="claude-2")

        assert stream_position(session, project_session.id) == StreamPosition(
            "claude-2", 80
        )


def _docstrings(tree: ast.Module) -> set[ast.AST]:
    found: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
            ):
                found.add(body[0].value)
    return found


def _annotations(tree: ast.Module) -> set[ast.AST]:
    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.returns is not None:
                roots.append(node.returns)
        elif isinstance(node, ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
    return {inner for root in roots for inner in ast.walk(root)}


def _inside(tree: ast.Module, function: str) -> set[ast.AST]:
    return {
        inner
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function
        for inner in ast.walk(node)
    }


def _constructors(tree: ast.Module) -> set[ast.AST]:
    return {
        node.func
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SessionRecord"
    }


def _uses(path: Path) -> list[tuple[ast.AST, ast.Module]]:
    """Every node of the module that names the table outside a docstring, and
    the module: the model by its name, by a name an import gives it, or as an
    attribute (`models.SessionRecord`), and the table by its name in a string."""
    tree = ast.parse(path.read_text(), filename=str(path))
    docstrings = _docstrings(tree)
    names = {"SessionRecord"} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "SessionRecord" and alias.asname is not None
    }
    return [
        (node, tree)
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id in names)
        or (isinstance(node, ast.Attribute) and node.attr == "SessionRecord")
        or (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "session_records" in node.value
            and node not in docstrings
        )
    ]


class TestTheOneRead:
    """`read_records` is the only query of `session_records` in the server
    (design 2 §11.4), and the writer the only code that adds a record (§10)."""

    def _server_modules(self) -> list[Path]:
        return [
            path for path in sorted(APP_DIR.rglob("*.py")) if path not in MODEL_MODULES
        ]

    def test_no_code_but_the_read_function_queries_the_table(self) -> None:
        offenders = []
        for path in self._server_modules():
            for node, tree in _uses(path):
                allowed = _annotations(tree) | _constructors(tree)
                if path == RECORD_SERVICE:
                    allowed |= _inside(tree, "read_records")
                if node not in allowed:
                    offenders.append(f"{path.relative_to(APP_DIR)}:{node.lineno}")
        assert offenders == []

    def test_no_code_but_the_writer_adds_a_record(self) -> None:
        constructing = [
            path
            for path in self._server_modules()
            if _constructors(ast.parse(path.read_text()))
        ]
        assert constructing == [RECORD_SERVICE]
        tree = ast.parse(RECORD_SERVICE.read_text())
        assert _constructors(tree) <= _inside(tree, "append")

    def test_it_sees_a_query_elsewhere(self, tmp_path: Path) -> None:
        stray = tmp_path / "stray.py"
        stray.write_text(
            "from app import models\n"
            "from app.models import SessionRecord\n"
            "from app.models import SessionRecord as Records\n"
            "def count(db):\n"
            "    return db.query(SessionRecord).count()\n"
            "def count_by_attribute(db):\n"
            "    return db.query(models.SessionRecord).count()\n"
            "def count_by_alias(db):\n"
            "    return db.query(Records).count()\n"
            "RAW = 'SELECT seq FROM session_records'\n"
        )

        assert sorted(getattr(node, "lineno", 0) for node, _ in _uses(stray)) == [
            5,
            7,
            9,
            10,
        ]


class TestAppend:
    def test_it_numbers_the_records_from_one_without_a_gap(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        written = [
            records.append(project_session.id, RecordKind.SERVER, payload={"n": n})
            for n in range(3)
        ]

        assert [record.seq for record in written] == [1, 2, 3]
        assert all(record.at is not None for record in written)
        assert _seqs(read_records(session, project_session.id, limit=10)) == [1, 2, 3]

    def test_it_writes_what_the_caller_gives(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        turn = _turn(session, project_session, 1, author=None)

        record = records.append(
            project_session.id,
            RecordKind.RESULT,
            payload={"turn": 1, "isError": False},
            turn_id=turn.id,
            raw_offset=640,
            controller_session="pilot-1",
        )

        stored = session.execute(
            select(SessionRecord).where(SessionRecord.id == record.id)
        ).scalar_one()
        assert stored.kind_code == RecordKind.RESULT
        assert stored.payload == {"turn": 1, "isError": False}
        assert (stored.turn_id, stored.raw_offset, stored.controller_session) == (
            turn.id,
            640,
            "pilot-1",
        )

    def test_it_refuses_an_unknown_session(self, records: SessionRecordService) -> None:
        with pytest.raises(RecordNotFoundException):
            records.append(uuid.uuid4(), RecordKind.SERVER, payload={"text": "Lost"})

    def test_each_record_is_counted_by_its_kind(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        before = {
            kind: metric_value(RECORDS_WRITTEN_TOTAL, kind=kind.value)
            for kind in (RecordKind.SERVER, RecordKind.CLAUDE)
        }
        turn = _turn(session, project_session, 1, author=None)

        _server(records, project_session, "One")
        _server(records, project_session, "Two")
        _line(records, project_session, turn, 120)

        assert metric_value(RECORDS_WRITTEN_TOTAL, kind="server") == (
            before[RecordKind.SERVER] + 2
        )
        assert metric_value(RECORDS_WRITTEN_TOTAL, kind="claude") == (
            before[RecordKind.CLAUDE] + 1
        )

    def test_the_records_of_one_transaction_share_one_wake(
        self, records: SessionRecordService, project_session: models.Session
    ) -> None:
        _server(records, project_session, "One")
        _server(records, project_session, "Two")

        assert len(after_commit_module._callbacks.get()) == 1

    def test_concurrent_writers_number_without_a_gap(
        self, committed_app: Flask
    ) -> None:
        container = committed_app.container
        with scoped_session(container) as db:
            person = User(
                kind_code=UserKind.PERSON,
                subject="subject-ada",
                handle="ada",
                name="Ada Example",
                avatar_slot=1,
            )
            db.add(person)
            db.flush()
            project = Project(created_by_user_id=person.id)
            db.add_all(
                [
                    project,
                    Environment(id="example-env-1", name="Example-1", exempt=False),
                ]
            )
            db.flush()
            run = models.Session(
                project_id=project.id,
                environment_id="example-env-1",
                kind_code="work",
                cwd="/work/Example",
                token_hash="1" * 64,
                state_code=SessionState.RUNNING,
            )
            db.add(run)
            db.flush()
            session_id = run.id

        writers, each = 4, 10
        failures: list[BaseException] = []
        start = threading.Barrier(writers)

        def write(writer: int) -> None:
            try:
                start.wait()
                for n in range(each):
                    with scoped_session(container):
                        container.session_record_service().append(
                            session_id,
                            RecordKind.SERVER,
                            payload={"writer": writer, "n": n},
                        )
            except BaseException as error:
                failures.append(error)

        threads = [threading.Thread(target=write, args=(w,)) for w in range(writers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert failures == []
        with scoped_session(container) as db:
            stored = read_records(db, session_id, limit=100)
        assert _seqs(stored) == list(range(1, writers * each + 1))
        for writer in range(writers):
            mine = [
                e.record.payload["n"]
                for e in stored
                if e.record.payload["writer"] == writer
            ]
            assert mine == list(range(each))


class TestLockSession:
    def test_it_reads_the_row_afresh(
        self,
        session: DbSession,
        records: SessionRecordService,
        project_session: models.Session,
    ) -> None:
        session.execute(
            models.Session.__table__.update()
            .where(models.Session.__table__.c.id == project_session.id)
            .values(state_code=SessionState.IDLE)
        )

        assert records.lock_session(project_session.id).state_code == SessionState.IDLE

    def test_it_refuses_an_unknown_session(self, records: SessionRecordService) -> None:
        with pytest.raises(RecordNotFoundException):
            records.lock_session(uuid.uuid4())


class TestRequireSession:
    def test_it_finds_the_session(
        self, records: SessionRecordService, project_session: models.Session
    ) -> None:
        assert records.require_session(project_session.id) is project_session

    def test_it_refuses_an_unknown_session(self, records: SessionRecordService) -> None:
        with pytest.raises(RecordNotFoundException):
            records.require_session(uuid.uuid4())


class TestReadPage:
    @pytest.fixture
    def five(
        self, records: SessionRecordService, project_session: models.Session
    ) -> models.Session:
        for n in range(5):
            _server(records, project_session, f"Line {n}")
        return project_session

    def test_it_pages_after_a_seq(
        self, records: SessionRecordService, five: models.Session
    ) -> None:
        page = records.read_page(five.id, after=1, limit=2)

        assert _seqs(page.records) == [2, 3]
        assert page.ended is False

    @pytest.mark.parametrize("state", [SessionState.ENDED, SessionState.FAILED])
    def test_a_page_with_the_last_record_of_a_stream_that_ended_ends(
        self,
        session: DbSession,
        records: SessionRecordService,
        five: models.Session,
        state: SessionState,
    ) -> None:
        five.state_code = state
        session.flush()

        assert records.read_page(five.id, after=3, limit=2).ended is True
        assert records.read_page(five.id, after=5, limit=2).ended is True
        assert records.read_page(five.id, after=2, limit=2).ended is False

    @pytest.mark.parametrize(
        "state",
        [
            SessionState.STARTING,
            SessionState.RUNNING,
            SessionState.IDLE,
            SessionState.STOPPED,
        ],
    )
    def test_a_stream_that_continues_does_not_end(
        self,
        session: DbSession,
        records: SessionRecordService,
        five: models.Session,
        state: SessionState,
    ) -> None:
        five.state_code = state
        session.flush()

        assert records.read_page(five.id, after=0, limit=10).ended is False

    def test_it_refuses_an_unknown_session(self, records: SessionRecordService) -> None:
        with pytest.raises(RecordNotFoundException):
            records.read_page(uuid.uuid4(), after=0, limit=10)
