"""The wait on a file call the controller keeps refusing for a reason of its
own (P-64): the write-back's every refusal but one naming the file, its path
or its environment (`WriteBackService`), and the turn-end read's `409
conflict` (`TurnEndReadService`). Such a call is made again a round at a time,
every `REFUSAL_RETRY_SECONDS`, until `REFUSAL_WAIT_SECONDS` have passed since
the round of its first refusal counted, and is then taken as refused with the
controller's answer. A run makes all its calls in each round, so that their
waits run side by side, never one after another. A refusal that counts toward
no wait starts its call's afresh from the next one.
"""

import time
from collections.abc import Hashable, Iterable

REFUSAL_WAIT_SECONDS = 5 * 60.0
"""How long a call the controller refuses for a reason of its own is made
again from its first refusal counted."""

REFUSAL_RETRY_SECONDS = 5.0
"""The wait between two rounds of those calls."""


class RefusalWaits:
    """One run's calls refused for a reason of the controller's own, each
    with the start of its wait, by the call's key."""

    def __init__(self, wait_seconds: float, retry_seconds: float) -> None:
        self._wait = wait_seconds
        self._retry = retry_seconds
        self._since: dict[Hashable, float] = {}
        self._round = time.perf_counter()

    def __contains__(self, key: Hashable) -> bool:
        """Whether the call's wait has started."""
        return key in self._since

    def round(self, owed: Iterable[Hashable]) -> None:
        """A round begins with the calls still `owed`: the others' waits are
        dropped."""
        self._round = time.perf_counter()
        kept = set(owed)
        self._since = {key: at for key, at in self._since.items() if key in kept}

    def passed(self, key: Hashable) -> bool:
        """A refusal of the call counted, its wait started with this round if
        it had none: whether the wait has passed by this round's start, which
        ends it. The calls whose waits started in one round pass in one."""
        since = self._since.setdefault(key, self._round)
        if self._round - since < self._wait:
            return False
        del self._since[key]
        return True

    def restart(self, key: Hashable) -> None:
        """A refusal that counts toward no wait: the call's starts from its
        next one."""
        self._since.pop(key, None)

    def pause(self) -> float:
        """The wait before the next round: the retry's, or less when a wait
        passes sooner."""
        now = time.perf_counter()
        due = [since + self._wait - now for since in self._since.values()]
        return max(0.0, min([self._retry, *due]))
