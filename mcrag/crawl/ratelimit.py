"""One request per second, held across every caller.

The limiter is shared state, not a sleep between calls. Two threads each
sleeping one second between their own requests produce two requests per second
at the server, which is the failure this class exists to prevent. The lock is
held across the wait so the interval is enforced globally.

``clock`` and ``sleep`` are injected so the timing test does not take real time,
and so a crawl can be replayed deterministically.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    """A global minimum interval between acquisitions."""

    def __init__(
        self,
        requests_per_second: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.min_interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None
        self.acquisitions = 0

    def acquire(self) -> float:
        """Block until the next request is permitted. Returns seconds waited."""
        with self._lock:
            now = self._clock()
            waited = 0.0
            if self._last is not None:
                elapsed = now - self._last
                if elapsed < self.min_interval:
                    waited = self.min_interval - elapsed
                    self._sleep(waited)
                    now = self._clock()
            self._last = now
            self.acquisitions += 1
            return waited

    def respect_crawl_delay(self, delay: float | None) -> None:
        """Adopt a robots.txt Crawl-delay when it is stricter than our own.

        Never loosens. A site asking for slower gets slower; a site asking for
        faster does not get faster, because the one-per-second floor is our own
        policy and not theirs to raise.
        """
        if delay and delay > self.min_interval:
            self.min_interval = delay

    def __enter__(self) -> RateLimiter:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        return None
