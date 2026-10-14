"""Custom Flask application class with typed container attribute."""

from typing import TYPE_CHECKING, cast

from flask import Flask, current_app

from app.services.container import ServiceContainer

if TYPE_CHECKING:
    from app.services.diagnostics_service import DiagnosticsService


class App(Flask):
    container: ServiceContainer
    diagnostics_service: "DiagnosticsService"


def current_container() -> ServiceContainer:
    """Return the service container of the app handling the current request.

    ``current_app`` is typed as plain ``Flask``; the factory only ever builds
    an ``App``, which is what carries the container.
    """
    return cast(App, current_app).container
