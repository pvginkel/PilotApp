"""The collector's settings, each read from the environment variable of its
name."""

import re
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import AfterValidator, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

INSTALL_PATH = "{install_path}"
"""What `COLLECTOR_LABELLER` names the installed copy's folder by."""


def _names_the_id(pattern: re.Pattern[str]) -> re.Pattern[str]:
    if pattern.groups < 1:
        raise ValueError("the pattern has no group for the environment's id")
    return pattern


def _are_absolute(roots: list[str]) -> list[str]:
    for root in roots:
        if not PurePosixPath(root).is_absolute():
            raise ValueError(f"the checkout root `{root}` is no absolute path")
    return roots


def _are_owners(owners: list[str]) -> list[str]:
    for owner in owners:
        if not owner or "/" in owner or owner in (".", ".."):
            raise ValueError(f"the owner `{owner}` is no name of one folder")
    return owners


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    COLLECTOR_PILOT_URL: str = Field(
        description=(
            "Where Pilot's backend answers, the address its `/api/collector`"
            " routes are under (F152.1)"
        ),
    )
    COLLECTOR_TOKEN: SecretStr = Field(
        min_length=1,
        description=(
            "The bearer between the collector and Pilot, the backend's"
            " `COLLECTOR_TOKEN`: its calls to Pilot carry it, and a call for a"
            " reading is refused without it (F152.1, F152.13)"
        ),
    )
    COLLECTOR_HOME: Path = Field(
        description=(
            "The fleet's home as the collector sees it: the folder that holds"
            " `projects`, Claude Code's `.claude` (F152.1)"
        ),
    )

    COLLECTOR_PORT: int = Field(
        default=3503,
        ge=0,
        le=65_535,
        description=(
            "The port the collector serves a conversation's reading on, to"
            " Pilot's backend (F152.13); 0 takes one that is free"
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
    COLLECTOR_LABELLER: list[str] = Field(
        default=["python3", "-B", f"{INSTALL_PATH}/tools/labeller.py"],
        min_length=1,
        description=(
            "The command that runs the workflow's labeller, as a JSON list, each"
            " call's verb appended; `{install_path}` in it is the folder of the"
            " copy of `dev@aiworkflow` that the home's"
            " `plugins/installed_plugins.json` names, as the collector sees it"
            " (F152.6)"
        ),
    )
    COLLECTOR_LABELLER_SECONDS: float = Field(
        default=60.0,
        gt=0,
        description=(
            "Seconds a call of the labeller may take: past them it is stopped,"
            " and the walk labels nothing (F152.6)"
        ),
    )
    COLLECTOR_MIRROR_URL: str = Field(
        default="http://gitblit.git-sync-prd.svc.cluster.local/r",
        min_length=1,
        description=(
            "Where the Gitblit mirror serves the repositories, with no"
            " credential: a Repository's address is `<this>/<owner>/<name>.git`,"
            " as git reads one, a folder's path included (F152.11)"
        ),
    )
    COLLECTOR_MIRROR_OWNERS: Annotated[list[str], AfterValidator(_are_owners)] = Field(
        default=["pvginkel"],
        min_length=1,
        description=(
            "The owners on the mirror a Repository is looked for under, in"
            " the order they are tried, as a JSON list (F152.11)"
        ),
    )
    COLLECTOR_MIRROR_SECONDS: float = Field(
        default=3_600.0,
        gt=0,
        description=(
            "Seconds from one read of the clones to the next: the first walk"
            " after a start reads them, and then the first walk once these have"
            " passed since the last read began, one that left transcripts for"
            " the next walk waiting for one that did not (F152.11)"
        ),
    )
    COLLECTOR_CLONES: Path = Field(
        default=Path("/tmp/pilot-collector/clones"),
        description=(
            "The folder the bare clones of the mirror are kept in, on the"
            " collector's own storage: a clone it holds is fetched, and one it"
            " lacks is cloned (F152.11)"
        ),
    )
