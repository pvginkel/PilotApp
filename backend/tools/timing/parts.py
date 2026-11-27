"""The timing's parts (F154.9): each part of the engine this slice builds,
read over all time and over a quota week, timed on the history as it stands.

    DATABASE_URL=… uv run python -m tools.timing.parts --out results/630000.json

Each part is read through the app as the page reads it, its route through
the app's own client and a count's task by the service the task runs, under
the engine's bounds with a timeout long enough that nothing is refused: once
to warm the process and the database's cache, then `RUNS` times, or once
where that first read took longer than `LONG_MS`, its time the median. Its
statements are then read once more, each run again under `EXPLAIN (ANALYZE,
BUFFERS)`, so that a sort, a hashed grouping, a hash or a window that went
to disk at the cluster's `work_mem` is named with the statement that did. A burst reads the Projects view over all time from one
to `BURST` clients at once. The record's size on disk is the database's,
with its largest tables. A collector's call, Pilot's inventory, is read
under the collector's bearer, its token drawn for the timing where none is
set.

The each-item quick filter of R24 is added first where the record has none:
a conversation's cost over five dollars, coarser than the call.
"""

import argparse
import json
import os
import secrets
import statistics
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask
from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine

from app.exceptions import QueryRefusedException
from app.services.publication_service import COLLECTOR_PROTOCOL_MAX

RUNS = 3
"""The timed reads of a part; its time is their median."""

LONG_MS = 20_000
"""A part whose first read takes longer is timed once, not `RUNS` times."""

BURST = 4
"""The most reads of one view at once the burst times."""

TIMEOUT_SECONDS = 600
"""The engine's timeout while timing: no part is refused for its time."""

RANGES = ("all", "lqw")
"""Over all time, and over the quota week before the running one, the last
whole one."""

EACH_ITEM = "@items,gt,5,cost.sum.conversation"
"""R24's quick filter: an each-item one coarser than the call."""

EACH_ITEM_LABEL = "Costly conversations"


@dataclass(frozen=True)
class Part:
    """A part as the page asks it: a route and its query, or a task's
    count (`attributes`, `quick_filters`), on `state`, whose `{t}` is the
    range read and `{x}` the threshold that keeps fewer rows than all; or,
    where `collector`, a collector's call of the route, which takes no
    state."""

    key: str
    label: str
    state: str
    route: str | None = None
    query: tuple[tuple[str, str], ...] = ()
    ranges: tuple[str, ...] = RANGES
    collector: bool = False


PARTS = (
    Part(
        "rows",
        "Rows by project, five measures",
        "t={t}&by=project&m=cost.sum&m=tokens.sum&m=calls.count&m=r:overhead"
        "&m=r:per_call",
        "/api/dashboard/rows",
    ),
    Part(
        "projects",
        "The Projects view: four measures, colored by work type",
        "t={t}&by=project&m=cost.sum&m=tokens.sum&m=misses.sum&m=ctx.max&col=work_type",
        "/api/dashboard/rows",
    ),
    Part(
        "work_types",
        "The Work types view: four measures, colored by model",
        "t={t}&by=work_type&m=cost.sum&m=tokens.sum&m=misses.sum&m=ctx.max&col=model",
        "/api/dashboard/rows",
    ),
    Part(
        "medians",
        "Median, mean and P90 per conversation, by project",
        "t={t}&by=project&m=cost.median.conversation&m=cost.mean.conversation"
        "&m=cost.p90.conversation",
        "/api/dashboard/rows",
    ),
    Part(
        "threshold",
        "Rows by project under a threshold on the By's rows",
        "t={t}&by=project&m=cost.sum&m=calls.count&c=@rows,gt,{x},cost.sum",
        "/api/dashboard/rows",
    ),
    Part(
        "each_item",
        "Rows by project under a condition on each conversation",
        "t={t}&by=project&m=cost.sum&c=@items,gt,1,cost.sum.conversation",
        "/api/dashboard/rows",
    ),
    Part(
        "attributes",
        "The attributes' counts (By's panel), a task",
        "t={t}&by=project&m=cost.sum",
    ),
    Part(
        "quick_filters",
        "The quick filters' counts and amounts, an each-item one among them, a task",
        "t={t}&by=project&m=cost.sum",
    ),
    Part(
        "values_call",
        "An attribute's values for a filter's pane: the calls",
        "t={t}&by=project&m=cost.sum",
        "/api/dashboard/values",
        (("dimension", "call"),),
    ),
    Part(
        "values_conversation",
        "An attribute's values for a filter's pane: the conversations",
        "t={t}&by=project&m=cost.sum",
        "/api/dashboard/values",
        (("dimension", "conversation"),),
    ),
    Part(
        "day",
        "Over time by local day, colored by model",
        "t={t}&by=project&p=time,day&m=cost.sum&col=model",
        "/api/dashboard/series",
    ),
    Part(
        "weekday",
        "Over time by local weekday, colored by model",
        "t={t}&by=project&p=time,weekday&m=cost.sum&col=model",
        "/api/dashboard/series",
    ),
    Part(
        "hour",
        "Over time by local hour, colored by model",
        "t={t}&by=project&p=time,hod&m=cost.sum&col=model",
        "/api/dashboard/series",
    ),
    Part(
        "weeks",
        "Where the week went: by quota week, with the overhead, colored by source",
        "t={t}&by=project&p=time,qweek&m=cost.sum&m=r:overhead&col=source",
        "/api/dashboard/series",
        ranges=("all", "l8"),
    ),
    Part(
        "order",
        "In order: each Pilot session's cost by its start, with its band",
        "t={t}&by=psession&p=order&m=cost.sum",
        "/api/dashboard/series",
    ),
    Part(
        "strip",
        "The events strip of the series by day",
        "t={t}&by=project&p=time,day&m=cost.sum",
        "/api/dashboard/series/events",
    ),
    Part(
        "lanes",
        "The lanes by project",
        "t={t}&by=project&p=lanes&m=cost.sum",
        "/api/dashboard/lanes",
    ),
    Part(
        "lanes_conversation",
        "The lanes by conversation",
        "t={t}&by=conversation&p=lanes&m=cost.sum",
        "/api/dashboard/lanes",
    ),
    Part(
        "items",
        "The items: the conversations of the rows a threshold keeps",
        "t={t}&by=project&m=cost.sum&c=@rows,gt,{x},cost.sum&ig=conversation",
        "/api/dashboard/items",
    ),
    Part(
        "calls",
        "A conversation's calls: the longest thread's",
        "t={t}&by=conversation&m=cost.sum",
        "/api/dashboard/conversations/{conversation}/calls",
    ),
    Part(
        "kind_rows",
        "Rows by the widest kind of work: its units, their measure and the cost",
        "t={t}&by=errand&m=cost.sum&m=units.count&m=parts.sum",
        "/api/dashboard/rows",
    ),
    Part(
        "kind_color",
        "Rows by project, colored by the widest kind of work",
        "t={t}&by=project&m=cost.sum&col=errand",
        "/api/dashboard/rows",
    ),
    Part(
        "roles",
        "Rows by a unit's role, with the share of work done again",
        "t={t}&by=role&m=cost.sum&m=units.count&m=r:rework_share",
        "/api/dashboard/rows",
    ),
    Part(
        "kind_order",
        "In order: each leg by its start, its outliers judged among its role,"
        " with the marker of a role's configuration",
        "t={t}&by=leg&p=order&m=cost.sum",
        "/api/dashboard/series",
    ),
    Part(
        "kind_dots",
        "In order: each errand by its start, its conversations as dots, each"
        " with its role",
        "t={t}&by=errand&p=order&m=cost.median.conversation",
        "/api/dashboard/series",
    ),
    Part(
        "lanes_model",
        "The lanes by conversation, their runs colored by model",
        "t={t}&by=conversation&p=lanes&m=cost.sum&col=model",
        "/api/dashboard/lanes",
    ),
    Part(
        "inventory",
        "Pilot's inventory with what it hands the labeller, a collector's call",
        "",
        "/api/collector/inventory",
        ranges=("all",),
        collector=True,
    ),
)


@dataclass
class Statement:
    """A statement of a part's read as `EXPLAIN (ANALYZE, BUFFERS)` ran
    it: its time, the temporary blocks it wrote and the nodes that went to
    disk."""

    head: str
    ms: float
    temp_blocks: int
    spills: list[str]


class Refused(Exception):
    """A route's refusal at the engine's bounds, a finding of the timing's."""


@dataclass
class Timed:
    key: str
    label: str
    range: str
    state: str
    ms: float
    runs: list[float]
    temp_bytes: int
    statements: list[Statement] = field(default_factory=list)
    error: str | None = None


class _Captured:
    """The statements the app's engine sends while `on`."""

    def __init__(self, engine: Engine) -> None:
        self.on = False
        self.sent: list[tuple[str, Any]] = []
        self._lock = threading.Lock()
        event.listen(engine, "before_cursor_execute", self._sent)

    def _sent(
        self,
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if self.on and statement.lstrip()[:6].upper() in ("SELECT", "WITH ("):
            with self._lock:
                self.sent.append((statement, parameters))

    @contextmanager
    def capturing(self) -> Iterator[list[tuple[str, Any]]]:
        self.sent = []
        self.on = True
        try:
            yield self.sent
        finally:
            self.on = False


def _spills(node: dict[str, Any], found: list[str]) -> None:
    kind = node.get("Node Type", "")
    if node.get("Sort Space Type") == "Disk":
        found.append(f"{kind} to disk, {node.get('Sort Space Used')} kB")
    if node.get("HashAgg Batches", 1) > 1 or node.get("Disk Usage", 0) > 0:
        found.append(
            f"{kind} ({node.get('Strategy')}) to disk, "
            f"{node.get('HashAgg Batches')} batches, {node.get('Disk Usage')} kB"
        )
    if node.get("Hash Batches", 1) > 1:
        found.append(f"{kind} in {node.get('Hash Batches')} batches")
    if node.get("Storage") == "Disk":
        found.append(f"{kind} stored on disk, {node.get('Maximum Storage')} kB")
    for worker in node.get("Workers", []):
        if worker.get("Sort Space Type") == "Disk":
            found.append(
                f"{kind} to disk in a worker, {worker.get('Sort Space Used')} kB"
            )
    for child in node.get("Plans", []):
        _spills(child, found)


def explained(
    connection: Connection, sent: Sequence[tuple[str, Any]]
) -> list[Statement]:
    """Each statement `sent` run again under `EXPLAIN (ANALYZE, BUFFERS)`
    on `connection`, read only and with JIT off as the engine runs it, each
    in a savepoint rolled back."""
    found: list[Statement] = []
    for statement, parameters in sent:
        savepoint = connection.begin_nested()
        try:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(
                f"SET LOCAL statement_timeout = {TIMEOUT_SECONDS * 1000}"
            )
            connection.exec_driver_sql("SET LOCAL jit = off")
            plan: dict[str, Any] = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters
            ).scalar_one()[0]
        finally:
            savepoint.rollback()
        spilled: list[str] = []
        _spills(plan["Plan"], spilled)
        found.append(
            Statement(
                head=" ".join(statement.split())[:160],
                ms=round(plan["Execution Time"], 1),
                temp_blocks=plan["Plan"].get("Temp Written Blocks", 0),
                spills=spilled,
            )
        )
    return found


def timed_runs(first_ms: float) -> int:
    """The timed reads of a part whose first read took `first_ms`."""
    return RUNS if first_ms <= LONG_MS else 1


class Timing:
    """The parts read on `app`'s record."""

    def __init__(self, app: Flask) -> None:
        self.app = app
        self.container = app.container  # type: ignore[attr-defined]
        with app.app_context():
            self.engine: Engine = self.container.db_session().get_bind()
        self.captured = _Captured(self.engine)
        self.client = app.test_client()
        self.thresholds: dict[str, str] = {}
        token = self.container.app_config().collector_token
        self.collector = {
            "Authorization": f"Bearer {token}",
            "X-Pilot-Collector-Protocol": str(COLLECTOR_PROTOCOL_MAX),
        }

    def _scalar(self, sql: str) -> Any:
        with self.engine.connect() as connection:
            return connection.execute(text(sql)).scalar()

    def temp_bytes(self) -> int:
        return int(
            self._scalar(
                "SELECT temp_bytes FROM pg_stat_database WHERE datname = current_database()"
            )
        )

    def each_item_filter(self) -> None:
        with self.app.app_context():
            store = self.container.dashboard_store_service()
            if not any(q.condition == EACH_ITEM for q in store.quick_filters()):
                store.add_quick_filter(EACH_ITEM_LABEL, EACH_ITEM, "cost", None)
                self.container.db_session().commit()
            self.container.catalogue_service().drop()

    def facts(self) -> dict[str, Any]:
        """The record's size: its rows and its bytes on disk."""
        with self.engine.connect() as connection:
            counts = {
                table: connection.execute(
                    text(f"SELECT count(*) FROM {table}")
                ).scalar()
                for table in (
                    "calls",
                    "transcripts",
                    "launches",
                    "tool_calls",
                    "events",
                    "compactions",
                    "sessions",
                    "turns",
                    "work_units",
                    "segments",
                )
            }
            span = connection.execute(
                text("SELECT min(completed_at), max(completed_at) FROM calls")
            ).one()
            size = connection.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar()
            tables = connection.execute(
                text(
                    "SELECT relname, pg_total_relation_size(c.oid) FROM pg_class AS c "
                    "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                    "ORDER BY 2 DESC LIMIT 12"
                )
            ).all()
        return {
            "rows": counts,
            "first_call": span[0].isoformat(),
            "last_call": span[1].isoformat(),
            "database_bytes": size,
            "largest_tables": dict(tables),
        }

    def _get(self, route: str, state: str, query: Sequence[tuple[str, str]]) -> Any:
        answer = self.client.get(route, query_string=[("state", state), *query])
        if answer.status_code == 409:
            raise Refused(answer.get_json()["error"])
        if answer.status_code != 200:
            raise RuntimeError(f"{answer.status_code}: {answer.get_json()}")
        return answer.get_json()

    def threshold(self, range_: str) -> str:
        """A threshold on the projects' cost that keeps the two costliest."""
        rows = self._get(
            "/api/dashboard/rows", f"t={range_}&by=project&m=cost.sum", ()
        )["rows"]
        values = sorted((row["values"][0] or 0 for row in rows), reverse=True)
        return f"{values[2]:.2f}" if len(values) > 2 else "0"

    def conversation(self) -> str:
        return str(
            self._scalar(
                "SELECT transcript_id FROM calls GROUP BY transcript_id "
                "ORDER BY count(*) DESC, max(completed_at) DESC LIMIT 1"
            )
        )

    def _collector(self, route: str) -> Any:
        answer = self.client.get(route, headers=self.collector)
        if answer.status_code != 200:
            raise RuntimeError(f"{answer.status_code}: {answer.get_json()}")
        return answer.get_json()

    def _reader(self, part: Part, state: str) -> Callable[[], Any]:
        if part.collector:
            assert part.route is not None
            route = part.route
            return lambda: self._collector(route)
        if part.route is not None:
            route = part.route.format(conversation=self.conversation_id)
            return lambda: self._get(route, state, part.query)

        def counted() -> Any:
            with self.app.app_context():
                view = self.container.address_service().view(state)
                counts = self.container.counts_service()
                now = datetime.now(UTC)
                if part.key == "attributes":
                    return counts.attributes(view, now)
                return counts.quick_filters(view, now)

        return counted

    def time(self, part: Part, range_: str) -> Timed:
        state = part.state.format(t=range_, x=self.thresholds.get(range_, "0"))
        read = self._reader(part, state)
        try:
            began = time.perf_counter()
            read()
            first = (time.perf_counter() - began) * 1000
            runs = []
            before = self.temp_bytes()
            for _ in range(timed_runs(first)):
                began = time.perf_counter()
                read()
                runs.append(round((time.perf_counter() - began) * 1000, 1))
            spilled = self.temp_bytes() - before
            with self.captured.capturing() as sent:
                read()
            with self.engine.connect() as connection:
                statements = explained(connection, list(sent))
        except (Refused, QueryRefusedException) as refused:
            return Timed(
                part.key, part.label, range_, state, 0, [], 0, error=str(refused)
            )
        return Timed(
            part.key,
            part.label,
            range_,
            state,
            statistics.median(runs),
            runs,
            spilled // len(runs),
            statements,
        )

    def burst(self) -> list[dict[str, Any]]:
        """The Projects view over all time, read by one to `BURST` clients
        at once: each read's time."""
        state = PARTS[1].state.format(t="all")
        found = []
        for at_once in range(1, BURST + 1):

            def read() -> float:
                client = self.app.test_client()
                began = time.perf_counter()
                answer = client.get(
                    "/api/dashboard/rows", query_string={"state": state}
                )
                assert answer.status_code == 200, answer.get_json()
                return round((time.perf_counter() - began) * 1000, 1)

            with ThreadPoolExecutor(at_once) as pool:
                pool.submit(read).result()
                began = time.perf_counter()
                times = list(pool.map(lambda _: read(), range(at_once)))
                wall = round((time.perf_counter() - began) * 1000, 1)
            found.append({"at_once": at_once, "reads_ms": times, "wall_ms": wall})
        return found

    def run(self, only: set[str] | None) -> dict[str, Any]:
        self.each_item_filter()
        self.conversation_id = self.conversation()
        self.thresholds = {range_: self.threshold(range_) for range_ in RANGES}
        timed = []
        for part in PARTS:
            if only and part.key not in only:
                continue
            for range_ in part.ranges:
                one = self.time(part, range_)
                print(
                    f"{part.key:20} {range_:4} {one.ms:9.1f} ms"
                    + (f"  {one.error}" if one.error else ""),
                    flush=True,
                )
                timed.append(asdict(one))
        return {
            "taken_at": datetime.now(UTC).isoformat(),
            "record": self.facts(),
            "conversation": self.conversation_id,
            "thresholds": self.thresholds,
            "parts": timed,
            "burst": [] if only else self.burst(),
        }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="*", help="the parts to time, by key")
    args = parser.parse_args(argv)

    os.environ["DASHBOARD_STATEMENT_TIMEOUT_SECONDS"] = str(TIMEOUT_SECONDS)
    os.environ["OIDC_ENABLED"] = "false"
    os.environ.setdefault("COLLECTOR_TOKEN", secrets.token_hex(16))
    from app import create_app

    timing = Timing(create_app(skip_background_services=True))
    found = timing.run(set(args.only) if args.only else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(found, indent=1, default=str) + "\n")


if __name__ == "__main__":
    main()
