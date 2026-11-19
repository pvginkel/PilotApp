"""The collector as a process: `python -m pilot_collector`, or the script
`pilot-collector`. It walks the home named in its settings for the Pilot
named there until it is told to stop, by SIGTERM or SIGINT, which a walk
obeys before its next publication."""

import logging
import signal
import threading

from pilot_collector.pilot import Pilot
from pilot_collector.settings import Settings
from pilot_collector.walk import Walker


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request at INFO: one line per publication.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    stop = threading.Event()
    for told in (signal.SIGTERM, signal.SIGINT):
        signal.signal(told, lambda *_: stop.set())
    with Pilot(
        settings.COLLECTOR_PILOT_URL, settings.COLLECTOR_TOKEN.get_secret_value()
    ) as pilot:
        Walker(pilot, settings, stop).run()


if __name__ == "__main__":
    main()
