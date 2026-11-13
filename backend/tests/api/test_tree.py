"""The routes that read the store's tree as the record renders it (F150.5): a
directory's entries, the files a glob matches and a file as text."""

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.models import Attachment, Project
from app.models.reference import AttachmentSource
from app.schemas.testing_record import InventedProjectCreateSchema
from app.services.container import ServiceContainer

ENTRIES = "/api/tree/entries"
MATCHES = "/api/tree/matches"
TEXT = "/api/tree/text"


@pytest.fixture
def recipes(client: FlaskClient, container: ServiceContainer, person: Any) -> Project:
    """An open project of a signed-in person's: its draft, its handbook and
    its opening."""
    response = client.post(
        "/api/testing/auth/session",
        json={"subject": "subject-ada", "name": "Ada Example", "roles": ["editor"]},
    )
    assert response.status_code == 201
    return container.test_data_service().project(
        InventedProjectCreateSchema.model_validate(
            {"name": "Recipe box", "members": ["ada"]}
        )
    )


class TestListEntries:
    def test_the_root_is_listed_without_a_path(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(ENTRIES)

        assert response.status_code == 200
        assert response.get_json() == {
            "entries": [
                {"path": f"{recipes.slug}/", "is_directory": True},
                {"path": "reference.json", "is_directory": False},
            ]
        }

    def test_a_folder_is_listed_directories_first(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(ENTRIES, query_string={"path": f"{recipes.slug}/"})

        assert response.status_code == 200
        assert response.get_json() == {
            "entries": [
                {"path": f"{recipes.slug}/items/", "is_directory": True},
                {"path": f"{recipes.slug}/chat.md", "is_directory": False},
                {"path": f"{recipes.slug}/handbook.md", "is_directory": False},
                {"path": f"{recipes.slug}/plan.json", "is_directory": False},
                {"path": f"{recipes.slug}/project.md", "is_directory": False},
                {"path": f"{recipes.slug}/timeline.json", "is_directory": False},
            ]
        }

    def test_an_archived_projects_folder_is_not_listed(
        self, client: FlaskClient, session: Session, recipes: Project
    ) -> None:
        recipes.archived = True
        session.flush()

        root = client.get(ENTRIES)
        folder = client.get(ENTRIES, query_string={"path": recipes.slug})

        assert root.get_json() == {
            "entries": [{"path": "reference.json", "is_directory": False}]
        }
        assert folder.status_code == 404

    def test_nothing_at_the_path_is_not_found(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(ENTRIES, query_string={"path": "bike-log"})

        assert response.status_code == 404
        assert (
            response.get_json()["error"]
            == "Folder 'bike-log' was not found [not-found]"
        )

    def test_a_files_path_is_refused(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(ENTRIES, query_string={"path": "reference.json"})

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            "Cannot list 'reference.json' because it is a file, not a folder"
            " [not-a-directory]"
        )

    @pytest.mark.parametrize("path", ["/work", "../x"])
    def test_a_path_that_leaves_the_tree_is_refused(
        self, client: FlaskClient, recipes: Project, path: str
    ) -> None:
        response = client.get(ENTRIES, query_string={"path": path})

        assert response.status_code == 400
        assert response.get_json()["error"].endswith("[path-outside-projects]")

    def test_no_one_signed_in_is_refused(self, oidc_client: FlaskClient) -> None:
        assert oidc_client.get(ENTRIES).status_code == 401


class TestListMatches:
    def test_the_files_a_glob_matches_are_answered_in_path_order(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(MATCHES, query_string={"pattern": "**/*.json"})

        assert response.status_code == 200
        assert response.get_json() == {
            "paths": [
                f"{recipes.slug}/plan.json",
                f"{recipes.slug}/timeline.json",
                "reference.json",
            ]
        }

    def test_a_glob_that_matches_nothing_answers_no_path(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(MATCHES, query_string={"pattern": "*.md"})

        assert (response.status_code, response.get_json()) == (200, {"paths": []})

    def test_an_archived_projects_files_are_not_matched(
        self, client: FlaskClient, session: Session, recipes: Project
    ) -> None:
        recipes.archived = True
        session.flush()

        response = client.get(MATCHES, query_string={"pattern": "**"})

        assert response.get_json() == {"paths": ["reference.json"]}

    @pytest.mark.parametrize(
        ("pattern", "fault"),
        [
            ("items/[ab].md", "(supported: *, **, ?, {a,b}) [validation-error]"),
            ("/work/**", "[path-outside-projects]"),
        ],
    )
    def test_a_pattern_the_search_does_not_take_is_refused(
        self, client: FlaskClient, recipes: Project, pattern: str, fault: str
    ) -> None:
        response = client.get(MATCHES, query_string={"pattern": pattern})

        assert response.status_code == 400
        assert response.get_json()["error"].endswith(fault)

    @pytest.mark.parametrize("query", [{}, {"pattern": ""}])
    def test_no_pattern_is_refused(
        self, client: FlaskClient, recipes: Project, query: dict[str, str]
    ) -> None:
        assert client.get(MATCHES, query_string=query).status_code == 400

    def test_no_one_signed_in_is_refused(self, oidc_client: FlaskClient) -> None:
        response = oidc_client.get(MATCHES, query_string={"pattern": "**"})

        assert response.status_code == 401


class TestReadText:
    def test_a_file_is_read_whole_with_its_hash_and_its_line_count(
        self, client: FlaskClient, container: ServiceContainer, recipes: Project
    ) -> None:
        draft = container.tree_service().read(f"{recipes.slug}/project.md").content

        response = client.get(TEXT, query_string={"path": f"{recipes.slug}/project.md"})

        assert response.status_code == 200
        lines = draft.decode().splitlines()
        assert response.get_json() == {
            "content": "".join(f"{n}: {line}\n" for n, line in enumerate(lines, 1)),
            "sha256": hashlib.sha256(draft).hexdigest(),
            "total_count": len(lines),
            "limit_hit": False,
            "line_cut": False,
        }
        assert lines

    def test_a_range_and_a_tail_read_their_lines(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        path = f"{recipes.slug}/timeline.json"
        whole = client.get(TEXT, query_string={"path": path}).get_json()
        numbered = whole["content"].splitlines(keepends=True)

        ranged = client.get(
            TEXT, query_string={"path": path, "start_line": 2, "end_line": 3}
        )
        tail = client.get(TEXT, query_string={"path": path, "tail_lines": 2})

        assert ranged.get_json() == whole | {"content": "".join(numbered[1:3])}
        assert tail.get_json() == whole | {"content": "".join(numbered[-2:])}

    def test_a_tail_with_a_range_is_refused(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(
            TEXT,
            query_string={"path": "reference.json", "start_line": 1, "tail_lines": 2},
        )

        assert response.status_code == 400
        assert response.get_json()["error"].startswith(
            "Pass either `tail_lines` or `start_line` and `end_line`, not both"
        )

    @pytest.mark.parametrize(
        "query",
        [
            {},
            {"path": ""},
            {"path": "reference.json", "start_line": "0"},
            {"path": "reference.json", "end_line": "0"},
            {"path": "reference.json", "tail_lines": "0"},
            {"path": "reference.json", "start_line": "two"},
        ],
    )
    def test_no_path_or_a_line_that_is_no_number_from_one_is_refused(
        self, client: FlaskClient, recipes: Project, query: dict[str, str]
    ) -> None:
        assert client.get(TEXT, query_string=query).status_code == 400

    def test_a_path_that_leaves_the_tree_is_refused(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(TEXT, query_string={"path": "/etc/hostname"})

        assert response.status_code == 400
        assert response.get_json()["error"].endswith("[path-outside-projects]")

    def test_nothing_at_the_path_is_not_found(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(TEXT, query_string={"path": f"{recipes.slug}/notes.md"})

        assert response.status_code == 404
        assert response.get_json()["error"] == (
            f"File '{recipes.slug}/notes.md' was not found [not-found]"
        )

    def test_an_archived_projects_file_is_not_read(
        self, client: FlaskClient, session: Session, recipes: Project
    ) -> None:
        recipes.archived = True
        session.flush()

        response = client.get(TEXT, query_string={"path": f"{recipes.slug}/project.md"})

        assert response.status_code == 404

    def test_a_directory_is_refused(
        self, client: FlaskClient, recipes: Project
    ) -> None:
        response = client.get(TEXT, query_string={"path": f"{recipes.slug}/items"})

        assert response.status_code == 409
        assert response.get_json()["error"].endswith("[not-a-file]")

    def test_a_file_that_is_not_text_is_refused(
        self,
        client: FlaskClient,
        session: Session,
        container: ServiceContainer,
        recipes: Project,
    ) -> None:
        container.attachment_store().put(
            Attachment(
                project_id=recipes.id,
                batch=1,
                title="The badge",
                filename="badge.png",
                content_type="image/png",
                source_code=AttachmentSource.DRAFT,
                copied_at=datetime.now(UTC),
            ),
            b"\x89PNG\r\n\x1a\n",
        )
        session.flush()

        response = client.get(
            TEXT, query_string={"path": f"{recipes.slug}/attachments/1/badge.png"}
        )

        assert response.status_code == 409
        assert response.get_json()["error"] == (
            f"Cannot read '{recipes.slug}/attachments/1/badge.png' because it is"
            " not UTF-8 text, and a read answers text alone [not-text]"
        )

    def test_no_one_signed_in_is_refused(self, oidc_client: FlaskClient) -> None:
        response = oidc_client.get(TEXT, query_string={"path": "reference.json"})

        assert response.status_code == 401
