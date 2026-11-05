"""The engine's side of the file put (design 1 §5.3): an agent's save of a
path of the store's tree, gated, merged by ownership and published, in one
transaction that holds the document's row, an item of Pilot's own closed by the
save that writes its last open block's `done`; and what the reconcile's
write-down does to a held `plan.json` (§5.5 step 2)."""

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import pilot_dsl as dsl
from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.engine.bus import (
    DocumentModified,
    EngineBus,
    ErrorsRaised,
    ErrorsResolved,
    ProjectChanged,
    TreeHashMoved,
)
from app.engine.documents import OPENING, DocumentService
from app.engine.paths import PLAN, sha256_hex
from app.engine.plan import PlanService
from app.engine.record import RecordService
from app.engine.tree import TreeDocument, TreeFile, TreePlan, TreeService
from app.engine.views import ViewService
from app.models import (
    Document,
    Environment,
    Item,
    PlanTask,
    Project,
    SaveError,
    Turn,
    User,
)
from app.models import Session as AgentSession
from app.models.reference import DocumentRole, ErrorKind, ProjectState

_NOT_TEXT = (
    "the file is not UTF-8 text: each sequence that is not, and each NUL,"
    " is replaced by U+FFFD"
)


class PathKind(StrEnum):
    """What a path of the tree names."""

    DOCUMENT = "document"
    PLAN = "plan"
    VIEW = "view"
    """A read-only path: a rendered view, or an attachment."""


@dataclass(frozen=True)
class Ingested:
    """What the file put answers (design 1 §5.1).

    `kind` is what the path names; `content` the bytes the file must now
    hold, none when the save is them; `hash` the path's tree hash, but a
    held `plan.json` save's own, which the answer acknowledges (design 1 §5.3
    step 3); `stale` whether the base hash was not the path's tree hash when
    the save came. `faults` are those the save raised on the path: `parse`
    faults when it is `held`, else `reverted`.
    """

    kind: PathKind
    content: bytes | None
    hash: str
    stale: bool
    held: bool
    faults: tuple[dsl.Fault, ...]


@dataclass(frozen=True)
class WorkerVersion:
    """A registered document's file as its worker's turn left it: its text,
    and every fault it holds."""

    text: str
    faults: tuple[dsl.Fault, ...]


class IngestService:
    def __init__(
        self,
        db: Session,
        engine_bus: EngineBus,
        tree_service: TreeService,
        view_service: ViewService,
        document_service: DocumentService,
        plan_service: PlanService,
        record_service: RecordService,
    ) -> None:
        self.db = db
        self.engine_bus = engine_bus
        self.tree_service = tree_service
        self.view_service = view_service
        self.document_service = document_service
        self.plan_service = plan_service
        self.record_service = record_service

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
        when it has none; `session` the Session the save is credited to, the
        one that held the write lock of the path's project folder, none when
        it is no Session's (design 1 §7). A document's save while that
        Session has a Turn in flight has it writing the document until its
        turn ends; one that lands after its turn ended cuts the Session's
        `turn` Version at once, where the published text moved, and a held
        one cuts nothing.

        A read-only path stores nothing and is answered with its projection.
        A save of `plan.json` writes the plan's rows, or on any fault changes
        nothing, and is stored nowhere. A document's save is stored as its
        ingest and held on any fault, else merged by ownership against the
        published text and published; the opening's is never read, and one
        that differs is reverted whole, never held. Either's faults replace
        the path's `parse` Save Errors. A published save of an item of
        Pilot's own that writes the `done` of its last open block closes it
        (`RecordService.done_by_its_save`). Refused for a path the store does
        not sync.
        """
        resolved = self.tree_service.resolve(path)
        if isinstance(resolved, TreeFile):
            return Ingested(
                kind=PathKind.VIEW,
                content=_unless(resolved.content, content),
                hash=resolved.hash,
                stale=base_hash != resolved.hash,
                held=False,
                faults=(),
            )
        if isinstance(resolved, TreePlan):
            return self._ingest_plan(
                path, resolved.project, content, base_hash, environment
            )
        return self._ingest_document(
            path, resolved, content, base_hash, environment, session
        )

    def worker_version(self, project: Project, content: bytes) -> WorkerVersion:
        """`content`, the bytes of a registered document's file as its
        worker's turn left it, read as a text of `project`'s: its bytes'
        faults, its own and those against the record, in line order, outside
        the title rule (`dsl.DocumentKind.WORKER_VERSION`)."""
        text, faults = _decoded(content)
        facts = self._facts(project, dsl.DocumentKind.WORKER_VERSION, {})
        return WorkerVersion(
            text,
            tuple(_in_line_order([*faults, *dsl.validate(dsl.parse(text), facts)])),
        )

    def born_faults(self, project: Project, text: str) -> tuple[dsl.Fault, ...]:
        """`text`, the text an item of Pilot's own is to be born with in
        `project`, read as a save of it is: every fault it holds, its own and
        those against the record, the title rule's among them, in line order
        (`dsl.DocumentKind.OWN_ITEM`). A block's `by` naming a person is a
        fault too: a born text has no published one to hold that person's
        answer (§6.4)."""
        facts = self._facts(project, dsl.DocumentKind.OWN_ITEM, {})
        parsed = dsl.parse(text)
        persons = [
            dsl.Fault(
                block.lines["by"].first,
                f"block {block.local_id}: `by: {block.by}` is {block.by}'s answer,"
                " which the record does not hold",
            )
            for block in parsed.blocks
            if block.by is not None and block.by != dsl.AGENT
        ]
        return tuple(_in_line_order([*dsl.validate(parsed, facts), *persons]))

    def write_down(self, paths: Iterable[str]) -> None:
        """The reconcile writes `paths`, from the tree's root, down from the
        record (design 1 §5.5 step 2). A held `plan.json` among them is
        written down canonical, so the save that raised its `parse` Save
        Errors leaves the disk and they go with it: the one case where a
        projection clears errors."""
        plans = [path for path in paths if path.partition("/")[2] == PLAN]
        held = self.db.scalars(
            select(SaveError.path)
            .where(SaveError.kind_code == ErrorKind.PARSE, SaveError.path.in_(plans))
            .distinct()
            .order_by(SaveError.path)
        ).all()
        for path in held:
            resolved = self.tree_service.resolve(path)
            assert isinstance(resolved, TreePlan)
            self.plan_service.lock(resolved.project)
            # A clean save of the plan that took the lock first cleared them.
            if self.tree_service.held_path(path):
                self._clear(path)
                self.engine_bus.emit(ErrorsResolved(resolved.project.id, path))

    def _ingest_plan(
        self,
        path: str,
        project: Project,
        content: bytes,
        base_hash: str | None,
        environment: Environment,
    ) -> Ingested:
        """Design 1 §5.3 step 3: the rows written and the answer the canonical
        rendering when it differs from the save; or, held, nothing changed and
        the save's hash acknowledged, the tree hash staying the rendering's."""
        self.plan_service.lock(project)
        tree = self.plan_service.render(project)
        held_before = self.tree_service.held_path(path)
        self._clear(path)
        faults = self.plan_service.save(project, content)
        if faults:
            self._raise(environment, path, ErrorKind.PARSE, faults)
            self.engine_bus.emit(ErrorsRaised(project.id, path))
            return Ingested(
                kind=PathKind.PLAN,
                content=None,
                hash=hashlib.sha256(content).hexdigest(),
                stale=base_hash != tree.hash,
                held=True,
                faults=tuple(faults),
            )
        canonical = self.plan_service.render(project)
        if canonical.hash != tree.hash:
            self.engine_bus.emit(TreeHashMoved(path, canonical.hash))
            self.engine_bus.emit(ProjectChanged(project.id))
        if held_before:
            self.engine_bus.emit(ErrorsResolved(project.id, path))
        return Ingested(
            kind=PathKind.PLAN,
            content=_unless(canonical.text.encode(), content),
            hash=canonical.hash,
            stale=base_hash != tree.hash,
            held=False,
            faults=(),
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
        own = (
            item
            if item is not None
            and _kind(project, document, item) is dsl.DocumentKind.OWN_ITEM
            and self.record_service.pilots_own(item)
            else None
        )
        if own is not None:
            # The save may close the item: it takes the lock a close takes,
            # the project's row before the Session's and the document's (the
            # start's lock order).
            self.document_service.lock_project(project)
        in_turn = session is not None and self._in_turn(session)
        self.document_service.lock(document)
        held_before = self.tree_service.held(project, document)
        tree_hash = self.tree_service.hash(project, document)

        text, faults = _decoded(content)
        taken = self._store(document, text, session, in_turn)
        self._clear(path)
        kind = _kind(project, document, item)
        if kind is dsl.DocumentKind.OPENING:
            # The opening is never read: the merge reverts a save that differs,
            # whatever it holds (DB decision 2).
            faults = []
        else:
            facts = self._facts(project, kind, _published_to(document))
            faults = _in_line_order([*faults, *dsl.validate(dsl.parse(text), facts)])
        held = bool(faults)
        if held:
            self._raise(environment, path, ErrorKind.PARSE, faults)
            tree_text = text
        else:
            before = _published(document)
            merged = dsl.merge(before, text, kind)
            self.document_service.publish(document, merged.text)
            faults = list(merged.reverted)
            self._raise(environment, path, ErrorKind.REVERTED, faults)
            tree_text = merged.text
            if own is not None:
                self.record_service.done_by_its_save(project, own, document, before)
        # No turn end is left to cut the Version of a save that landed after
        # its session's turn ended.
        versioned = (
            session is not None
            and not in_turn
            and not held
            and self.document_service.cut_turn_version(document, session.id)
        )

        moved = self.tree_service.hash(project, document)
        if moved != tree_hash:
            self.engine_bus.emit(TreeHashMoved(path, moved))
        self.engine_bus.emit(DocumentModified(project.id, path))
        if held:
            self.engine_bus.emit(ErrorsRaised(project.id, path))
        elif held_before:
            self.engine_bus.emit(ErrorsResolved(project.id, path))
        if item is not None and held != held_before:
            # The item shows as a concept while its save is held (F78).
            self.engine_bus.emit(ProjectChanged(project.id))
        if taken or versioned:
            # Pilot's dots show on the document its session writes (F35), and
            # its Edited time is its latest `turn` Version's (F28.7).
            self.engine_bus.emit(ProjectChanged(project.id))
        return Ingested(
            kind=PathKind.DOCUMENT,
            content=_unless(tree_text.encode(), content),
            hash=moved,
            stale=base_hash != tree_hash,
            held=held,
            faults=tuple(faults),
        )

    def _in_turn(self, session: AgentSession) -> bool:
        """Whether `session` has a Turn in flight, read under its row's lock,
        held until the transaction ends: every end of a Turn takes that lock,
        so a save and its session's turn end are taken one after the other.
        Taken before the document's lock, the order a turn's end takes them
        in."""
        self.db.execute(
            select(AgentSession.id)
            .where(AgentSession.id == session.id)
            .with_for_update()
        )
        return bool(
            self.db.scalar(
                select(
                    exists().where(
                        Turn.session_id == session.id, Turn.ended_at.is_(None)
                    )
                )
            )
        )

    @staticmethod
    def _store(
        document: Document, text: str, session: AgentSession | None, in_turn: bool
    ) -> bool:
        """The save as the document's ingest, its session's (D077), and that
        session as the one writing it while its turn is in flight, `in_turn`
        (design 1 §7); whether that session took the document with it."""
        now = datetime.now(UTC)
        document.ingested_text = text
        document.ingested_hash = sha256_hex(text)
        document.ingested_at = now
        document.ingested_session_id = None if session is None else session.id
        if session is None or not in_turn or document.writing_session_id == session.id:
            return False
        document.writing_session_id = session.id
        document.writing_since = now
        return True

    def _clear(self, path: str) -> None:
        """The path's `parse` Save Errors, in every Environment, go: the save
        replaces them with its own."""
        self.db.execute(
            delete(SaveError).where(
                SaveError.path == path, SaveError.kind_code == ErrorKind.PARSE
            )
        )

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
        self,
        project: Project,
        kind: dsl.DocumentKind,
        published_to: Mapping[str, str],
    ) -> dsl.Facts:
        """What the record holds at the save; a `to` the published text has,
        `published_to`, is not checked again (DB 203)."""
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
            published_to=published_to,
        )


def _published_to(document: Document) -> dict[str, str]:
    """Each `to` of the document's published text, by its block's id."""
    return {
        block.local_id: block.to
        for block in dsl.parse(_published(document)).blocks
        if block.to is not None
    }


def _in_line_order(faults: list[dsl.Fault]) -> list[dsl.Fault]:
    """File order, the faults of the document as a whole last."""
    return sorted(faults, key=lambda fault: (fault.line is None, fault.line or 0))


def _decoded(content: bytes) -> tuple[str, list[dsl.Fault]]:
    """The save's text, and a fault at the first of its bytes PostgreSQL's
    `text` cannot hold: a sequence that is not UTF-8, or NUL. Each of those is
    replaced by U+FFFD."""
    nul = content.find(b"\x00")
    first = None if nul < 0 else nul
    try:
        text = content.decode()
    except UnicodeDecodeError as error:
        first = error.start if first is None else min(first, error.start)
        text = content.decode(errors="replace")
    if first is None:
        return text, []
    line = content.count(b"\n", 0, first) + 1
    return text.replace("\x00", "�"), [dsl.Fault(line, _NOT_TEXT)]


def _kind(project: Project, document: Document, item: Item | None) -> dsl.DocumentKind:
    if item is None:
        if (
            document.role_code is DocumentRole.DRAFT
            and project.state_code is ProjectState.DRAFT
        ):
            return dsl.DocumentKind.DRAFT
        # Past Create project `project.md` is no draft (F47.4): it takes the
        # handbook's rules, an answered block frozen, a dropped one restored
        # and its slug read by nothing (DB decision 1).
        return dsl.DocumentKind.HANDBOOK
    if item.kind_code == OPENING:
        return dsl.DocumentKind.OPENING
    if document.source_path is not None:
        return dsl.DocumentKind.REGISTERED_ITEM
    return dsl.DocumentKind.OWN_ITEM


def _published(document: Document) -> str:
    # Every document but a registered one is born published, and a registered
    # one has a file in the tree to save only once it has its text.
    assert document.published_text is not None
    return document.published_text


def _unless(tree: bytes, save: bytes) -> bytes | None:
    """The bytes the file must hold, none when the save already holds them."""
    return None if tree == save else tree
