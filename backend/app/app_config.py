"""Application-specific configuration.

This module implements app-specific configuration that is separate from the
infrastructure configuration in config.py.
"""

import re
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator
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
        )
