"""What `pilot-projects` reads that no screen does (F150.5, F150.8): the index
of a project's `timeline.json`, and the tree's files listed, found and read as
text, KubeCoder's fleet adapter's reads one for one."""

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.views import utc_time
from app.exceptions import (
    InvalidOperationException,
    RecordNotFoundException,
    ValidationException,
)
from app.models import Attachment, Item, Project, User
from app.models.reference import AttachmentSource, ProjectState
from app.services.container import ServiceContainer
from app.services.tree_read_service import (
    READ_MAX_BYTES,
    READ_MAX_LINES,
    IndexedItem,
    TreeEntry,
    TreeText,
)


def _keep(
    container: ServiceContainer,
    project: Project,
    batch: int,
    filename: str,
    content: bytes,
) -> None:
    """A copy of the draft in the batch, kept through the store."""
    container.attachment_store().put(
        Attachment(
            project_id=project.id,
            batch=batch,
            title="Palette",
            filename=filename,
            content_type="text/markdown",
            source_code=AttachmentSource.DRAFT,
            copied_at=datetime.now(UTC),
        ),
        content,
    )


@pytest.fixture
def badges(
    session: DbSession,
    container: ServiceContainer,
    project: Project,
    project_session: models.Session,
) -> Project:
    """An open project, `badge-colours`: its draft, its handbook, a notice
    and a decision."""
    documents = container.document_service()
    documents.bear_draft(project, "# Badges\nBlue or green.\n")
    project.slug = "badge-colours"
    project.state_code = ProjectState.OPEN
    documents.bear_handbook(project, "Keep it short.\n")
    documents.bear_item(project, "notice", "The palette", project_session)
    documents.bear_item(project, "decision", "Which colour?", project_session)
    session.flush()
    return project


def _items(session: DbSession, project: Project) -> list[Item]:
    return list(session.query(Item).filter_by(project_id=project.id).order_by(Item.seq))


class TestTreeReadServiceItems:
    def test_the_index_is_a_row_per_item_in_seq_order(
        self,
        session: DbSession,
        container: ServiceContainer,
        badges: Project,
        project_session: models.Session,
        person: User,
    ) -> None:
        container.record_service().place_work(badges, project_session, "Refine it")
        notice, decision, work = _items(session, badges)
        decision.urgent = True
        decision.for_user_id = person.id
        session.flush()

        index = container.tree_read_service().items(badges, True, None)

        assert index == [
            IndexedItem(
                seq=1,
                kind="notice",
                title="The palette",
                path="badge-colours/items/1-the-palette.md",
                created_at=utc_time(notice.created_at),
                done_cause=None,
                for_handle=None,
                urgent=False,
            ),
            IndexedItem(
                seq=2,
                kind="decision",
                title="Which colour?",
                path="badge-colours/items/2-which-colour.md",
                created_at=utc_time(decision.created_at),
                done_cause=None,
                for_handle="ada",
                urgent=True,
            ),
            IndexedItem(
                seq=3,
                kind="work",
                title="Refine it",
                path=None,
                created_at=utc_time(work.created_at),
                done_cause=None,
                for_handle=None,
                urgent=False,
            ),
        ]

    def test_the_open_items_alone_or_every_one(
        self,
        session: DbSession,
        container: ServiceContainer,
        badges: Project,
        person: User,
    ) -> None:
        notice, _ = _items(session, badges)
        notice.done_at = datetime.now(UTC)
        notice.done_cause_code = "marked"
        notice.done_by_user_id = person.id
        session.flush()
        read = container.tree_read_service()

        assert [item.seq for item in read.items(badges, True, None)] == [2]
        assert [
            (item.seq, item.done_cause) for item in read.items(badges, False, None)
        ] == [(1, "marked"), (2, None)]

    def test_a_kind_lists_its_items_alone(
        self, container: ServiceContainer, badges: Project
    ) -> None:
        read = container.tree_read_service()

        assert [item.seq for item in read.items(badges, True, "decision")] == [2]
        assert read.items(badges, True, "question") == []

    def test_a_path_runs_from_a_drafts_folder_while_it_is_a_draft(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        container.document_service().bear_item(
            project, "notice", "The palette", project_session
        )

        [item] = container.tree_read_service().items(project, True, None)

        assert item.path == f"draft-{project.number}/items/1-the-palette.md"

    def test_a_registered_document_without_its_text_has_no_path(
        self,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        container.document_service().register(
            project, project_session, "/work/Example/refinement.md"
        )

        [item] = container.tree_read_service().items(project, True, None)

        assert (item.kind, item.path) == ("review", None)

    def test_an_archived_projects_index_is_read(
        self, session: DbSession, container: ServiceContainer, badges: Project
    ) -> None:
        badges.archived = True
        session.flush()

        index = container.tree_read_service().items(badges, True, None)

        assert [item.seq for item in index] == [1, 2]

    def test_another_projects_items_are_not_in_the_index(
        self, session: DbSession, container: ServiceContainer, badges: Project
    ) -> None:
        other = Project(created_by_user_id=badges.created_by_user_id)
        session.add(other)
        session.flush()

        assert container.tree_read_service().items(other, False, None) == []


@pytest.fixture
def filed(session: DbSession, container: ServiceContainer, badges: Project) -> str:
    """`badge-colours` with attachments in a batch, two files and one in
    folders, beside a draft and an archived project; the draft's folder."""
    _keep(container, badges, 1, "Zebra.md", b"# Zebra\n")
    _keep(container, badges, 1, "apple.md", b"# Apple\n")
    _keep(container, badges, 1, "survey/colours/palette.md", b"# Palette\n")
    draft = Project(created_by_user_id=badges.created_by_user_id)
    archived = Project(created_by_user_id=badges.created_by_user_id)
    session.add_all([draft, archived])
    session.flush()
    container.document_service().bear_draft(draft, "# Bikes\n")
    container.document_service().bear_draft(archived, "# Old\n")
    archived.slug = "old-camp"
    archived.state_code = ProjectState.OPEN
    archived.archived = True
    session.flush()
    return f"draft-{draft.number}"


@pytest.mark.usefixtures("filed")
class TestTreeReadServiceEntries:
    @pytest.mark.parametrize("path", ["", ".", "./", "badge-colours/.."])
    def test_the_root_holds_the_reference_and_every_syncing_folder(
        self, container: ServiceContainer, filed: str, path: str
    ) -> None:
        assert container.tree_read_service().entries(path) == [
            TreeEntry("badge-colours/", True),
            TreeEntry(f"{filed}/", True),
            TreeEntry("reference.json", False),
        ]

    @pytest.mark.parametrize(
        "path",
        [
            "badge-colours",
            "badge-colours/",
            "badge-colours//",
            "./badge-colours/items/..",
        ],
    )
    def test_a_folder_lists_its_directories_then_its_files(
        self, container: ServiceContainer, path: str
    ) -> None:
        assert container.tree_read_service().entries(path) == [
            TreeEntry("badge-colours/attachments/", True),
            TreeEntry("badge-colours/items/", True),
            TreeEntry("badge-colours/chat.md", False),
            TreeEntry("badge-colours/handbook.md", False),
            TreeEntry("badge-colours/plan.json", False),
            TreeEntry("badge-colours/project.md", False),
            TreeEntry("badge-colours/timeline.json", False),
        ]

    def test_each_group_is_in_case_insensitive_name_order(
        self, container: ServiceContainer
    ) -> None:
        read = container.tree_read_service()

        assert read.entries("badge-colours/attachments") == [
            TreeEntry("badge-colours/attachments/1/", True)
        ]
        assert read.entries("badge-colours/attachments/1") == [
            TreeEntry("badge-colours/attachments/1/survey/", True),
            TreeEntry("badge-colours/attachments/1/apple.md", False),
            TreeEntry("badge-colours/attachments/1/Zebra.md", False),
        ]
        assert read.entries("badge-colours/attachments/1/survey/") == [
            TreeEntry("badge-colours/attachments/1/survey/colours/", True)
        ]

    def test_a_listed_path_is_one_the_reads_take(
        self, container: ServiceContainer
    ) -> None:
        read = container.tree_read_service()

        [items, *_] = [
            entry for entry in read.entries("badge-colours") if "items" in entry.path
        ]
        [first, second] = read.entries(items.path)

        assert (first, second) == (
            TreeEntry("badge-colours/items/1-the-palette.md", False),
            TreeEntry("badge-colours/items/2-which-colour.md", False),
        )
        assert read.text(first.path, None, None, None).total_count == 3

    def test_a_files_path_is_not_a_directory(self, container: ServiceContainer) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.tree_read_service().entries("badge-colours/project.md")

        assert raised.value.message == (
            "Cannot list 'badge-colours/project.md' because it is a file, not a"
            " folder [not-a-directory]"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "nowhere",
            "badge-colours/notes",
            "badge-colours/item",
            "badge-colours/project.md/x",
            pytest.param("old-camp", id="an-archived-projects-folder"),
            pytest.param("draft-{number}", id="an-opened-projects-draft-folder"),
        ],
    )
    def test_nothing_at_the_path_is_not_found(
        self, container: ServiceContainer, badges: Project, path: str
    ) -> None:
        path = path.format(number=badges.number)

        with pytest.raises(RecordNotFoundException) as raised:
            container.tree_read_service().entries(path)

        assert raised.value.message == f"Folder '{path}' was not found"

    @pytest.mark.parametrize(
        "path", ["/", "/badge-colours", "..", "badge-colours/../..", "./../x"]
    )
    def test_a_path_that_leaves_the_tree_is_refused(
        self, container: ServiceContainer, path: str
    ) -> None:
        with pytest.raises(ValidationException) as raised:
            container.tree_read_service().entries(path)

        assert raised.value.message == (
            f"Path '{path}' is outside the projects' files: a path runs from their"
            " root, as `<folder>/timeline.json` does, never from `/` and never"
            " above it [path-outside-projects]"
        )


@pytest.mark.usefixtures("filed")
class TestTreeReadServiceMatches:
    @pytest.mark.parametrize(
        ("pattern", "paths"),
        [
            ("**/project.md", ["badge-colours/project.md", "DRAFT/project.md"]),
            ("*.json", ["reference.json"]),
            (
                "badge-colours/items/*.md",
                [
                    "badge-colours/items/1-the-palette.md",
                    "badge-colours/items/2-which-colour.md",
                ],
            ),
            (
                "badge-colours/**/*.md",
                [
                    "badge-colours/attachments/1/Zebra.md",
                    "badge-colours/attachments/1/apple.md",
                    "badge-colours/attachments/1/survey/colours/palette.md",
                    "badge-colours/chat.md",
                    "badge-colours/handbook.md",
                    "badge-colours/items/1-the-palette.md",
                    "badge-colours/items/2-which-colour.md",
                    "badge-colours/project.md",
                ],
            ),
            (
                "DRAFT/{plan.json,timeline.json}",
                ["DRAFT/plan.json", "DRAFT/timeline.json"],
            ),
            ("draft-*/p???.json", ["DRAFT/plan.json"]),
            pytest.param("old-camp/**", [], id="an-archived-projects-files"),
            pytest.param("badge-colours/items", [], id="a-directory-is-no-file"),
            pytest.param("../**", [], id="no-path-climbs"),
        ],
    )
    def test_the_files_a_glob_matches_in_path_order(
        self, container: ServiceContainer, filed: str, pattern: str, paths: list[str]
    ) -> None:
        found = container.tree_read_service().matches(pattern.replace("DRAFT", filed))

        assert found == [path.replace("DRAFT", filed) for path in paths]

    def test_glob_syntax_that_is_not_supported_is_refused_by_name(
        self, container: ServiceContainer
    ) -> None:
        with pytest.raises(ValidationException) as raised:
            container.tree_read_service().matches("badge-colours/items/[12]-*.md")

        assert raised.value.message == (
            "Invalid glob pattern: character class '[' at index 20 is not supported"
            " (supported: *, **, ?, {a,b}) [validation-error]"
        )

    def test_a_pattern_from_the_filesystems_root_is_refused(
        self, container: ServiceContainer
    ) -> None:
        with pytest.raises(ValidationException) as raised:
            container.tree_read_service().matches("/work/**/*.md")

        assert raised.value.message == (
            "Pattern '/work/**/*.md' is outside the projects' files: a path runs"
            " from their root, as `<folder>/timeline.json` does, never from `/`"
            " and never above it [path-outside-projects]"
        )


def _numbered(first: int, last: int, line: str = "line {n}") -> str:
    return "".join(f"{n}: {line.format(n=n)}\n" for n in range(first, last + 1))


@pytest.mark.usefixtures("badges")
class TestTreeReadServiceText:
    def test_a_file_is_read_whole_with_its_lines_numbered(
        self, container: ServiceContainer
    ) -> None:
        text = container.tree_read_service().text(
            "badge-colours/project.md", None, None, None
        )

        assert text == TreeText(
            content="1: # Badges\n2: Blue or green.\n",
            sha256=hashlib.sha256(b"# Badges\nBlue or green.\n").hexdigest(),
            total_count=2,
            limit_hit=False,
            line_cut=False,
        )

    def test_a_view_is_read_as_it_is_rendered(
        self, container: ServiceContainer, badges: Project
    ) -> None:
        rendering = container.view_service().timeline(badges)

        text = container.tree_read_service().text(
            "./badge-colours//timeline.json", None, None, None
        )

        assert text.sha256 == rendering.hash
        assert text.total_count == rendering.text.count("\n")
        assert text.content.startswith('1: {\n2:   "readonly": ')

    def test_the_reference_is_read_at_the_root(
        self, container: ServiceContainer
    ) -> None:
        text = container.tree_read_service().text("reference.json", None, None, None)

        assert text.sha256 == container.view_service().reference().hash

    def test_a_last_line_without_its_newline_is_a_line(
        self, container: ServiceContainer, badges: Project
    ) -> None:
        _keep(container, badges, 1, "notes.txt", b"one\n\ntwo")

        text = container.tree_read_service().text(
            "badge-colours/attachments/1/notes.txt", None, None, None
        )

        assert (text.content, text.total_count) == ("1: one\n2: \n3: two\n", 3)

    def test_an_empty_file_has_no_line(
        self, container: ServiceContainer, badges: Project
    ) -> None:
        _keep(container, badges, 1, "empty.txt", b"")
        read = container.tree_read_service()
        path = "badge-colours/attachments/1/empty.txt"

        assert read.text(path, None, None, None) == TreeText(
            "", hashlib.sha256(b"").hexdigest(), 0, False, False
        )
        assert read.text(path, None, None, 5).content == ""
        assert read.text(path, 1, 5, None).content == ""

    @pytest.mark.parametrize(
        ("start", "end", "content"),
        [
            (2, 4, _numbered(2, 4)),
            (9, None, _numbered(9, 10)),
            (None, 2, _numbered(1, 2)),
            pytest.param(8, 50, _numbered(8, 10), id="an-end-past-the-file"),
            pytest.param(11, None, "", id="a-start-past-the-file"),
            pytest.param(5, 3, "", id="an-end-before-its-start"),
        ],
    )
    def test_a_range_is_its_lines_under_the_files_numbers(
        self,
        container: ServiceContainer,
        badges: Project,
        start: int | None,
        end: int | None,
        content: str,
    ) -> None:
        raw = "".join(f"line {n}\n" for n in range(1, 11)).encode()
        _keep(container, badges, 1, "ten.txt", raw)

        text = container.tree_read_service().text(
            "badge-colours/attachments/1/ten.txt", start, end, None
        )

        assert text == TreeText(
            content, hashlib.sha256(raw).hexdigest(), 10, False, False
        )

    @pytest.mark.parametrize(
        ("tail", "content"),
        [(3, _numbered(8, 10)), (10, _numbered(1, 10)), (40, _numbered(1, 10))],
    )
    def test_a_tail_is_the_files_last_lines(
        self, container: ServiceContainer, badges: Project, tail: int, content: str
    ) -> None:
        _keep(
            container,
            badges,
            1,
            "ten.txt",
            "".join(f"line {n}\n" for n in range(1, 11)).encode(),
        )

        text = container.tree_read_service().text(
            "badge-colours/attachments/1/ten.txt", None, None, tail
        )

        assert (text.content, text.limit_hit, text.line_cut) == (content, False, False)

    def test_a_range_and_a_tail_are_cut_at_the_line_limit(
        self, container: ServiceContainer, badges: Project
    ) -> None:
        lines = READ_MAX_LINES + 500
        _keep(
            container,
            badges,
            1,
            "long.txt",
            "".join(f"line {n}\n" for n in range(1, lines + 1)).encode(),
        )
        read = container.tree_read_service()
        path = "badge-colours/attachments/1/long.txt"

        whole = read.text(path, None, None, None)
        ranged = read.text(path, 101, None, None)
        tail = read.text(path, None, None, lines)

        assert (whole.content, whole.limit_hit) == (_numbered(1, lines), False)
        assert ranged == TreeText(
            _numbered(101, 100 + READ_MAX_LINES), whole.sha256, lines, True, False
        )
        assert tail == TreeText(_numbered(501, lines), whole.sha256, lines, True, False)

    def test_a_file_over_the_byte_limit_is_read_by_a_range_or_a_tail_alone(
        self, container: ServiceContainer, badges: Project
    ) -> None:
        line = "x" * 999
        raw = (f"{line}\n" * 200).encode()
        _keep(container, badges, 1, "wide.txt", raw)
        read = container.tree_read_service()
        path = "badge-colours/attachments/1/wide.txt"
        # A numbered line is its number, a colon, a space, and its 1000 bytes.
        fitting = [n for n in range(1, 201) if 1004 * 9 + 1005 * (n - 9) <= 131072]

        with pytest.raises(InvalidOperationException) as raised:
            read.text(path, None, None, None)
        ranged = read.text(path, 1, None, None)
        tail = read.text(path, None, None, 200)

        assert raised.value.message == (
            f"Cannot read '{path}' whole because it is 200000 bytes and 200 lines,"
            " over the 131072-byte (128 KB) limit of a whole read: ask for a line"
            " range with `start_line` and `end_line`, or the last lines with"
            " `tail_lines`; either answers at most 2000 lines and 128 KB"
            " [file-too-large]"
        )
        assert ranged == TreeText(
            "".join(f"{n}: {line}\n" for n in fitting),
            hashlib.sha256(raw).hexdigest(),
            200,
            True,
            False,
        )
        assert len(ranged.content.encode()) <= READ_MAX_BYTES
        assert tail.content.startswith("71: x") and tail.content.endswith("x\n")
        assert (len(tail.content.encode()) <= READ_MAX_BYTES, tail.limit_hit) == (
            True,
            True,
        )

    def test_a_line_over_the_byte_limit_on_its_own_comes_back_cut(
        self, container: ServiceContainer, badges: Project
    ) -> None:
        wide = "é" * 100_000
        _keep(container, badges, 1, "one.txt", f"first\n{wide}z\nlast\n".encode())
        read = container.tree_read_service()
        path = "badge-colours/attachments/1/one.txt"
        kept = (READ_MAX_BYTES - len("2: \n")) // 2

        ranged = read.text(path, 2, 3, None)
        tail = read.text(path, None, None, 2)
        before = read.text(path, 1, 2, None)

        assert ranged.content == f"2: {'é' * kept}\n"
        assert (ranged.limit_hit, ranged.line_cut, ranged.total_count) == (
            True,
            True,
            3,
        )
        assert (tail.content, tail.limit_hit, tail.line_cut) == (
            "3: last\n",
            True,
            False,
        )
        assert read.text(path, None, None, 1).content == "3: last\n"
        assert (before.content, before.limit_hit, before.line_cut) == (
            "1: first\n",
            True,
            False,
        )
        cut = read.text(path, None, 2, None)
        assert (cut.content, cut.line_cut) == ("1: first\n", False)

    def test_a_tail_ending_in_a_line_over_the_limit_keeps_the_lines_end(
        self, container: ServiceContainer, badges: Project
    ) -> None:
        wide = "a" + "é" * 100_000 + "z"
        _keep(container, badges, 1, "one.txt", f"first\n{wide}\n".encode())
        kept = (READ_MAX_BYTES - len("2: \n") - 1) // 2

        tail = container.tree_read_service().text(
            "badge-colours/attachments/1/one.txt", None, None, 2
        )

        assert tail.content == f"2: {'é' * kept}z\n"
        assert (tail.limit_hit, tail.line_cut) == (True, True)

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param(b"\xff\xfe\x00a", id="not-utf-8"),
            pytest.param(b"\x89PNG\r\n\x1a\n", id="an-image"),
            pytest.param(b"text\x00more\n", id="a-nul-byte"),
        ],
    )
    @pytest.mark.parametrize(
        "lines", [(None, None, None), (1, 2, None), (None, None, 3)]
    )
    def test_a_file_that_is_not_text_is_refused(
        self,
        container: ServiceContainer,
        badges: Project,
        content: bytes,
        lines: tuple[int | None, int | None, int | None],
    ) -> None:
        _keep(container, badges, 1, "badge.png", content)

        with pytest.raises(InvalidOperationException) as raised:
            container.tree_read_service().text(
                "badge-colours/attachments/1/badge.png", *lines
            )

        assert raised.value.message == (
            "Cannot read 'badge-colours/attachments/1/badge.png' because it is not"
            " UTF-8 text, and a read answers text alone [not-text]"
        )

    @pytest.mark.parametrize(
        "path", ["badge-colours", "badge-colours/items/", "", ".", "badge-colours/.."]
    )
    def test_a_directory_is_not_a_file(
        self, container: ServiceContainer, path: str
    ) -> None:
        with pytest.raises(InvalidOperationException) as raised:
            container.tree_read_service().text(path, None, None, None)

        assert raised.value.message == (
            f"Cannot read {path!r} because it is a folder, not a file [not-a-file]"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "badge-colours/notes.md",
            "badge-colours/items/3-nothing.md",
            "nowhere/project.md",
            "project.md",
            "badge-colours/project.md/x",
            pytest.param(
                "draft-{number}/project.md", id="its-draft-folder-once-opened"
            ),
            pytest.param("reference.json\x00", id="a-nul-in-the-path"),
        ],
    )
    def test_nothing_at_the_path_is_not_found(
        self, container: ServiceContainer, badges: Project, path: str
    ) -> None:
        path = path.format(number=badges.number)

        with pytest.raises(RecordNotFoundException) as raised:
            container.tree_read_service().text(path, None, None, None)

        assert raised.value.message == f"File {path!r} was not found"

    def test_an_archived_projects_file_is_not_read(
        self, session: DbSession, container: ServiceContainer, badges: Project
    ) -> None:
        read = container.tree_read_service()
        assert read.text("badge-colours/project.md", None, None, None).total_count == 2
        badges.archived = True
        session.flush()

        with pytest.raises(RecordNotFoundException):
            read.text("badge-colours/project.md", None, None, None)

    @pytest.mark.parametrize("path", ["/badge-colours/project.md", "../project.md"])
    def test_a_path_that_leaves_the_tree_is_refused(
        self, container: ServiceContainer, path: str
    ) -> None:
        with pytest.raises(ValidationException) as raised:
            container.tree_read_service().text(path, None, None, None)

        assert raised.value.message == (
            f"Path '{path}' is outside the projects' files: a path runs from their"
            " root, as `<folder>/timeline.json` does, never from `/` and never"
            " above it [path-outside-projects]"
        )

    @pytest.mark.parametrize("lines", [(1, None, 5), (None, 9, 5), (2, 9, 5)])
    def test_a_tail_with_a_range_is_refused(
        self, container: ServiceContainer, lines: tuple[int | None, int | None, int]
    ) -> None:
        with pytest.raises(ValidationException) as raised:
            container.tree_read_service().text("badge-colours/project.md", *lines)

        assert raised.value.message == (
            "Pass either `tail_lines` or `start_line` and `end_line`, not both: a"
            " tail is the file's last lines, a range the lines between two numbers"
        )
