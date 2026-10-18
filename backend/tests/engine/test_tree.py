"""The tree hash of every path a project's folder holds (design 1 §5.2)."""

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.engine.paths import sha256_hex
from app.engine.tree import TreeDocument, TreeFile, TreePlan
from app.exceptions import RecordNotFoundException
from app.models import Attachment, Document, Environment, Project, SaveError
from app.models.reference import AttachmentSource, ErrorKind, ProjectState
from app.services.container import ServiceContainer

_HELD = "```decision id=D1\nproposal: [\n```\n"


def _ingest(document: Document, text: str) -> None:
    document.ingested_text = text
    document.ingested_hash = sha256_hex(text)
    document.ingested_at = datetime.now(UTC)


def _error(
    environment: Environment, path: str, kind: ErrorKind = ErrorKind.PARSE
) -> SaveError:
    return SaveError(
        environment_id=environment.id, path=path, kind_code=kind, message="a fault"
    )


class TestTreeService:
    def test_a_documents_tree_hash_is_its_published_hash(
        self, container: ServiceContainer, project: Project
    ) -> None:
        draft = container.document_service().bear_draft(project, "# Badges\n")

        assert container.tree_service().hash(project, draft) == sha256_hex("# Badges\n")

    def test_a_held_path_holds_its_ingest(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = container.document_service().bear_draft(project)
        _ingest(draft, _HELD)
        session.add(_error(environment, f"draft-{project.number}/project.md"))
        session.flush()

        assert container.tree_service().hash(project, draft) == sha256_hex(_HELD)

    def test_a_reverted_error_holds_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = container.document_service().bear_draft(project)
        _ingest(draft, "# Badges\n")
        session.add(
            _error(
                environment, f"draft-{project.number}/project.md", ErrorKind.REVERTED
            )
        )
        session.flush()

        assert container.tree_service().hash(project, draft) == sha256_hex("")

    def test_another_paths_error_holds_nothing(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = container.document_service().bear_draft(project)
        _ingest(draft, _HELD)
        session.add(_error(environment, f"draft-{project.number}/handbook.md"))
        session.flush()

        assert container.tree_service().hash(project, draft) == sha256_hex("")

    def test_a_drafts_folder_holds_its_draft_plan_and_timeline(
        self, container: ServiceContainer, project: Project
    ) -> None:
        container.document_service().bear_draft(project)
        folder = f"draft-{project.number}"

        assert container.tree_service().hashes(project) == {
            f"{folder}/plan.json": container.plan_service().render(project).hash,
            f"{folder}/project.md": sha256_hex(""),
            f"{folder}/timeline.json": container.view_service().timeline(project).hash,
        }

    def test_an_open_projects_folder_holds_every_path(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
        project_session: models.Session,
    ) -> None:
        documents = container.document_service()
        documents.bear_draft(project, "# Badges\n")
        project.slug = "badge-colours"
        project.state_code = ProjectState.OPEN
        documents.bear_handbook(project, "Keep it short.\n")
        held = documents.bear_item(project, "notice", "The palette", project_session)
        documents.bear_item(project, "decision", "Which colour?", project_session)
        _ingest(session.get_one(Document, held.id), _HELD)
        session.add(_error(environment, "badge-colours/items/1-the-palette.md"))
        content = b"# Palette\n"
        session.add(
            Attachment(
                project_id=project.id,
                batch=1,
                title="Palette",
                filename="project.md",
                content_type="text/markdown",
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
                source_code=AttachmentSource.DRAFT,
                copied_at=datetime.now(UTC),
            )
        )
        session.flush()
        container.plan_service().save(project, b'{"ticket": "MD-8"}')

        hashes = container.tree_service().hashes(project)

        assert hashes == {
            "badge-colours/attachments/1/project.md": hashlib.sha256(
                content
            ).hexdigest(),
            "badge-colours/handbook.md": sha256_hex("Keep it short.\n"),
            "badge-colours/items/1-the-palette.md": sha256_hex(_HELD),
            "badge-colours/items/2-which-colour.md": sha256_hex(""),
            "badge-colours/plan.json": container.plan_service().render(project).hash,
            "badge-colours/project.md": sha256_hex("# Badges\n"),
            "badge-colours/timeline.json": container.view_service()
            .timeline(project)
            .hash,
        }
        assert list(hashes) == sorted(hashes)

    def test_another_projects_paths_are_not_in_the_folder(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        other = Project(created_by_user_id=project.created_by_user_id)
        session.add(other)
        session.flush()
        documents = container.document_service()
        documents.bear_draft(other)
        documents.bear_item(project, "notice", "The palette", project_session)

        assert set(container.tree_service().hashes(other)) == {
            f"draft-{other.number}/plan.json",
            f"draft-{other.number}/project.md",
            f"draft-{other.number}/timeline.json",
        }


class TestTreeServicePaths:
    def test_a_project_documents_path_names_it(
        self, container: ServiceContainer, project: Project
    ) -> None:
        draft = container.document_service().bear_draft(project, "# Badges\n")

        assert container.tree_service().resolve(
            f"draft-{project.number}/project.md"
        ) == TreeDocument(project, draft, None)

    def test_an_items_path_names_its_document_and_item(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        project_session: models.Session,
    ) -> None:
        item = container.document_service().bear_item(
            project, "notice", "The palette", project_session
        )
        project.slug = "badge-colours"
        project.state_code = ProjectState.OPEN
        session.flush()

        assert container.tree_service().resolve(
            "badge-colours/items/1-the-palette.md"
        ) == TreeDocument(project, session.get_one(Document, item.id), item)

    def test_the_plan_names_its_project(
        self, container: ServiceContainer, project: Project
    ) -> None:
        assert container.tree_service().resolve(
            f"draft-{project.number}/plan.json"
        ) == TreePlan(project)

    def test_the_views_name_their_renderings(
        self, container: ServiceContainer, project: Project
    ) -> None:
        tree, views = container.tree_service(), container.view_service()
        timeline, reference = views.timeline(project), views.reference()

        assert tree.resolve(f"draft-{project.number}/timeline.json") == TreeFile(
            timeline.text.encode(), timeline.hash
        )
        assert tree.resolve("reference.json") == TreeFile(
            reference.text.encode(), reference.hash
        )

    def test_an_attachments_path_names_its_copy(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        content = b"# Palette\n"
        session.add(
            Attachment(
                project_id=project.id,
                batch=3,
                title="Palette",
                filename="palette.md",
                content_type="text/markdown",
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
                source_code=AttachmentSource.DRAFT,
                copied_at=datetime.now(UTC),
            )
        )
        session.flush()

        assert container.tree_service().resolve(
            f"draft-{project.number}/attachments/3/palette.md"
        ) == TreeFile(content, hashlib.sha256(content).hexdigest())

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "project.md",
            "draft-999999/project.md",
            "draft-0{number}/project.md",
            "{folder}",
            "{folder}/handbook.md",
            "{folder}/notes.md",
            "{folder}/attachments/3/palette.md",
            "{folder}/attachments/x/palette.md",
        ],
    )
    def test_a_path_the_store_does_not_sync_is_refused(
        self, container: ServiceContainer, project: Project, path: str
    ) -> None:
        container.document_service().bear_draft(project)
        path = path.format(folder=f"draft-{project.number}", number=project.number)

        with pytest.raises(RecordNotFoundException) as raised:
            container.tree_service().resolve(path)

        assert raised.value.message == f"Path {path} was not found"

    def test_an_archived_or_opened_projects_draft_folder_is_refused(
        self, session: DbSession, container: ServiceContainer, project: Project
    ) -> None:
        container.document_service().bear_draft(project)
        tree = container.tree_service()
        project.slug = "badge-colours"
        project.state_code = ProjectState.OPEN
        session.flush()

        with pytest.raises(RecordNotFoundException):
            tree.resolve(f"draft-{project.number}/project.md")
        project.archived = True
        session.flush()
        with pytest.raises(RecordNotFoundException):
            tree.resolve("badge-colours/project.md")

    def test_read_gives_the_published_text_or_the_held_ingest(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        draft = container.document_service().bear_draft(project, "# Badges\n")
        path = f"draft-{project.number}/project.md"
        tree = container.tree_service()

        assert tree.read(path) == TreeFile(b"# Badges\n", sha256_hex("# Badges\n"))
        assert not tree.held(project, draft)
        _ingest(draft, _HELD)
        session.add(_error(environment, path))
        session.flush()
        assert tree.read(path) == TreeFile(_HELD.encode(), sha256_hex(_HELD))
        assert tree.held(project, draft)

    def test_read_gives_the_plans_rendering(
        self, container: ServiceContainer, project: Project
    ) -> None:
        container.plan_service().save(project, b'{"ticket": "MD-8"}')
        plan = container.plan_service().render(project)

        assert container.tree_service().read(
            f"draft-{project.number}/plan.json"
        ) == TreeFile(plan.text.encode(), plan.hash)

    def test_held_path_is_a_parse_error_standing_on_the_path(
        self,
        session: DbSession,
        container: ServiceContainer,
        project: Project,
        environment: Environment,
    ) -> None:
        path = f"draft-{project.number}/plan.json"
        tree = container.tree_service()
        session.add(_error(environment, path, ErrorKind.REVERTED))
        session.add(_error(environment, f"draft-{project.number}/project.md"))
        session.flush()

        assert not tree.held_path(path)
        session.add(_error(environment, path))
        session.flush()
        assert tree.held_path(path)

    def test_read_gives_a_read_only_paths_projection(
        self, container: ServiceContainer, project: Project
    ) -> None:
        timeline = container.view_service().timeline(project)

        assert container.tree_service().read(
            f"draft-{project.number}/timeline.json"
        ) == TreeFile(timeline.text.encode(), timeline.hash)
