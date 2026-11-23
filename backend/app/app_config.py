"""Application-specific configuration.

This module implements app-specific configuration that is separate from the
infrastructure configuration in config.py.
"""

import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self
from zoneinfo import available_timezones

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FilePath,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import Sensitive, dump_config_for_logging

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_TICKET_ID_PATTERN = r"[A-Z][A-Z0-9_]*-[1-9][0-9]*"


class HaltSetting(StrEnum):
    """What a usage halt does to the work items, one setting per window
    (F135.6): no new work, the cooperative stop or the hard stop. The gate
    holds their starts under each."""

    NO_NEW_WORK = "no_new_work"
    COOPERATIVE_STOP = "cooperative_stop"
    HARD_STOP = "hard_stop"


class AppEnvironment(BaseSettings):
    """Raw environment variable loading for app-specific settings."""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    TICKET_ID_PATTERN: str = Field(
        default=_TICKET_ID_PATTERN,
        description="Regular expression a whole ticket id matches (F91)",
    )
    SYNC_TOKEN: str = Field(
        default="",
        description="The store sidecar's bearer for /api/sync; empty refuses every sync call",
    )
    STORE_ENVIRONMENT_ID: str = Field(
        default="",
        description="The store environment's KubeCoder id, which every sync call names",
    )
    YOUTRACK_WEBHOOK_TOKEN: str = Field(
        default="",
        description=(
            "YouTrack's webhook token, which each delivery to "
            "/api/tracker-events/youtrack carries in X-YouTrack-Token; empty "
            "refuses every delivery"
        ),
    )
    COLLECTOR_TOKEN: str = Field(
        default="",
        description=(
            "The collector's bearer for /api/collector; empty refuses every "
            "call of a collector's"
        ),
    )
    COLLECTOR_URL: str = Field(
        default="",
        description=(
            "The base URL of the collector's readings, which a conversation's "
            "reader asks (F154.7); empty refuses every read of a conversation"
        ),
    )
    COLLECTOR_WALK_INTERVAL_SECONDS: float = Field(
        default=30.0,
        gt=0,
        description=(
            "Seconds from one walk of a collector's to its next, which each "
            "inventory hands it (F152.2)"
        ),
    )
    COLLECTOR_SETTLING_SECONDS: float = Field(
        default=600.0,
        ge=0,
        description=(
            "Seconds a transcript's file stands unchanged before its replay at "
            "rest, which each inventory hands the collector (F152.16)"
        ),
    )
    SYNC_PUT_MAX_BYTES: int = Field(
        default=2 * 1024 * 1024,
        gt=0,
        description="Largest file a sync PUT takes, in bytes; a larger one gets 413",
    )
    SYNC_HEARTBEAT_SECONDS: float = Field(
        default=15.0,
        gt=0,
        description="Seconds the sync change stream stays idle before a heartbeat comment",
    )
    TICKET_URL_TEMPLATE: str | None = Field(
        default=None,
        description=(
            "A ticket's address, {id} standing for its id; unset, ticket ids show "
            "unlinked (F91)"
        ),
    )
    ENVIRONMENT_LINK_BASE_URL: str | None = Field(
        default=None,
        description=(
            "KubeCoder's address: an environment links to "
            "<base>/environments/<environment id>/ssh/open, which opens it in VS "
            "Code; unset, environments show unlinked (F93)"
        ),
    )
    CONTROLLER_URL: str = Field(
        default="",
        description="The KubeCoder controller's base URL; empty runs the app with no controller",
    )
    CONTROLLER_TOKEN: str = Field(
        default="",
        description="Pilot's named client credential at the KubeCoder controller",
    )
    CONTROLLER_CA_FILE: str = Field(
        default="",
        description=(
            "A PEM file of the CAs that verify the controller's certificate; "
            "empty leaves it to requests' own trust"
        ),
    )
    VAPID_PRIVATE_KEY: str = Field(
        default="",
        description=(
            "The stage's VAPID private key, P-256 in PEM, which signs every web "
            "push and whose public key browsers subscribe with; empty pushes "
            "nothing"
        ),
    )
    MCP_SERVER_URL: str = Field(
        default="",
        description=(
            "Pilot's MCP server's endpoint as a session reaches it, handed to "
            "every session Pilot creates; empty hands it none"
        ),
    )
    OUTAGE_ALARM_AFTER_SECONDS: float = Field(
        default=300.0,
        ge=0,
        description=(
            "Seconds the controller stays unreachable before its alarm reaches "
            "the phone, so a shorter blip buzzes nobody (F142.2)"
        ),
    )
    SCHEDULER_TICK_SECONDS: float = Field(
        default=10.0,
        gt=0,
        description="Seconds the supervisor's scheduler waits between two rounds of its timers",
    )
    ENVIRONMENT_STOP_AFTER_SECONDS: float = Field(
        default=1800.0,
        gt=0,
        description=(
            "Seconds an environment Pilot started stands with no session running "
            "or starting there before its shutdown timer stops it"
        ),
    )
    ENVIRONMENT_DELETE_AFTER_SECONDS: float = Field(
        default=604800.0,
        gt=0,
        description=(
            "Seconds an environment Pilot created stands free before its delete "
            "timer deletes it"
        ),
    )
    WORK_PARALLELISM_MAX: int = Field(
        default=3,
        gt=0,
        description=(
            "Work items running or starting across every project at which the "
            "gate holds a work item's start (F143.4)"
        ),
    )
    PROJECT_PARALLELISM_MAX: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Work items running or starting in one project at which the gate "
            "holds its work items' starts; unset, WORK_PARALLELISM_MAX (F143.4)"
        ),
    )
    ESTIMATE_WINDOW_STEPS: int = Field(
        default=20,
        gt=0,
        description=(
            "The last Step Timings of a kind, by their end, that the price of "
            "a step of that kind is read from (F156.4, F156.10)"
        ),
    )
    ESTIMATE_RUNNING_STEPS: int = Field(
        default=60,
        gt=0,
        description=(
            "The last Step Timings of its kind, of those that had ended when "
            "a running step began, that it is read against, for the time it "
            "still takes, for longer than usual and for its figures (F156.5, "
            "F156.10, F156.13)"
        ),
    )
    ESTIMATE_RUN_SLOW_FACTOR: float = Field(
        default=1.6,
        ge=1,
        description=(
            "What a run's normal, its list at its kinds' prices, is multiplied "
            "by for its slow in the figures (F156.10, F156.13): the 90th "
            "percentile of past runs' work over their list's price, set from "
            "the backtest each time it is run"
        ),
    )
    WEEK_FIRST_LIMIT: float = Field(
        default=0.90,
        gt=0,
        le=1,
        description=(
            "The week's share of the subscription's quota at or over which the "
            "week's halt holds the work items, unless an overrule holds (F135.1)"
        ),
    )
    WEEK_ALLOWANCE: float = Field(
        default=0.05,
        gt=0,
        le=1,
        description=(
            "The share an allowance adds to the week's share as it stands, its "
            "target, at most WEEK_SECOND_LIMIT (F135.2)"
        ),
    )
    WEEK_SECOND_LIMIT: float = Field(
        default=0.98,
        gt=0,
        le=1,
        description=(
            "The week's share at or over which the week's halt offers run-out in "
            "place of the allowance; at least WEEK_FIRST_LIMIT (F135.2)"
        ),
    )
    FIVE_HOUR_LIMIT: float = Field(
        default=0.75,
        ge=0,
        le=1,
        description=(
            "The five-hour window's share of the quota at or over which the "
            "five-hour halt holds the work items; 0 holds none (F135.4)"
        ),
    )
    WEEK_HALT: HaltSetting = Field(
        default=HaltSetting.COOPERATIVE_STOP,
        description=(
            "What the week's halt does to the work items: no_new_work, "
            "cooperative_stop or hard_stop (F135.6)"
        ),
    )
    FIVE_HOUR_HALT: HaltSetting = Field(
        default=HaltSetting.COOPERATIVE_STOP,
        description=(
            "What the five-hour halt does to the work items: no_new_work, "
            "cooperative_stop or hard_stop (F135.6)"
        ),
    )
    BRAIN_MODEL: str = Field(
        default="opus",
        min_length=1,
        description="The model of every brain session, the chat's and every job's (F139)",
    )
    BRAIN_REASONING_EFFORT: str = Field(
        default="xhigh",
        min_length=1,
        description=(
            "The reasoning effort of every brain session, the chat's and every "
            "job's (F139)"
        ),
    )
    CACHE_EXPIRATION_TTL: float = Field(
        default=3300.0,
        gt=0,
        description=(
            "Seconds after its previous run's turn ended within which a wait's "
            "run resumes that run's conversation, the subscription's prompt-cache "
            "TTL (F136.5)"
        ),
    )
    CHAT_CLOSE_TIMEOUT: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Seconds after its last turn ended at which an open project chat with "
            "no turn in flight closes; unset, CACHE_EXPIRATION_TTL (F130)"
        ),
    )
    WAIT_QUIET_WINDOW_SECONDS: float = Field(
        default=5.0,
        gt=0,
        description=(
            "Seconds after a wait's first pending firing at which its run is "
            "placed, later firings joining it (F136.4)"
        ),
    )
    DASHBOARD_ZONE: str = Field(
        default="Europe/Amsterdam",
        description=(
            "The IANA time zone the analysis dashboard derives the day, the "
            "weekday and the hour in, and shows its times in (F160.11)"
        ),
    )
    DASHBOARD_SITTING_GAP_SECONDS: float = Field(
        default=14400.0,
        gt=0,
        description=(
            "Seconds between one transcript's last call and the next one's "
            "first at or over which a sitting of the sessions on no project "
            "ends (F166.6)"
        ),
    )
    DASHBOARD_STATEMENT_TIMEOUT_SECONDS: float = Field(
        default=45.0,
        gt=0,
        description=(
            "Seconds a read of the analysis dashboard's engine takes at most "
            "before it is refused, its wait for a slot among its statements "
            "at once and every statement it runs together, below the 60 s "
            "the proxy in front of /api/ waits for an answer (F154.5)"
        ),
    )
    DASHBOARD_STATEMENTS_AT_ONCE: int = Field(
        default=2,
        gt=0,
        description=(
            "The analysis dashboard's statements running at once at most, "
            "each on a connection of the pool, which must be larger (F154.5)"
        ),
    )
    DASHBOARD_READINGS_DIR: str = Field(
        default="",
        description=(
            "The folder the conversations' readings are kept in, a scratch "
            "volume of the pod's (F154.7); empty keeps them in a temporary "
            "folder of the process's own, removed at its exit"
        ),
    )
    DASHBOARD_READINGS_MAX_BYTES: int = Field(
        default=256 * 1024 * 1024,
        gt=0,
        description=(
            "The bytes of the conversations' readings kept at most, as the "
            "collector compressed them; past it the least recently read go "
            "first (F154.7)"
        ),
    )
    POOL_GUARD: bool = Field(
        default=False,
        description=(
            "Testing mode alone: the pool guard on the app's pools, its "
            "nestings taken at /api/testing/pool-guard (Playwright's backends)"
        ),
    )
    STATEMENT_CAP: bool = Field(
        default=False,
        description=(
            "Testing mode alone: the statement cap on the app's engines, the "
            "statements over it taken at /api/testing/statement-cap "
            "(Playwright's backends)"
        ),
    )


class AppSettings(BaseModel):
    """Application-specific settings.

    Annotate every field that holds a secret ``Annotated[str, Sensitive]``
    (``from app.config import Sensitive``): run.py logs these settings at boot.
    """

    model_config = ConfigDict(from_attributes=True)

    ticket_id_pattern: re.Pattern[str] = re.compile(_TICKET_ID_PATTERN)
    """What a ticket id matches whole: `plan.json`'s `ticket` (F57.1, F91)."""

    sync_token: Annotated[str, Sensitive] = ""
    """The bearer the store's sidecar syncs with (design 1 §5.1): empty refuses
    every sync call."""

    store_environment_id: str = ""
    """The store environment's KubeCoder id, which every sync call names in
    `X-Pilot-Environment`: empty refuses every sync call."""

    youtrack_webhook_token: Annotated[str, Sensitive] = ""
    """YouTrack's webhook token, the instance's one, which each of its
    deliveries carries in `X-YouTrack-Token` (F136.1): empty refuses every
    delivery."""

    collector_token: Annotated[str, Sensitive] = ""
    """The bearer a collector publishes with (F152.3): empty refuses every
    call of a collector's."""

    collector_walk_interval_seconds: float = 30.0
    """How long after one walk of a collector's its next begins (F152.2): the
    inventory hands it to the collector."""

    collector_settling_seconds: float = 600.0
    """How long a Transcript's file stands unchanged before the collector
    publishes it whole once, its replay at rest (DB decision 81 point 2): the
    inventory hands it to the collector."""

    sync_put_max_bytes: int = 2 * 1024 * 1024
    """The largest body a sync PUT takes."""

    sync_heartbeat_seconds: float = 15.0
    """How long the sync change stream stays idle before it writes a heartbeat
    comment (design 1 §5.1)."""

    ticket_url_template: str | None = None
    """A ticket's address, `{id}` standing for its id (F91)."""

    environment_link_base_url: str | None = None
    """KubeCoder's address, without a trailing slash (F93)."""

    @field_validator("ticket_url_template")
    @classmethod
    def _holds_the_id(cls, template: str | None) -> str | None:
        if template is not None and "{id}" not in template:
            raise ValueError(
                "TICKET_URL_TEMPLATE must hold {id}, where the ticket id goes"
            )
        return template

    @field_validator("environment_link_base_url")
    @classmethod
    def _is_an_address(cls, base: str | None) -> str | None:
        if base is None:
            return None
        if not base.startswith(("https://", "http://")):
            raise ValueError("ENVIRONMENT_LINK_BASE_URL must be an http(s) address")
        return base.rstrip("/")

    controller_url: str | None = None
    """The KubeCoder controller's base URL (design 2 §14); None runs the app with
    no controller, and production refuses to start so."""

    controller_token: Annotated[str, Sensitive] = ""
    """Pilot's named client credential at the controller."""

    controller_ca_file: FilePath | None = None
    """The CAs that verify the controller's certificate, PEM; None leaves it to
    requests' own trust."""

    vapid_private_key: Annotated[str | None, Sensitive] = None
    """The stage's VAPID private key, P-256 in PEM (F94, F142; RFC 8292); None
    pushes nothing, and production refuses to start so."""

    @field_validator("vapid_private_key")
    @classmethod
    def _is_a_p256_key(cls, pem: str | None) -> str | None:
        if pem is None:
            return None
        try:
            key = serialization.load_pem_private_key(pem.encode(), password=None)
        except (ValueError, TypeError) as error:
            raise ValueError(
                "VAPID_PRIVATE_KEY must be an unencrypted private key in PEM"
            ) from error
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("VAPID_PRIVATE_KEY must be a P-256 key")
        return pem

    mcp_server_url: str | None = None
    """Pilot's MCP server's endpoint as a session reaches it, which every
    headless create Pilot makes hands the session (TD §4.5); None hands it
    none, and production refuses to start so."""

    @field_validator("mcp_server_url")
    @classmethod
    def _is_an_endpoint(cls, url: str | None) -> str | None:
        if url is not None and not url.startswith(("https://", "http://")):
            raise ValueError("MCP_SERVER_URL must be an http(s) address")
        return url

    outage_alarm_after_seconds: float = 300.0
    """How long the controller stays unreachable before its alarm is
    submitted (F142.2; design 2 §13.4)."""

    scheduler_tick_seconds: float = 10.0
    """The wait between two rounds of the supervisor's timers (design 2 §7.1)."""

    environment_stop_after_seconds: float = 1800.0
    """How long an environment Pilot started stands with no Session running or
    starting there before the shutdown timer stops it (design 2 §13.3)."""

    environment_delete_after_seconds: float = 604800.0
    """How long an environment of Pilot's own stands free before the delete
    timer deletes it (design 2 §13.5)."""

    work_parallelism_max: int = 3
    """The work items running or starting across every Project at which the
    gate holds a work item's start (design 2 §13.5; F143.4)."""

    project_parallelism_max: int = 3
    """The work items running or starting in one Project at which the gate
    holds its work items' starts (design 2 §13.5; F143.4)."""

    estimate_window_steps: int = 20
    """A kind's window: its last Step Timings by their end, which a step's
    price is read from (F156.4)."""

    estimate_running_steps: int = 60
    """The last Step Timings of its kind a running step is read against
    (F156.5, F156.7)."""

    estimate_run_slow_factor: float = 1.6
    """What a run's normal is multiplied by for its slow (F156.10,
    F156.13)."""

    week_first_limit: float = 0.90
    """The week's share at or over which the week's halt holds the work items,
    unless a Quota Overrule holds (F135.1; DB 266)."""

    week_allowance: float = 0.05
    """What an allowance adds to the week's share as it stands, its target at
    most the second limit (F135.2; DB 179)."""

    week_second_limit: float = 0.98
    """The week's share at or over which the week's halt offers run-out, the
    allowance no longer (F135.2)."""

    five_hour_limit: float = 0.75
    """The five-hour share at or over which the five-hour halt holds the work
    items; 0 holds none (F135.4; DB 266)."""

    week_halt: HaltSetting = HaltSetting.COOPERATIVE_STOP
    """What the week's halt does to the work items (F135.6)."""

    five_hour_halt: HaltSetting = HaltSetting.COOPERATIVE_STOP
    """What the five-hour halt does to the work items (F135.6)."""

    @model_validator(mode="after")
    def _limits_in_order(self) -> Self:
        if self.week_first_limit > self.week_second_limit:
            raise ValueError(
                "WEEK_FIRST_LIMIT must not be over WEEK_SECOND_LIMIT, the limit "
                "the allowance stops at"
            )
        return self

    brain_model: str = "opus"
    """The model every brain session is created on, the chat's and every
    job's alike (design 3 §12; F139)."""

    brain_reasoning_effort: str = "xhigh"
    """The reasoning effort every brain session is created with (F139)."""

    chat_close_timeout_seconds: float = 3300.0
    """How long after its last turn ended an open project chat with no turn in
    flight stands before the scheduler's tick closes it (F130; design 2
    §13)."""

    cache_expiration_ttl_seconds: float = 3300.0
    """How long after its previous run's turn ended a wait's run resumes that
    run's conversation; past it, the run is fresh (F136.5, DB 200)."""

    wait_quiet_window_seconds: float = 5.0
    """How long after a wait's first pending firing the batcher places its run,
    counted on the scheduler's tick (F136.4)."""

    dashboard_zone: str = "Europe/Amsterdam"
    """The zone the analysis dashboard's day, weekday and hour are derived
    in (DB decision 80.3)."""

    dashboard_sitting_gap_seconds: float = 14400.0
    """The gap from one Transcript's last Call to the next one's first that
    ends a sitting (DB decision 80.3)."""

    dashboard_statement_timeout_seconds: float = 45.0
    """How long a read of the dashboard's engine takes before it is refused,
    its wait for a slot and its statements together (F154.5)."""

    dashboard_statements_at_once: int = 2
    """How many statements of the dashboard's engine run at once at most,
    fewer than the app's pool holds (F154.5)."""

    collector_url: str | None = None
    """The base URL of the collector's readings (F152.13), under which
    `/readings/<session_id>` is a main thread's: none refuses every read of a
    conversation."""

    dashboard_readings_dir: Path | None = None
    """The folder the conversations' readings are kept in (F154.7): none
    keeps them in a temporary folder of the process's own."""

    dashboard_readings_max_bytes: int = 256 * 1024 * 1024
    """The bytes of the readings kept at most, each as the collector
    compressed it: some 12,000 readings of the median transcript's 21 KB, or
    280 of the largest's 0.9 MB, as `tools/cost-dashboard/architecture.md`
    measured them (F154.7)."""

    @field_validator("dashboard_zone")
    @classmethod
    def _is_a_zone(cls, zone: str) -> str:
        if zone not in available_timezones():
            raise ValueError("DASHBOARD_ZONE must be an IANA time zone")
        return zone

    pool_guard: bool = False
    """The pool guard on the app's pools (app/utils/pool_guard.py), its
    nestings taken at /api/testing/pool-guard: Playwright's backends, in
    testing mode alone."""

    statement_cap: bool = False
    """The statement cap on the app's engines (app/utils/statement_cap.py),
    the statements over it taken at /api/testing/statement-cap: Playwright's
    backends, in testing mode alone."""

    def dump_for_logging(self) -> dict[str, str]:
        """Every setting, for the boot log, with the Sensitive ones as ``***``."""
        return dump_config_for_logging(self)

    @classmethod
    def load(
        cls, env: "AppEnvironment | None" = None, flask_env: str = "development"
    ) -> "AppSettings":
        """Load app settings from environment variables."""
        if env is None:
            env = AppEnvironment()
        return cls(
            ticket_id_pattern=re.compile(env.TICKET_ID_PATTERN),
            sync_token=env.SYNC_TOKEN,
            store_environment_id=env.STORE_ENVIRONMENT_ID,
            youtrack_webhook_token=env.YOUTRACK_WEBHOOK_TOKEN,
            collector_token=env.COLLECTOR_TOKEN,
            collector_walk_interval_seconds=env.COLLECTOR_WALK_INTERVAL_SECONDS,
            collector_settling_seconds=env.COLLECTOR_SETTLING_SECONDS,
            sync_put_max_bytes=env.SYNC_PUT_MAX_BYTES,
            sync_heartbeat_seconds=env.SYNC_HEARTBEAT_SECONDS,
            ticket_url_template=env.TICKET_URL_TEMPLATE or None,
            environment_link_base_url=env.ENVIRONMENT_LINK_BASE_URL or None,
            controller_url=env.CONTROLLER_URL or None,
            controller_token=env.CONTROLLER_TOKEN,
            controller_ca_file=(
                Path(env.CONTROLLER_CA_FILE) if env.CONTROLLER_CA_FILE else None
            ),
            vapid_private_key=env.VAPID_PRIVATE_KEY or None,
            mcp_server_url=env.MCP_SERVER_URL or None,
            outage_alarm_after_seconds=env.OUTAGE_ALARM_AFTER_SECONDS,
            scheduler_tick_seconds=env.SCHEDULER_TICK_SECONDS,
            environment_stop_after_seconds=env.ENVIRONMENT_STOP_AFTER_SECONDS,
            environment_delete_after_seconds=env.ENVIRONMENT_DELETE_AFTER_SECONDS,
            work_parallelism_max=env.WORK_PARALLELISM_MAX,
            project_parallelism_max=(
                env.WORK_PARALLELISM_MAX
                if env.PROJECT_PARALLELISM_MAX is None
                else env.PROJECT_PARALLELISM_MAX
            ),
            estimate_window_steps=env.ESTIMATE_WINDOW_STEPS,
            estimate_running_steps=env.ESTIMATE_RUNNING_STEPS,
            estimate_run_slow_factor=env.ESTIMATE_RUN_SLOW_FACTOR,
            week_first_limit=env.WEEK_FIRST_LIMIT,
            week_allowance=env.WEEK_ALLOWANCE,
            week_second_limit=env.WEEK_SECOND_LIMIT,
            five_hour_limit=env.FIVE_HOUR_LIMIT,
            week_halt=env.WEEK_HALT,
            five_hour_halt=env.FIVE_HOUR_HALT,
            brain_model=env.BRAIN_MODEL,
            brain_reasoning_effort=env.BRAIN_REASONING_EFFORT,
            chat_close_timeout_seconds=(
                env.CACHE_EXPIRATION_TTL
                if env.CHAT_CLOSE_TIMEOUT is None
                else env.CHAT_CLOSE_TIMEOUT
            ),
            cache_expiration_ttl_seconds=env.CACHE_EXPIRATION_TTL,
            wait_quiet_window_seconds=env.WAIT_QUIET_WINDOW_SECONDS,
            dashboard_zone=env.DASHBOARD_ZONE,
            dashboard_sitting_gap_seconds=env.DASHBOARD_SITTING_GAP_SECONDS,
            dashboard_statement_timeout_seconds=env.DASHBOARD_STATEMENT_TIMEOUT_SECONDS,
            dashboard_statements_at_once=env.DASHBOARD_STATEMENTS_AT_ONCE,
            collector_url=env.COLLECTOR_URL or None,
            dashboard_readings_dir=(
                Path(env.DASHBOARD_READINGS_DIR) if env.DASHBOARD_READINGS_DIR else None
            ),
            dashboard_readings_max_bytes=env.DASHBOARD_READINGS_MAX_BYTES,
            pool_guard=env.POOL_GUARD,
            statement_cap=env.STATEMENT_CAP,
        )
