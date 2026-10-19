"""The store's tree as the record sees it (design 1 §5.1, §5.2): what each
path names, the bytes it must hold, and their tree hash."""

import re
from dataclasses import dataclass

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, defer

from app.engine.paths import PLAN, REFERENCE, TIMELINE, attachment_path, tree_path
from app.engine.plan import PlanService
from app.engine.views import Rendering, ViewService
from app.exceptions import RecordNotFoundException
from app.models import Attachment, Document, Item, Project, SaveError
from app.models.reference import ErrorKind

_DRAFT_FOLDER = re.compile(r"draft-(?P<number>[1-9][0-9]*)")
_ATTACHMENT = re.compile(r"attachments/(?P<batch>[1-9][0-9]*)/(?P<filename>[^/]+)")
_SYNCING = Project.archived.is_(False)
"""The projects whose folders the store syncs (design 1 §5.5)."""


@dataclass(frozen=True)
class TreeFile:
    """The bytes a path must hold, and their hash."""

    content: bytes
    hash: str


@dataclass(frozen=True)
class TreeDocument:
    """A path that is a Document of a project's folder; `item` is its Prose
    Item, none for a Project Document."""

    project: Project
    document: Document
    item: Item | None


@dataclass(frozen=True)
class ManifestEntry:
    """A path the store syncs, with its tree hash and whether it is a
    read-only view (design 1 §5.5, §8)."""

    path: str
    hash: str
    readonly: bool


@dataclass(frozen=True)
class TreePlan:
    """A project's `plan.json`, rendered from its rows and parsed back into
    them (design 1 §6.2)."""

    project: Project


class TreeService:
    """What the store's tree must hold, path by path.

    A path's `parse` Save Errors are the store's: its tree is the one the
    engine ingests from (design 1 §5.1), so a path is held whatever
    Environment holds the error.
    """

    def __init__(
        self, db: Session, view_service: ViewService, plan_service: PlanService
    ) -> None:
        self.db = db
        self.view_service = view_service
        self.plan_service = plan_service

    def resolve(self, path: str) -> TreeDocument | TreePlan | TreeFile:
        """What `path`, from the tree's root, names among the paths the store
        syncs: a Document, a project's plan, or a read-only path with its
        projection. Refused
        for any other path: a stray file's, a folder no project has, an
        archived project's (design 1 §5.3 step 1, §5.5)."""
        if path == REFERENCE:
            return _file(self.view_service.reference())
        folder, _, rest = path.partition("/")
        project = self._project(folder)
        if project is not None:
            if rest == TIMELINE:
                return _file(self.view_service.timeline(project))
            if rest == PLAN:
                return TreePlan(project)
            attachment = _ATTACHMENT.fullmatch(rest)
            if attachment is not None:
                copy = self.db.scalars(
                    select(Attachment).where(
                        Attachment.project_id == project.id,
                        Attachment.batch == int(attachment["batch"]),
                        Attachment.filename == attachment["filename"],
                    )
                ).one_or_none()
                if copy is not None:
                    return TreeFile(copy.content, copy.sha256)
            found = self.db.execute(
                select(Document, Item)
                .outerjoin(Item, Item.id == Document.id)
                .where(
                    Document.path == rest,
                    or_(
                        Document.project_id == project.id,
                        Item.project_id == project.id,
                    ),
                )
            ).one_or_none()
            if found is not None:
                return TreeDocument(project, found[0], found[1])
        raise RecordNotFoundException("Path", path)

    def read(self, path: str) -> TreeFile:
        """The bytes `path` must hold in the tree, and their tree hash."""
        resolved = self.resolve(path)
        if isinstance(resolved, TreeFile):
            return resolved
        if isinstance(resolved, TreePlan):
            return _file(self.plan_service.render(resolved.project))
        document = resolved.document
        held = self.held(resolved.project, document)
        text = document.ingested_text if held else document.published_text
        # Every document is born published, and a held save has its ingest.
        assert text is not None
        return TreeFile(text.encode(), _tree_hash(document, held))

    def held(self, project: Project, document: Document) -> bool:
        """Whether the document's latest save is held."""
        return self.held_path(tree_path(project, document.path))

    def held_path(self, path: str) -> bool:
        """Whether the latest save of `path`, from the tree's root, is held:
        a `parse` Save Error stands on it."""
        return bool(
            self.db.scalar(
                select(
                    exists().where(
                        SaveError.path == path,
                        SaveError.kind_code == ErrorKind.PARSE,
                    )
                )
            )
        )

    def hash(self, project: Project, document: Document) -> str:
        """A document's tree hash: its published hash, or its ingested hash
        while the path's latest save is held."""
        return _tree_hash(document, self.held(project, document))

    def hashes(self, project: Project) -> dict[str, str]:
        """Every path of the project's folder with its tree hash, the paths
        from the tree's root."""
        return {entry.path: entry.hash for entry in self._folder(project)}

    def manifest(self) -> list[ManifestEntry]:
        """Every path the store syncs, in path order: `reference.json` at the
        tree's root, and every path of every syncing project's folder
        (design 1 §5.5)."""
        entries = [ManifestEntry(REFERENCE, self.view_service.reference().hash, True)]
        for project in self.db.scalars(select(Project).where(_SYNCING)).all():
            entries.extend(self._folder(project))
        return sorted(entries, key=lambda entry: entry.path)

    def _folder(self, project: Project) -> list[ManifestEntry]:
        """Every path of the project's folder, from the tree's root, in path
        order; its `timeline.json` and attachments are read-only."""
        documents = {
            tree_path(project, document.path): document
            for document in self.db.scalars(
                select(Document).where(
                    or_(
                        Document.project_id == project.id,
                        Document.id.in_(
                            select(Item.id).where(Item.project_id == project.id)
                        ),
                    )
                )
            )
        }
        held = set(
            self.db.scalars(
                select(SaveError.path).where(
                    SaveError.kind_code == ErrorKind.PARSE,
                    SaveError.path.in_(documents),
                )
            )
        )
        entries = [
            ManifestEntry(path, _tree_hash(document, path in held), False)
            for path, document in documents.items()
        ]
        entries.append(
            ManifestEntry(
                tree_path(project, TIMELINE),
                self.view_service.timeline(project).hash,
                True,
            )
        )
        entries.append(
            ManifestEntry(
                tree_path(project, PLAN), self.plan_service.render(project).hash, False
            )
        )
        entries.extend(
            ManifestEntry(
                tree_path(project, attachment_path(attachment)),
                attachment.sha256,
                True,
            )
            for attachment in self.db.scalars(
                # Its hash, not its bytes: the content stays in the database.
                select(Attachment)
                .where(Attachment.project_id == project.id)
                .options(defer(Attachment.content))
            )
        )
        return sorted(entries, key=lambda entry: entry.path)

    def _project(self, folder: str) -> Project | None:
        """The syncing project whose folder is `folder` (DB decision 1)."""
        draft = _DRAFT_FOLDER.fullmatch(folder)
        named = (
            Project.slug == folder
            if draft is None
            else (Project.number == int(draft["number"])) & Project.slug.is_(None)
        )
        return self.db.scalars(select(Project).where(named, _SYNCING)).one_or_none()


def _file(rendering: Rendering) -> TreeFile:
    return TreeFile(rendering.text.encode(), rendering.hash)


def _tree_hash(document: Document, held: bool) -> str:
    tree_hash = document.ingested_hash if held else document.published_hash
    # Every document is born published, and a held save has its ingest.
    assert tree_hash is not None
    return tree_hash
