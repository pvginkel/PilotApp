"""Application-specific configuration.

This module implements app-specific configuration that is separate from the
infrastructure configuration in config.py.
"""

import re
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
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
        )
