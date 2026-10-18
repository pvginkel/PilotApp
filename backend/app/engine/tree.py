"""The tree hash of every path a project's folder holds (design 1 §5.2)."""

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.engine.paths import TIMELINE, attachment_path, tree_path
from app.engine.views import ViewService
from app.models import Attachment, Document, Item, Project, SaveError
from app.models.reference import ErrorKind


class TreeService:
    """What the store's tree must hold, path by path.

    A path's `parse` Save Errors are the store's: its tree is the one the
    engine ingests from (design 1 §5.1), so a path is held whatever
    Environment holds the error.
    """

    def __init__(self, db: Session, view_service: ViewService) -> None:
        self.db = db
        self.view_service = view_service

    def hash(self, project: Project, document: Document) -> str:
        """A document's tree hash: its published hash, or its ingested hash
        while the path's latest save is held."""
        held = self.db.scalar(
            select(
                exists().where(
                    SaveError.path == tree_path(project, document.path),
                    SaveError.kind_code == ErrorKind.PARSE,
                )
            )
        )
        return _tree_hash(document, bool(held))

    def hashes(self, project: Project) -> dict[str, str]:
        """Every path of the project's folder with its tree hash, the paths
        from the tree's root."""
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
        hashes = {
            path: _tree_hash(document, path in held)
            for path, document in documents.items()
        }
        hashes[tree_path(project, TIMELINE)] = self.view_service.timeline(project).hash
        for attachment in self.db.scalars(
            select(Attachment).where(Attachment.project_id == project.id)
        ):
            hashes[tree_path(project, attachment_path(attachment))] = attachment.sha256
        return dict(sorted(hashes.items()))


def _tree_hash(document: Document, held: bool) -> str:
    tree_hash = document.ingested_hash if held else document.published_hash
    # Every document is born published, and a held save has its ingest.
    assert tree_hash is not None
    return tree_hash
