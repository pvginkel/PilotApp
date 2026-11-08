"""`update-store`: the operator's update of the store while Pilot runs (F144.1;
design 5 D1, D2, D7).

The command writes the Store Update row and nothing else, and reads it and the
jobs the update stopped. The CLI builds the app without its background
services and fires no STARTUP, so it tells no listener: the server takes the
row up from the record, runs the update, retries the jobs it stopped and lifts
it, and the command prints each phase as the server writes it.
"""

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import click
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.app import App
from app.database import scoped_session
from app.exceptions import InvalidOperationException
from app.models import Item, Project, StoreUpdate, Work
from app.models import Session as AgentSession
from app.services.job_service import retry_refusal
from app.services.project_service import project_name
from app.services.store_update_service import stopped_by, utc_time

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
    def of(cls, db: Session, update: StoreUpdate) -> "_Read":
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
        ):
            if at is not None:
                lines.append(words.format(utc_time(at)))
        if update.lifted_at is not None:
            retries = _retries(db, update, update.lifted_at)
            if retries is not None:
                lines.append(retries)
            lines.append(
                f"Lifted at {utc_time(update.lifted_at)}: Pilot's chats and jobs go on."
            )
        return cls(update.id, lines, update.error, update.lifted_at is not None)


def _retries(db: Session, update: StoreUpdate, lifted_at: datetime) -> str | None:
    """What the lift did with the jobs the update stopped, as the record has
    them at `lifted_at`: how many a Retry placed before it, and each it left,
    its item open then and no retry placed, with why Retry refuses it now;
    None when it stopped neither kind."""
    retry = aliased(AgentSession)
    retried = 0
    left: list[str] = []
    for job, work, line, retried_at in db.execute(
        select(AgentSession, Work, Item, retry.created_at)
        .join(Work, Work.id == AgentSession.id)
        .join(Item, Item.id == AgentSession.id)
        .outerjoin(retry, retry.id == Work.retried_by_id)
        .where(stopped_by(update))
        .order_by(AgentSession.created_at, AgentSession.id)
    ):
        if retried_at is not None and retried_at <= lifted_at:
            retried += 1
        elif line.done_at is None or line.done_at > lifted_at:
            project = db.get_one(Project, job.project_id)
            refusal = retry_refusal(db, project, job, work, line)
            left.append(
                f"{line.title} in {project_name(project)}"
                + ("" if refusal is None else f" ({refusal})")
            )
    if not retried and not left:
        return None
    jobs = "no job" if not retried else "1 job" if retried == 1 else f"{retried} jobs"
    if not left:
        return f"Retried {jobs}."
    return f"Retried {jobs}; {len(left)} left to a person's Retry: {', '.join(left)}."


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
            with scoped_session(container) as db:
                service = container.store_update_service()
                read = _Read.of(db, service.request_lift() if lift else service.make())
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
            with scoped_session(container) as db:
                read = _Read.of(
                    db, container.store_update_service().get(read.update_id)
                )
            report.show(read)
