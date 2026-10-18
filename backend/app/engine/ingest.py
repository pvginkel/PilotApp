"""The engine's side of the file put (design 1 §5.3): an agent's save of a
path of the store's tree, gated, merged by ownership and published, in one
transaction that holds the document's row."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engine import dsl
from app.engine.bus import (
    DocumentModified,
    EngineBus,
    ErrorsRaised,
    ErrorsResolved,
    TreeHashMoved,
)
from app.engine.documents import OPENING, DocumentService
from app.engine.paths import sha256_hex
from app.engine.tree import TreeDocument, TreeFile, TreeService
from app.engine.views import ViewService
from app.models import Document, Environment, Item, PlanTask, Project, SaveError, User
from app.models import Session as AgentSession
from app.models.reference import DocumentRole, ErrorKind

_NOT_TEXT = (
    "the file is not UTF-8 text: each byte that is not, and each NUL,"
    " is replaced by U+FFFD"
)


@dataclass(frozen=True)
class Ingested:
    """What the file put answers (design 1 §5.1).

    `content` is the bytes the file must now hold, none when the save is
    them; `hash` the path's tree hash; `stale` whether the base hash was not
    the path's tree hash when the save came. `faults` are those the save
    raised on the path: `parse` faults when it is `held`, else `reverted`.
    """

    content: bytes | None
    hash: str
    stale: bool
    held: bool
    faults: tuple[dsl.Fault, ...]


class IngestService:
    def __init__(
        self,
        db: Session,
        engine_bus: EngineBus,
        tree_service: TreeService,
        view_service: ViewService,
        document_service: DocumentService,
    ) -> None:
        self.db = db
        self.engine_bus = engine_bus
        self.tree_service = tree_service
        self.view_service = view_service
        self.document_service = document_service

    def ingest(
        self,
        path: str,
        content: bytes,
        base_hash: str | None,
        environment: Environment,
        session: AgentSession | None,
    ) -> Ingested:
        """Take the store's save of `path`, from the tree's root.

        `base_hash` is the hash the sidecar last synced for the path, none
        when it has none; `session` the Session whose turn wrote the save,
        none while that is not known (design 1 §7).

        A read-only path stores nothing and is answered with its projection.
        A document's save is stored as its ingest and held on any fault, else
        merged by ownership against the published text and published; its
        faults replace the path's `parse` Save Errors. Refused for a path the
        store does not sync.
        """
        resolved = self.tree_service.resolve(path)
        if isinstance(resolved, TreeFile):
            return Ingested(
                content=_unless(resolved.content, content),
                hash=resolved.hash,
                stale=base_hash != resolved.hash,
                held=False,
                faults=(),
            )
        return self._ingest_document(
            path, resolved, content, base_hash, environment, session
        )

    def _ingest_document(
        self,
        path: str,
        resolved: TreeDocument,
        content: bytes,
        base_hash: str | None,
        environment: Environment,
        session: AgentSession | None,
    ) -> Ingested:
        project, document, item = resolved.project, resolved.document, resolved.item
        self.document_service.lock(document)
        held_before = self.tree_service.held(project, document)
        tree_hash = self.tree_service.hash(project, document)

        text, faults = _decoded(content)
        self._store(document, text, session)
        self.db.execute(
            delete(SaveError).where(
                SaveError.path == path, SaveError.kind_code == ErrorKind.PARSE
            )
        )
        kind = _kind(document, item)
        faults = sorted(
            [
                *faults,
                *dsl.validate(dsl.parse(text), self._facts(project, document, kind)),
            ],
            key=lambda fault: (fault.line is None, fault.line or 0),
        )
        held = bool(faults)
        if held:
            self._raise(environment, path, ErrorKind.PARSE, faults)
            tree_text = text
        else:
            merged = dsl.merge(_published(document), text, kind)
            self.document_service.publish(document, merged.text)
            faults = list(merged.reverted)
            self._raise(environment, path, ErrorKind.REVERTED, faults)
            tree_text = merged.text

        moved = self.tree_service.hash(project, document)
        if moved != tree_hash:
            self.engine_bus.emit(TreeHashMoved(path, moved))
        self.engine_bus.emit(DocumentModified(project.id, path))
        if held:
            self.engine_bus.emit(ErrorsRaised(project.id, path))
        elif held_before:
            self.engine_bus.emit(ErrorsResolved(project.id, path))
        return Ingested(
            content=_unless(tree_text.encode(), content),
            hash=moved,
            stale=base_hash != tree_hash,
            held=held,
            faults=tuple(faults),
        )

    @staticmethod
    def _store(document: Document, text: str, session: AgentSession | None) -> None:
        """The save as the document's ingest, and its session as the one
        writing it (design 1 §7)."""
        now = datetime.now(UTC)
        document.ingested_text = text
        document.ingested_hash = sha256_hex(text)
        document.ingested_at = now
        document.ingested_session_id = None if session is None else session.id
        if session is not None and document.writing_session_id != session.id:
            document.writing_session_id = session.id
            document.writing_since = now

    def _raise(
        self,
        environment: Environment,
        path: str,
        kind: ErrorKind,
        faults: list[dsl.Fault],
    ) -> None:
        self.db.add_all(
            SaveError(
                environment_id=environment.id,
                path=path,
                kind_code=kind,
                line=fault.line,
                message=fault.message,
            )
            for fault in faults
        )

    def _facts(
        self, project: Project, document: Document, kind: dsl.DocumentKind
    ) -> dsl.Facts:
        """What the record holds at the save; a `to` the published text has is
        not checked again (DB 203)."""
        tasks = self.db.execute(
            select(PlanTask.task_id, PlanTask.removed_at).where(
                PlanTask.project_id == project.id
            )
        ).all()
        return dsl.Facts(
            document=kind,
            handles=set(self.db.scalars(select(User.handle))),
            plan_task_ids={task for task, removed_at in tasks if removed_at is None},
            removed_task_ids={
                task for task, removed_at in tasks if removed_at is not None
            },
            confirmation_reasons=[
                reason.code for reason in self.view_service.confirmation_reasons()
            ],
            taken_slugs={
                slug
                for slug in self.db.scalars(
                    select(Project.slug).where(Project.id != project.id)
                )
                if slug is not None
            },
            published_to={
                block.local_id: block.to
                for block in dsl.parse(_published(document)).blocks
                if block.to is not None
            },
        )


def _decoded(content: bytes) -> tuple[str, list[dsl.Fault]]:
    """The save's text, and a fault at the first of its bytes PostgreSQL's
    `text` cannot hold: bytes that are not UTF-8, and NUL. Each of those is
    replaced by U+FFFD."""
    try:
        text = content.decode()
    except UnicodeDecodeError as error:
        line = content.count(b"\n", 0, error.start) + 1
        text = content.decode(errors="replace")
    else:
        if "\x00" not in text:
            return text, []
        line = text.count("\n", 0, text.index("\x00")) + 1
    return text.replace("\x00", "�"), [dsl.Fault(line, _NOT_TEXT)]


def _kind(document: Document, item: Item | None) -> dsl.DocumentKind:
    if item is None:
        if document.role_code is DocumentRole.DRAFT:
            return dsl.DocumentKind.DRAFT
        return dsl.DocumentKind.HANDBOOK
    if item.kind_code == OPENING:
        return dsl.DocumentKind.OPENING
    if document.source_path is not None:
        return dsl.DocumentKind.REGISTERED_ITEM
    return dsl.DocumentKind.OWN_ITEM


def _published(document: Document) -> str:
    # Every document is born published.
    assert document.published_text is not None
    return document.published_text


def _unless(tree: bytes, save: bytes) -> bytes | None:
    """The bytes the file must hold, none when the save already holds them."""
    return None if tree == save else tree
