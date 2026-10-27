"""The store's sync (design 1 §5): the gate every sync call passes, the file
put and get, the manifest reconcile and its hash, and the hook's check,
moving the engine's values over the wire."""

import hashlib
import hmac
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from prometheus_client import Counter, Histogram
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.app_config import AppSettings
from app.engine.ingest import Ingested, IngestService, PathKind
from app.engine.plan import HomelessDeferral, PlanService
from app.engine.tree import ManifestEntry, TreeFile, TreeService
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    SyncProtocolUnsupportedException,
)
from app.models import Environment, SaveError, SessionKind
from app.models import Session as AgentSession
from app.models.reference import ErrorKind, Surface
from app.services.environment_service import EnvironmentService

SYNC_PROTOCOL_MIN = 2
"""The oldest protocol version the server serves."""

SYNC_PROTOCOL_MAX = 2
"""The newest protocol version the server serves. A change to any request or
response shape of the sync routes bumps it, and the sidecar's own version, in
one commit (design 1 §5.1)."""

INGEST_SECONDS = Histogram(
    "pilot_sync_ingest_seconds",
    "A sync PUT, from received to answered",
    ["kind", "outcome"],
)
FAULTS_TOTAL = Counter(
    "pilot_sync_faults_total",
    "Save Errors the store's PUTs raised",
    ["kind"],
)
STALE_PUTS_TOTAL = Counter(
    "pilot_sync_stale_puts_total",
    "Sync PUTs whose base hash was not the path's tree hash",
)
RECONCILES_TOTAL = Counter(
    "pilot_sync_reconciles_total",
    "Manifest reconciles of the store's tree",
)
HOOK_WAIT_SECONDS = Histogram(
    "pilot_sync_hook_wait_seconds",
    "The store sidecar's flush of the project folder the hook checks, as it reports it",
)

logger = logging.getLogger(__name__)

Outcome = Literal["published", "held", "reverted", "readonly"]

_VERSION = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class Reconciled:
    """What the manifest reconcile answers (design 1 §5.5 step 2), each list
    in path order."""

    manifest: list[ManifestEntry]
    send_up: list[str]
    write_down: list[ManifestEntry]
    delete: list[str]


@dataclass(frozen=True)
class CheckedError:
    """A Save Error as the check reports it."""

    path: str
    kind: ErrorKind
    line: int | None
    message: str


@dataclass(frozen=True)
class Checked:
    """What the hook's check answers (design 1 §5.6 step 3)."""

    errors: list[CheckedError]
    homeless_deferrals: list[HomelessDeferral]


class SyncService:
    def __init__(
        self,
        db: Session,
        app_settings: AppSettings,
        ingest_service: IngestService,
        tree_service: TreeService,
        plan_service: PlanService,
        environment_service: EnvironmentService,
    ) -> None:
        self.db = db
        self.app_settings = app_settings
        self.ingest_service = ingest_service
        self.tree_service = tree_service
        self.plan_service = plan_service
        self.environment_service = environment_service

    def admit(
        self,
        authorization: str | None,
        environment_id: str | None,
        protocol: str | None,
    ) -> None:
        """Let a sync call through, its three headers' values given, and make
        the store's Environment row if it has none: from the controller's
        report while a controller is configured (`ensure_environment`), so
        the store's exemption holds from the row's first moment; without one,
        named by its id and not exempt.

        Refused, in this order: without the store's bearer, and always while
        `SYNC_TOKEN` is empty; from an environment other than
        `STORE_ENVIRONMENT_ID`, and always while that is empty; in a protocol
        version outside the accepted range. A refused call touches nothing.
        While the store has no row, a call let through fails, and makes none,
        when the controller does not report the store.
        """
        token = self.app_settings.sync_token
        if not token or not hmac.compare_digest(
            (authorization or "").encode(), f"Bearer {token}".encode()
        ):
            raise AuthenticationException(
                "Cannot sync because the request does not carry the store's bearer"
            )
        store = self.app_settings.store_environment_id
        if not store or environment_id != store:
            raise AuthorizationException(
                f"Cannot sync from environment {environment_id!r} because it is"
                " not the store's"
            )
        if (
            protocol is None
            or not _VERSION.fullmatch(protocol)
            or not SYNC_PROTOCOL_MIN <= int(protocol) <= SYNC_PROTOCOL_MAX
        ):
            raise SyncProtocolUnsupportedException(
                protocol, SYNC_PROTOCOL_MIN, SYNC_PROTOCOL_MAX
            )
        if self.app_settings.controller_url is not None:
            self.environment_service.ensure_environment(self.db, store)
            return
        self.db.execute(
            insert(Environment)
            .values(id=store, name=store, exempt=False)
            .on_conflict_do_nothing(index_elements=[Environment.id])
        )

    def put(
        self, path: str, content: bytes, base_hash: str | None, writer: str | None
    ) -> Ingested:
        """The store's save of `path`, from the tree's root, with the hash its
        sidecar last synced for the path, none when it has none: the engine's
        ingest, its Save Errors keyed by the store's Environment, which
        `admit()` made. `writer` is the Session the sidecar says held the
        write lock of the path's project folder as it read the file, none
        when none held it: the save is that Session's when it is a brain
        session, a chat's or a job's, of the syncing project whose folder
        holds the path; any other value is logged, and the save is no
        Session's."""
        started = time.perf_counter()
        environment = self.db.get_one(
            Environment, self.app_settings.store_environment_id
        )
        session = None if writer is None else self._writer(path, writer)
        answer = self.ingest_service.ingest(
            path, content, base_hash, environment, session
        )
        INGEST_SECONDS.labels(kind=answer.kind, outcome=_outcome(answer)).observe(
            time.perf_counter() - started
        )
        if answer.faults:
            fault_kind = ErrorKind.PARSE if answer.held else ErrorKind.REVERTED
            FAULTS_TOTAL.labels(kind=fault_kind).inc(len(answer.faults))
        if answer.stale:
            STALE_PUTS_TOTAL.inc()
        return answer

    def get(self, path: str) -> TreeFile:
        """The bytes `path`, from the tree's root, must hold, and their tree
        hash."""
        return self.tree_service.read(path)

    def manifest_hash(self) -> str:
        """The hash of the manifest as it stands, which the change stream's
        `hello` carries: the sha256 of its entries in path order, each its
        path, its tree hash and `1` for read-only or `0`, separated by NUL
        bytes and ended by a newline, in UTF-8."""
        digest = hashlib.sha256()
        for entry in self.tree_service.manifest():
            digest.update(
                f"{entry.path}\0{entry.hash}\0{int(entry.readonly)}\n".encode()
            )
        return digest.hexdigest()

    def reconcile(self, tree: dict[str, str], shadow: dict[str, str]) -> Reconciled:
        """The manifest, and what the sidecar does to its tree to match it,
        given the hash of each path on disk and of each path as it last
        synced it (design 1 §5.5 step 2).

        `write_down` is every path of the manifest whose tree hash is not the
        one on disk, `delete` every path synced that the manifest does not
        list. `send_up` is every path of the manifest whose hash on disk is
        not the one last synced: the sidecar sends those up before it asks,
        so the list is a cross-check, logged and never acted on. A file the
        record never bore is in neither the manifest nor the shadow, and so
        in no list.
        """
        manifest = self.tree_service.manifest()
        listed = {entry.path for entry in manifest}
        write_down = [entry for entry in manifest if tree.get(entry.path) != entry.hash]
        delete = sorted(set(shadow) - listed)
        send_up = sorted(
            path
            for path, disk_hash in tree.items()
            if path in listed and shadow.get(path) != disk_hash
        )
        self.ingest_service.write_down(entry.path for entry in write_down)
        RECONCILES_TOTAL.inc()
        logger.info(
            "Sync reconcile: %d paths listed, %d to write down, %d to delete",
            len(manifest),
            len(write_down),
            len(delete),
        )
        if send_up:
            logger.warning(
                "Sync reconcile: the store's sidecar had not sent up %s",
                ", ".join(send_up),
            )
        return Reconciled(manifest, send_up, write_down, delete)

    def check(self, folder: str, wait_seconds: float) -> Checked:
        """The hook's check of the project folder `folder`, from the tree's
        root, once the store's sidecar has flushed it, which took
        `wait_seconds` (design 1 §5.6 step 3).

        The errors are the Save Errors of the store's Environment under the
        folder, in path order: its `reverted` rows are deleted as they are
        read, so each is reported once, and its `parse` rows stand until a
        clean save of their path. With them, the deferrals without a home of
        the syncing project whose folder it is, none for a folder of no
        syncing project.
        """
        HOOK_WAIT_SECONDS.observe(wait_seconds)
        project = self.tree_service.project_in(folder)
        scope = (
            SaveError.environment_id == self.app_settings.store_environment_id,
            SaveError.path.startswith(f"{folder}/", autoescape=True),
        )
        columns = (
            SaveError.id,
            SaveError.path,
            SaveError.kind_code,
            SaveError.line,
            SaveError.message,
        )
        # One statement deletes what it returns: a `reverted` row committed
        # after it is the next check's to report.
        reverted = self.db.execute(
            delete(SaveError)
            .where(*scope, SaveError.kind_code == ErrorKind.REVERTED)
            .returning(*columns)
        ).all()
        parse = self.db.execute(
            select(*columns).where(*scope, SaveError.kind_code == ErrorKind.PARSE)
        ).all()
        errors = [
            CheckedError(row.path, row.kind_code, row.line, row.message)
            for row in sorted([*parse, *reverted], key=lambda row: (row.path, row.id))
        ]
        deferrals = (
            [] if project is None else self.plan_service.homeless_deferrals(project)
        )
        return Checked(errors, deferrals)

    def _writer(self, path: str, writer: str) -> AgentSession | None:
        """The Session `writer` names, when it is a brain session of the
        syncing project whose folder holds `path`; else none, logged."""
        project = self.tree_service.project_of(path)
        try:
            session_id = uuid.UUID(writer)
        except ValueError:
            session_id = None
        session = None if session_id is None else self.db.get(AgentSession, session_id)
        if (
            session is not None
            and project is not None
            and session.project_id == project.id
            and self.db.get_one(SessionKind, session.kind_code).surface == Surface.STORE
        ):
            return session
        logger.warning(
            "Sync PUT of %s: the store's sidecar credits it to %r, no brain"
            " session of the path's project; ingested as no Session's",
            path,
            writer,
        )
        return None


def _outcome(answer: Ingested) -> Outcome:
    if answer.kind is PathKind.VIEW:
        return "readonly"
    if answer.held:
        return "held"
    if answer.faults:
        return "reverted"
    return "published"
