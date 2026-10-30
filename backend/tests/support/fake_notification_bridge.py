"""The fake notification bridge served over real HTTP, as the client meets the
real one."""

import threading
from collections.abc import Callable

from dependency_injector import providers
from werkzeug.serving import make_server
from werkzeug.wrappers import Request, Response

from app.services.container import ServiceContainer
from app.services.fake_notification_bridge import FakeNotificationBridge
from app.services.health_service import HealthService
from app.services.notification_bridge_client import NotificationBridgeClient


class ServedFakeNotificationBridge(FakeNotificationBridge):
    """The fake, served on a free port of 127.0.0.1 by a thread of its own;
    `url` is its base URL."""

    def __init__(self) -> None:
        super().__init__()
        self._server = make_server("127.0.0.1", 0, self, threaded=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="fake-notification-bridge",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        super().close()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


class WatchedFakeNotificationBridge(ServedFakeNotificationBridge):
    """The served fake, which runs `on_submit` once, after it took the next
    submit and before it answers it: a submit in flight. What the hook
    raised is kept in `failures`."""

    def __init__(self) -> None:
        super().__init__()
        self.on_submit: Callable[[], None] | None = None
        self.failures: list[BaseException] = []

    def _respond(self, request: Request) -> Response:
        response = super()._respond(request)
        hook = self.on_submit
        if hook is not None and request.path == "/v1/submit":
            self.on_submit = None
            try:
                hook()
            except BaseException as error:
                self.failures.append(error)
        return response


def bridge_client_of(
    container: ServiceContainer, fake_bridge: ServedFakeNotificationBridge
) -> NotificationBridgeClient:
    """The real client on ``fake_bridge``, made ``container``'s client. Its
    readiness check is on a health service of its own."""
    client = NotificationBridgeClient(
        base_url=fake_bridge.url,
        health_service=HealthService(
            lifecycle_coordinator=container.lifecycle_coordinator(),
            settings=container.config(),
        ),
    )
    container.notification_bridge_client.override(providers.Object(client))
    return client
