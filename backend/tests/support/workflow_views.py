"""An invented file of the workflow's views and ratios, in the scenario's own
words (`pilot_scenario`: the recipe box's errand and its servings, the bike
log's rides), naming nothing of a workflow, as the dashboard's load takes it:
`views`, each a `key`, a `name`, a `state` and a `note`, and `ratios`, each a
`key`, a `name`, a `numerator`, a `denominator` and a `note`."""

import json
from pathlib import Path
from typing import Any

from app.dashboard.views import SystemView
from app.services.dashboard_store_service import RatioEntry

FILE = Path(__file__).resolve().parent.parent / "fixtures" / "workflow_views.json"


def arguments() -> dict[str, Any]:
    """The file whole, as the load's tool and its route take it."""
    loaded: dict[str, Any] = json.loads(FILE.read_text(encoding="utf-8"))
    return loaded


def entries() -> tuple[list[SystemView], list[RatioEntry]]:
    """The file's views and ratios, as the load's service takes them."""
    written = arguments()
    return (
        [SystemView(**view) for view in written["views"]],
        [RatioEntry(**ratio) for ratio in written["ratios"]],
    )
