"""Side effects that must wait until the request's transaction has committed.

Service code calls :func:`after_commit` to schedule a callback — an outbound
notification, a cache purge, a pipeline trigger — that must only happen once
the request's database writes are durable. The ``teardown_request`` handler in
``create_app()`` runs the callbacks after a successful commit and drops them on
rollback, then clears them either way.

The callbacks live in a ``ContextVar``, not Flask's ``g``, so service code
stays Flask-free. Registering the same callback twice in one request runs it
once, so many writes coalesce into a single side effect.
"""

import contextvars
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

_callbacks: contextvars.ContextVar[tuple[Callable[[], None], ...]] = contextvars.ContextVar(
    "after_commit_callbacks", default=()
)


def after_commit(callback: Callable[[], None]) -> None:
    """Run ``callback`` once the current request's transaction has committed."""
    callbacks = _callbacks.get()
    if callback not in callbacks:
        _callbacks.set((*callbacks, callback))


def run_after_commit_callbacks() -> None:
    """Run the registered callbacks. Failures are logged, never raised."""
    for callback in _callbacks.get():
        try:
            callback()
        except Exception:
            logger.exception("after_commit callback %r failed", callback)


def clear_after_commit_callbacks() -> None:
    """Forget the registered callbacks without running them."""
    _callbacks.set(())
