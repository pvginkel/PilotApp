"""The collector's settings, each read from the environment variable of its
name."""

import re
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import AfterValidator, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _names_the_id(pattern: re.Pattern[str]) -> re.Pattern[str]:
    if pattern.groups < 1:
        raise ValueError("the pattern has no group for the environment's id")
    return pattern


def _are_absolute(roots: list[str]) -> list[str]:
    for root in roots:
        if not PurePosixPath(root).is_absolute():
            raise ValueError(f"the checkout root `{root}` is no absolute path")
    return roots


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    COLLECTOR_PILOT_URL: str = Field(
        description=(
            "Where Pilot's backend answers, the address its `/api/collector`"
            " routes are under (F152.1)"
        ),
    )
    COLLECTOR_TOKEN: SecretStr = Field(
        description=(
            "The bearer between the collector and Pilot, the backend's"
            " `COLLECTOR_TOKEN` (F152.1)"
        ),
    )
    COLLECTOR_HOME: Path = Field(
        description=(
            "The fleet's home as the collector sees it: the folder that holds"
            " `projects`, Claude Code's `.claude` (F152.1)"
        ),
    )

    COLLECTOR_ENVIRONMENT_PATTERN: Annotated[
        re.Pattern[str], AfterValidator(_names_the_id)
    ] = Field(
        default=re.compile(r"# Environment: (\S+)"),
        description=(
            "Regular expression the managed instruction file opens with on a"
            " hosted session: its first group is the environment's id (F152.4)"
        ),
    )
    COLLECTOR_CARRY_TRANSCRIPTS: int = Field(
        default=2_500,
        ge=0,
        description=(
            "How many transcripts' carries the collector keeps between walks:"
            " past it the transcript whose file changed longest ago is forgotten"
            " first, and is published whole when it next grows (F152.15)"
        ),
    )
    COLLECTOR_CARRY_BYTES: int = Field(
        default=64_000_000,
        ge=0,
        description=(
            "The bytes of memory the carries are kept within, forgotten in the"
            " same order past it (F152.15)"
        ),
    )
    COLLECTOR_CHECKOUT_ROOTS: Annotated[list[str], AfterValidator(_are_absolute)] = (
        Field(
            default=["/work"],
            description=(
                "The directories an environment's repositories are checked out"
                " under, each an absolute path, as a JSON list (F152.4)"
            ),
        )
    )
