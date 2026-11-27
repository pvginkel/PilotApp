"""Pilot's invented scenarios and their builder (F122.2 to F122.4): short
scripts in invented words, turned into what each layer reads: a collector
their conversations as transcript files, the backend's ingest their
publications. The invented one tells a story (`SCENARIO`), the tally gives
the dashboard's figures a case each (`TALLY`), and a history draws days of
the fleet's work from a seed (`pilot_scenario.history`). It imports nothing
of the database, Flask or the app, so that every layer's suite can take
it."""

from pilot_scenario.builder import COLLECTOR, Builder, SentRun, SentTurn
from pilot_scenario.scenario import SCENARIO
from pilot_scenario.script import Scenario
from pilot_scenario.tally import TALLY
from pilot_scenario.transcript import HomeFile

__all__ = [
    "COLLECTOR",
    "SCENARIO",
    "TALLY",
    "Builder",
    "HomeFile",
    "Scenario",
    "SentRun",
    "SentTurn",
]
