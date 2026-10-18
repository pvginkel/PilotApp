"""The fake sidecar's engine-facing half (design 1 §11): the store's tree and
the sidecar's shadow as dicts, the engine's ingest called as the file put
calls it, and the change events the bus delivers applied as the sidecar
applies them. Slice 003 adds the HTTP half."""

from app.database import scoped_session
from app.engine.bus import EngineEvent, TreeHashMoved
from app.engine.ingest import Ingested
from app.models import Environment
from app.models import Session as AgentSession
from app.services.container import ServiceContainer


class FakeSidecar:
    """The sidecar of the store's environment, with `/work/Projects` as
    `tree`: path to bytes, the paths from the tree's root.

    `shadow` holds each path's hash as last synced. `events` is every event
    the bus delivered since the sidecar started, in order.
    """

    def __init__(self, container: ServiceContainer, environment: Environment) -> None:
        self.container = container
        self.environment = environment
        self.tree: dict[str, bytes] = {}
        self.shadow: dict[str, str] = {}
        self.events: list[EngineEvent] = []
        self._drained = 0
        container.engine_bus().subscribe(self.events.append)

    def close(self) -> None:
        self.container.engine_bus().unsubscribe(self.events.append)

    def save(
        self,
        path: str,
        content: str | bytes,
        session: AgentSession | None = None,
    ) -> Ingested:
        """The agent writes `path`: the sidecar puts the file with its shadow
        hash as the base, writes the bytes the answer carries in place, and
        records the answer's hash."""
        data = content.encode() if isinstance(content, str) else content
        self.tree[path] = data
        with scoped_session(self.container):
            answer = self.container.ingest_service().ingest(
                path, data, self.shadow.get(path), self.environment, session
            )
        if answer.content is not None:
            self.tree[path] = answer.content
        self.shadow[path] = answer.hash
        return answer

    def drain(self) -> list[str]:
        """Apply the change events delivered since the last drain: fetch and
        write each path whose hash differs from the shadow; an event of the
        sidecar's own write is ignored. Returns the paths fetched, in
        order."""
        fetched: list[str] = []
        while self._drained < len(self.events):
            event = self.events[self._drained]
            self._drained += 1
            if not isinstance(event, TreeHashMoved):
                continue
            if self.shadow.get(event.path) == event.hash:
                continue
            with scoped_session(self.container):
                file = self.container.tree_service().read(event.path)
            self.tree[event.path] = file.content
            self.shadow[event.path] = file.hash
            fetched.append(event.path)
        return fetched

    def text(self, path: str) -> str:
        """What the agent reads at `path`."""
        return self.tree[path].decode()
