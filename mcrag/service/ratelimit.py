"""Spend protection for a public `/ask`: a per-client sliding window and a global
daily cap, both in memory.

Every question can spend generation quota, so a public deployment needs a ceiling
that does not depend on visitors being polite. In-memory means one process: the
limits reset on restart and are not shared across replicas, which is acceptable
for a single small instance and wrong for a scaled-out one.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_minute: int, daily_cap: int, clock=time.time) -> None:
        self.per_minute, self.daily_cap, self._clock = per_minute, daily_cap, clock
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self._day: int | None = None
        self._today = 0

    def check(self, client: str) -> str | None:
        """None to allow (and count) the request, else the reason it is refused."""
        now = self._clock()
        day = int(now // 86400)
        if day != self._day:
            self._day, self._today = day, 0
        if self._today >= self.daily_cap:
            return "daily limit reached"
        window = self._recent[client]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return "too many requests"
        window.append(now)
        self._today += 1
        return None
