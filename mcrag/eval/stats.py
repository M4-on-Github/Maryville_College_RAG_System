"""Interval estimation.

PLAN 4f: a bare float is not a reportable number anywhere in this project. Every
statistic leaves here as ``(value, ci_low, ci_high, n)`` because a point estimate
with no n is what turns a twenty-question sample into a confident claim.

The bootstrap is seeded and the seed travels with the result. An interval that
moves when you rerun it is not an interval, it is a mood.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Interval:
    """A statistic with its uncertainty and the sample it came from."""

    value: float
    ci_low: float
    ci_high: float
    n: int
    statistic: str = "median"
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """The shape ``RunDir.write_metrics`` enforces."""
        return {
            "value": self.value,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n": self.n,
            "statistic": self.statistic,
            "seed": self.seed,
        }

    def __str__(self) -> str:
        return f"{self.value:.3g} [{self.ci_low:.3g}, {self.ci_high:.3g}] (n={self.n})"


def bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = statistics.median,
    *,
    name: str = "median",
    seed: int = 42,
    iterations: int = 10_000,
    alpha: float = 0.05,
) -> Interval:
    """Percentile bootstrap over ``values``.

    The default statistic is the median, not the mean: latency and GPU-time
    samples carry cold starts and retries, and one 40-second outlier in twenty
    queries moves a mean enough to invalidate a budget built on it.

    A single observation gets a degenerate interval rather than an exception. One
    measurement is a real thing to report, as long as the n travels with it.
    """
    if not values:
        raise ValueError("cannot summarise an empty sample")
    point = float(statistic(values))
    n = len(values)
    if n == 1:
        return Interval(point, point, point, 1, name, seed)

    rng = random.Random(seed)
    draws = [
        float(statistic([values[rng.randrange(n)] for _ in range(n)])) for _ in range(iterations)
    ]
    draws.sort()
    lo = draws[int((alpha / 2) * iterations)]
    hi = draws[min(iterations - 1, int((1 - alpha / 2) * iterations))]
    return Interval(point, lo, hi, n, name, seed)
