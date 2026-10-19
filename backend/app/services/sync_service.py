"""The store's sync (design 1 §5): the gate every sync call passes, the file
put and get, and the manifest reconcile, moving the engine's values over the
wire."""

import hmac
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal

from prometheus_client import Counter, Histogram
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.app_config import AppSettings
from app.engine.ingest import Ingested, IngestService, PathKind
from app.engine.tree import ManifestEntry, TreeFile, TreeService
from app.exceptions import (
    AuthenticationException,
    AuthorizationException,
    SyncProtocolUnsupportedException,
)
from app.models import Environment
from app.models.reference import ErrorKind

SYNC_PROTOCOL_MIN = 1
"""The oldest protocol version the server serves."""

SYNC_PROTOCOL_MAX = 1
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


class SyncService:
    def __init__(
        self,
        db: Session,
        app_settings: AppSettings,
        ingest_service: IngestService,
        tree_service: TreeService,
    ) -> None:
        self.db = db
        self.app_settings = app_settings
        self.ingest_service = ingest_service
        self.tree_service = tree_service

    def admit(
        self,
        authorization: str | None,
        environment_id: str | None,
        protocol: str | None,
    ) -> None:
        """Let a sync call through, its three headers' values given, and make
        the store's Environment row if it has none.

        Refused, in this order: without the store's bearer, and always while
        `SYNC_TOKEN` is empty; from an environment other than
        `STORE_ENVIRONMENT_ID`, and always while that is empty; in a protocol
        version outside the accepted range. A refused call touches nothing.
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
        # `name` and `exempt` have no source before the controller client
        # (design 2 §13.1): the id stands in for the name.
        self.db.execute(
            insert(Environment)
            .values(id=store, name=store, exempt=False)
            .on_conflict_do_nothing(index_elements=[Environment.id])
        )

    def put(self, path: str, content: bytes, base_hash: str | None) -> Ingested:
        """The store's save of `path`, from the tree's root, with the hash its
        sidecar last synced for the path, none when it has none: the engine's
        ingest, its Save Errors keyed by the store's Environment, which
        `admit()` made."""
        started = time.perf_counter()
        environment = self.db.get_one(
            Environment, self.app_settings.store_environment_id
        )
        answer = self.ingest_service.ingest(path, content, base_hash, environment, None)
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


def _outcome(answer: Ingested) -> Outcome:
    if answer.kind is PathKind.VIEW:
        return "readonly"
    if answer.held:
        return "held"
    if answer.faults:
        return "reverted"
    return "published"
