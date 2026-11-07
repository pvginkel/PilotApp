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

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def _respond(self, request: Request) -> Response:
        response = super()._respond(request)
        hook = self.on_push
        if hook is not None and request.path.startswith("/push/"):
            self.on_push = None
            hook()
        return response


def web_push_of(container: ServiceContainer, private_key: str) -> WebPushService:
    """The real web push service under ``private_key``, made ``container``'s."""
    service = WebPushService(
        container=container,
        private_key=private_key,
        contact=container.config().baseurl,
    )
    container.web_push_service.override(providers.Object(service))
    return service
