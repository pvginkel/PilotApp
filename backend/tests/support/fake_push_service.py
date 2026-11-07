"""The fake push service served over real HTTP, as the web push service meets
a browser's; and the stage's key, minted at run time."""

import threading
from collections.abc import Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dependency_injector import providers
from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response

from app.services.container import ServiceContainer
from app.services.fake_push_service import FakePushService, FakeSubscription
from app.services.web_push import WebPushService
from tests.support.supervisor import WAIT_SECONDS


def mint_vapid_key() -> str:
    """A fresh P-256 private key in PKCS#8 PEM, the form of a stage's key."""
    return (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )


class ServedFakePushService(FakePushService):
    """The fake, served on a free port of 127.0.0.1 by a thread of its own;
    `url` is its base URL. `on_push` runs once, after it took the next push
    and before it answers it: a push in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.on_push: Callable[[], None] | None = None
        self._holding = threading.Lock()
        self._hold_until = 0
        self._held = 0
        self._all_held = threading.Event()
        self._server = make_server("127.0.0.1", 0, self, threaded=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="fake-push-service",
            daemon=True,
        )
        self._thread.start()

    def browser(self, application_server_key: str) -> FakeSubscription:
        """A browser subscribed with `application_server_key`, its endpoint
        this server's."""
        return self.subscribe(application_server_key, origin=self.url)

    def hold(self, pushes: int) -> threading.Event:
        """Hold each push from now on in flight, after it took it and before
        it answers it, until `pushes` of them are held at once, or for
        WAIT_SECONDS; each after those is answered at once. The event is set
        once they were held at once."""
        with self._holding:
            self._hold_until = pushes
            self._held = 0
            self._all_held.clear()
        return self._all_held

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def _respond(self, request: Request) -> Response:
        response = super()._respond(request)
        if not request.path.startswith("/push/"):
            return response
        self._hold()
        hook = self.on_push
        if hook is not None:
            self.on_push = None
            hook()
        return response

    def _hold(self) -> None:
        with self._holding:
            if self._hold_until == 0:
                return
            self._held += 1
            if self._held >= self._hold_until:
                self._all_held.set()
        self._all_held.wait(WAIT_SECONDS)


def web_push_of(container: ServiceContainer, private_key: str) -> WebPushService:
    """The real web push service under ``private_key``, made ``container``'s."""
    service = WebPushService(
        private_key=private_key,
        contact=container.config().baseurl,
    )
    container.web_push_service.override(providers.Object(service))
    return service
