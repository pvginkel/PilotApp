"""Application-specific configuration.

This module implements app-specific configuration that is separate from the
infrastructure configuration in config.py.
"""

import re
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, FilePath, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import Sensitive, dump_config_for_logging

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_TICKET_ID_PATTERN = r"[A-Z][A-Z0-9_]*-[1-9][0-9]*"


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
    MCP_SERVER_URL: str = Field(
        default="",
        description=(
            "Pilot's MCP server's endpoint as a session reaches it, handed to "
            "every session Pilot creates; empty hands it none"
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
    CHAT_CLOSE_TIMEOUT: float = Field(
        default=3300.0,
        gt=0,
        description=(
            "Seconds after its last turn ended at which an open project chat with "
            "no turn in flight closes; cache_expiration_ttl's 55 minutes (F130)"
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

    brain_model: str = "opus"
    """The model every brain session is created on, the chat's and every
    job's alike (design 3 §12; F139)."""

    brain_reasoning_effort: str = "xhigh"
    """The reasoning effort every brain session is created with (F139)."""

    chat_close_timeout_seconds: float = 3300.0
    """How long after its last turn ended an open project chat with no turn in
    flight stands before the scheduler's tick closes it (F130; design 2
    §13)."""

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
            sync_put_max_bytes=env.SYNC_PUT_MAX_BYTES,
            sync_heartbeat_seconds=env.SYNC_HEARTBEAT_SECONDS,
            ticket_url_template=env.TICKET_URL_TEMPLATE or None,
            environment_link_base_url=env.ENVIRONMENT_LINK_BASE_URL or None,
            controller_url=env.CONTROLLER_URL or None,
            controller_token=env.CONTROLLER_TOKEN,
            controller_ca_file=(
                Path(env.CONTROLLER_CA_FILE) if env.CONTROLLER_CA_FILE else None
            ),
            mcp_server_url=env.MCP_SERVER_URL or None,
            scheduler_tick_seconds=env.SCHEDULER_TICK_SECONDS,
            environment_stop_after_seconds=env.ENVIRONMENT_STOP_AFTER_SECONDS,
            environment_delete_after_seconds=env.ENVIRONMENT_DELETE_AFTER_SECONDS,
            work_parallelism_max=env.WORK_PARALLELISM_MAX,
            project_parallelism_max=(
                env.WORK_PARALLELISM_MAX
                if env.PROJECT_PARALLELISM_MAX is None
                else env.PROJECT_PARALLELISM_MAX
            ),
            brain_model=env.BRAIN_MODEL,
            brain_reasoning_effort=env.BRAIN_REASONING_EFFORT,
            chat_close_timeout_seconds=env.CHAT_CLOSE_TIMEOUT,
        )
