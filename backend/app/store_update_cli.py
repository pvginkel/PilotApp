"""`update-store`: the operator's update of the store while Pilot runs (F144.1;
design 5 D1, D2).

The command writes and reads the Store Update row and nothing else. The CLI
builds the app without its background services and fires no STARTUP, so it
tells no listener: the server takes the row up from the record, runs the
update and lifts it, and the command prints each phase as the server writes
it.
"""

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import click

from app.app import App
from app.database import scoped_session
from app.exceptions import InvalidOperationException
from app.models import StoreUpdate
from app.services.store_update_service import utc_time

POLL_SECONDS = 2.0
"""How often a waiting command reads the row again."""


@click.command()
@click.option(
    "--no-wait", is_flag=True, help="Return once the hold is set, or the lift asked."
)
@click.option(
    "--lift",
    is_flag=True,
    help=(
        "Ask the server to skip what remains of the update under way, retry "
        "what it stopped and lift the hold."
    ),
)
@click.pass_context
def update_store(ctx: click.Context, no_wait: bool, lift: bool) -> None:
    """Hold Pilot's chats and jobs while the server stops, resets and starts
    the store, and wait for the server to lift the hold."""
    handle_update_store(ctx.obj["app"], lift=lift, wait=not no_wait)


@dataclass(frozen=True)
class _Read:
    """What one read of the row tells."""

    update_id: int
    lines: list[str]
    error: str | None
    lifted: bool

    @classmethod
    def of(cls, update: StoreUpdate) -> "_Read":
        lines = [
            f"Update made at {utc_time(update.made_at)}: "
            "Pilot's chats and jobs are held."
        ]
        for at, words in (
            (update.stopped_at, "The store's chats and jobs stopped at {}."),
            (update.reset_at, "The store reset and running again at {}."),
            (update.reconciled_at, "The store's tree written down again at {}."),
            (
                update.lift_requested_at,
                "Lift asked at {}: the server skips what remains, retries "
                "what the update stopped and lifts the hold.",
            ),
            (update.lifted_at, "Lifted at {}: Pilot's chats and jobs go on."),
        ):
            if at is not None:
                lines.append(words.format(utc_time(at)))
        return cls(update.id, lines, update.error, update.lifted_at is not None)


class _Report:
    """Prints each line once, as it first appears, and the row's `error`
    each time it appears anew."""

    def __init__(self) -> None:
        self._printed: set[str] = set()
        self._error: str | None = None

    def show(self, read: _Read) -> None:
        for line in read.lines:
            if line not in self._printed:
                print(line, flush=True)
                self._printed.add(line)
        if read.error is not None and read.error != self._error:
            print(
                f"The update's last attempt failed, the server tries again: {read.error}",
                flush=True,
            )
        self._error = read.error


def handle_update_store(
    app: App,
    *,
    lift: bool,
    wait: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Make an update, or ask the lift of the one under way, and, waiting,
    print each phase until the lift; exits 1 at a refusal."""
    container = app.container
    with app.app_context():
        try:
            with scoped_session(container):
                service = container.store_update_service()
                read = _Read.of(service.request_lift() if lift else service.make())
        except InvalidOperationException as refused:
            print(refused.message, file=sys.stderr)
            if not lift:
                print(
                    "`update-store --lift` asks the server to lift it.",
                    file=sys.stderr,
                )
            sys.exit(1)
        report = _Report()
        report.show(read)
        while wait and not read.lifted:
            sleep(POLL_SECONDS)
            with scoped_session(container):
                read = _Read.of(container.store_update_service().get(read.update_id))
            report.show(read)
