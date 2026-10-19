"""The store's sync (design 1 §5): the gate every sync call passes, and the
file put and get, moving the engine's values over the wire."""

import hmac
import re
import time
from typing import Literal

from prometheus_client import Counter, Histogram
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.app_config import AppSettings
from app.engine.ingest import Ingested, IngestService, PathKind
from app.engine.tree import TreeFile, TreeService
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

Outcome = Literal["published", "held", "reverted", "readonly"]

_VERSION = re.compile(r"[0-9]+")


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


def _outcome(answer: Ingested) -> Outcome:
    if answer.kind is PathKind.VIEW:
        return "readonly"
    if answer.held:
        return "held"
    if answer.faults:
        return "reverted"
    return "published"
