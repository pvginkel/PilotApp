"""Pilot's invented scenario and its builder (F122.2 to F122.4): one short
script in invented words, turned into what each layer reads: a collector its
conversations as transcript files, the backend's ingest their publications. It imports
nothing of the database, Flask or the app, so that every layer's suite can
take it."""

from pilot_scenario.builder import COLLECTOR, Builder, SentTurn
from pilot_scenario.scenario import SCENARIO
from pilot_scenario.script import Scenario
from pilot_scenario.transcript import HomeFile

__all__ = ["COLLECTOR", "SCENARIO", "Builder", "HomeFile", "Scenario", "SentTurn"]
