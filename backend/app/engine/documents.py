"""Documents: born in the record, and published with their derived caches
(TD §7.1.3, DB §7.4, design 1 §7).

`publish()` is the one way a published text changes in the record (DB 172):
an agent's merged save and the record's own writes go through it.
"""

import re
import unicodedata
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import dsl
from app.engine.bus import EngineBus, TreeHashMoved
from app.engine.paths import DRAFT, HANDBOOK, sha256_hex, tree_path
from app.engine.tree import TreeService
from app.engine.views import ViewService
from app.exceptions import InvalidOperationException
from app.models import (
    Block,
    BlockOption,
    Document,
    DocumentVersion,
    Item,
    ItemKind,
    Project,
    User,
)
from app.models import Session as AgentSession
from app.models.reference import (
    AnswerChannel,
    BlockKind,
    DocumentRole,
    VersionCause,
)

OPENING = "opening"
CONFIRMATION = "confirmation"
DOCUMENT = "document"
PROSE = "prose"

_FILE_SLUG_LENGTH = 60


class DocumentService:
    def __init__(
        self,
        db: Session,
        engine_bus: EngineBus,
        tree_service: TreeService,
        view_service: ViewService,
    ) -> None:
        self.db = db
        self.engine_bus = engine_bus
        self.tree_service = tree_service
        self.view_service = view_service

    def bear_draft(self, project: Project, text: str = "") -> Document:
        """The project's draft, `project.md`, born at the plus."""
        return self._bear_project_document(project, DocumentRole.DRAFT, DRAFT, text)

    def bear_handbook(self, project: Project, text: str = "") -> Document:
        """The project's handbook, `handbook.md`, born at Create project."""
        return self._bear_project_document(
            project, DocumentRole.HANDBOOK, HANDBOOK, text
        )

    def bear_item(
        self,
        project: Project,
        kind: str,
        title: str,
        session: AgentSession,
        text: str = "",
    ) -> Item:
        """A prose item of Pilot's own that `session` added, of a prose kind
        but the opening, titled as added until its text gives a title."""
        item_kind = self.db.get(ItemKind, kind)
        if item_kind is None or item_kind.form != PROSE or kind == OPENING:
            raise InvalidOperationException(
                f"add a {kind} item to project {project.id}",
                f"{kind} is not a kind of prose item Pilot adds",
            )
        return self._bear_item(
            project,
            Item(kind_code=kind, title=title, created_by_session_id=session.id),
            text,
            session.id,
        )

    def bear_opening(self, project: Project, title: str, user: User, text: str) -> Item:
        """The opening, the words of `user` that started the project, born at
        Create project. Its kind and title are fixed at birth."""
        return self._bear_item(
            project,
            Item(kind_code=OPENING, title=title, created_by_user_id=user.id),
            text,
            None,
        )

    def publish(self, document: Document, text: str) -> None:
        """Publish `text` as the document's truth and rebuild every cache read
        from it, in the transaction. Refused for a text with a fault: only a
        parseable text is published (F78)."""
        project, item = self._owner(document)
        parsed = self._parse(project, document, text)
        tree_hash = self.tree_service.hash(project, document)
        shown = self._shown(project, item, document)
        self._set_published(document, text)
        self._rebuild(project, item, document, parsed)
        moved = self.tree_service.hash(project, document)
        if moved != tree_hash:
            self.engine_bus.emit(
                TreeHashMoved(tree_path(project, document.path), moved)
            )
        if self._shown(project, item, document) != shown:
            self.view_service.timeline_moved(project)

    def _bear_project_document(
        self, project: Project, role: DocumentRole, path: str, text: str
    ) -> Document:
        document = Document(
            id=uuid.uuid4(), path=path, project_id=project.id, role_code=role
        )
        parsed = self._parse(project, document, text)
        self._bear(project, None, document, text, parsed, None)
        return document

    def _bear_item(
        self, project: Project, item: Item, text: str, session_id: uuid.UUID | None
    ) -> Item:
        # Births in one project take their `seq` one at a time.
        self.db.execute(
            select(Project.id).where(Project.id == project.id).with_for_update()
        )
        seq = (
            self.db.scalar(
                select(func.max(Item.seq)).where(Item.project_id == project.id)
            )
            or 0
        ) + 1
        item.id = uuid.uuid4()
        item.project_id = project.id
        item.seq = seq
        document = Document(id=item.id, path=_item_path(seq, item.title))
        parsed = self._parse(project, document, text)
        self.db.add(item)
        self._bear(project, item, document, text, parsed, session_id)
        self.view_service.timeline_moved(project)
        return item

    def _bear(
        self,
        project: Project,
        item: Item | None,
        document: Document,
        text: str,
        parsed: dsl.ParsedDocument,
        session_id: uuid.UUID | None,
    ) -> None:
        self._set_published(document, text)
        self.db.add(document)
        self.db.flush()
        self.db.add(
            DocumentVersion(
                document_id=document.id,
                number=1,
                cause_code=VersionCause.BORN,
                text=text,
                hash=document.published_hash,
                session_id=session_id,
            )
        )
        self.db.flush()
        self._rebuild(project, item, document, parsed)
        self.engine_bus.emit(
            TreeHashMoved(
                tree_path(project, document.path),
                self.tree_service.hash(project, document),
            )
        )

    def _owner(self, document: Document) -> tuple[Project, Item | None]:
        if document.project_id is not None:
            return self.db.get_one(Project, document.project_id), None
        item = self.db.get_one(Item, document.id)
        return self.db.get_one(Project, item.project_id), item

    def _parse(
        self, project: Project, document: Document, text: str
    ) -> dsl.ParsedDocument:
        parsed = dsl.parse(text)
        if parsed.faults:
            faults = "; ".join(
                f"line {fault.line}: {fault.message}"
                if fault.line is not None
                else fault.message
                for fault in parsed.faults
            )
            raise InvalidOperationException(
                f"publish {tree_path(project, document.path)}",
                f"its text holds a fault: {faults}",
            )
        return parsed

    @staticmethod
    def _set_published(document: Document, text: str) -> None:
        document.published_text = text
        document.published_hash = sha256_hex(text)
        document.published_at = datetime.now(UTC)

    @staticmethod
    def _shown(
        project: Project, item: Item | None, document: Document
    ) -> tuple[object, ...]:
        """The caches of the document that `timeline.json` shows."""
        if item is not None:
            return (
                item.kind_code,
                item.title,
                item.plan_task_id,
                item.urgent,
                item.for_user_id,
                document.summary,
            )
        if document.role_code is DocumentRole.DRAFT:
            return (project.name,)
        return ()

    def _rebuild(
        self,
        project: Project,
        item: Item | None,
        document: Document,
        parsed: dsl.ParsedDocument,
    ) -> None:
        front_matter = parsed.front_matter
        users = self._users(
            {block.by for block in parsed.blocks if block.by is not None}
            | ({front_matter.addressee} if front_matter.addressee else set())
        )
        self._rebuild_blocks(document, parsed.blocks, users)
        if item is None:
            if document.role_code is DocumentRole.DRAFT:
                project.name = parsed.title
            return
        if item.kind_code == OPENING:
            return
        document.summary = front_matter.summary
        item.kind_code = _kind(item, parsed.blocks)
        if parsed.title is not None:
            item.title = parsed.title
        item.plan_task_id = front_matter.step
        item.urgent = front_matter.urgent
        item.for_user_id = (
            None if front_matter.addressee is None else users[front_matter.addressee]
        )

    def _rebuild_blocks(
        self,
        document: Document,
        parsed: tuple[dsl.Block, ...],
        users: dict[str, uuid.UUID],
    ) -> None:
        """The Blocks rewritten in place by local id, never replaced; a Block
        the text no longer holds is deleted, its options with it."""
        rows = {
            row.local_id: row
            for row in self.db.scalars(
                select(Block).where(Block.document_id == document.id)
            )
        }
        written: list[tuple[Block, dsl.Block]] = []
        for position, block in enumerate(parsed, start=1):
            row = rows.pop(block.local_id, None)
            if row is None:
                row = Block(document_id=document.id, local_id=block.local_id)
                self.db.add(row)
            _write_block(row, position, block, users)
            written.append((row, block))
        for gone in rows.values():
            self.db.delete(gone)
        self.db.flush()

        options: dict[int, list[BlockOption]] = {}
        for option in self.db.scalars(
            select(BlockOption)
            .where(BlockOption.block_id.in_([row.id for row, _ in written]))
            .order_by(BlockOption.position)
        ):
            options.setdefault(option.block_id, []).append(option)
        for row, block in written:
            held = options.get(row.id, [])
            choices = [(o.label, o.text, o.recommended) for o in block.options]
            if [(o.label, o.text, o.recommended) for o in held] == choices:
                continue
            for option in held:
                self.db.delete(option)
            self.db.add_all(
                BlockOption(
                    block_id=row.id,
                    position=position,
                    label=label,
                    text=text,
                    recommended=recommended,
                )
                for position, (label, text, recommended) in enumerate(choices, start=1)
            )
        self.db.flush()

    def _users(self, handles: set[str]) -> dict[str, uuid.UUID]:
        return dict(
            self.db.execute(
                select(User.handle, User.id).where(User.handle.in_(handles))
            ).all()
        )


def _write_block(
    row: Block, position: int, block: dsl.Block, users: dict[str, uuid.UUID]
) -> None:
    row.position = position
    row.kind_code = BlockKind(block.kind.value)
    row.confirmation = block.confirmation
    row.because_code = block.because
    row.proposal = block.proposal
    row.default_value = block.default
    row.check_text = block.check
    row.answer = block.answer
    row.answered_by_user_id = None if block.by is None else users[block.by]
    row.answered_at = block.at
    row.note = block.note
    row.via_code = None if block.via is None else AnswerChannel(block.via)
    row.done_at = block.done
    row.deferred_to_task_id = (
        block.to if block.answer == dsl.DEFERRED and block.to != dsl.PLAN else None
    )


def _kind(item: Item, blocks: tuple[dsl.Block, ...]) -> str:
    """One block gives its kind, a confirmation block makes a confirmation,
    several give `document`, none keeps the kind declared at birth (DB
    decision 2): a non-draft document never loses a block."""
    if len(blocks) > 1:
        return DOCUMENT
    if len(blocks) == 1:
        return CONFIRMATION if blocks[0].confirmation else blocks[0].kind.value
    return item.kind_code


def _item_path(seq: int, title: str) -> str:
    """`items/<seq>-<slug>.md`, the number as written (DB decision 35), the
    slug the title's ASCII letters and digits."""
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    if len(slug) > _FILE_SLUG_LENGTH:
        cut = slug[: _FILE_SLUG_LENGTH + 1]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else slug[:_FILE_SLUG_LENGTH]
    return f"items/{seq}-{slug}.md" if slug else f"items/{seq}.md"
