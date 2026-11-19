"""The collector's settings, each read from the environment variable of its
name."""

import re
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import AfterValidator, Field
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

    COLLECTOR_ENVIRONMENT_PATTERN: Annotated[
        re.Pattern[str], AfterValidator(_names_the_id)
    ] = Field(
        default=re.compile(r"# Environment: (\S+)"),
        description=(
            "Regular expression the managed instruction file opens with on a"
            " hosted session: its first group is the environment's id (F152.4)"
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
