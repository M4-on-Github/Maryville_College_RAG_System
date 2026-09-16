"""Task 16b: paired comparison tooling -- PLAN 4f.

Every comparison in this project is paired: the same gold questions score
both configs, so question difficulty is a blocking factor removed from the
error term rather than left in it. PLAN 4f splits outcome types across two
tests:

- **binary** (hit/miss, all-golds-retrieved, correct-refusal) -> exact McNemar
  on the discordant pairs
- **graded** (nDCG, MRR, the 0/1/2 rubric) and **cost** (median, never mean --
  cold starts skew it) -> paired bootstrap, 10k resamples, seeded

Every function here returns `stats.Interval`'s shape -- no bare float leaves
this module. McNemar's p-value is exact (a closed-form sum over the binomial
distribution, not the chi-square approximation, since the discordant counts
PLAN 4f's own MDE table works with are too small to trust the approximation)
and it travels as an explicit field on `ComparisonResult`, never implicitly
attached to a number. `assert_reportable` is the guard that keeps a p-value
from reaching a dev-split report at all: "dev is selection, not inference...
no p-value computed on dev appears in the writeup" (PLAN 4f) -- ranking
configs on dev does not need a hypothesis test, and reporting one invites a
multiplicity correction for a question nobody asked.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mcrag.eval.stats import Interval


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """One paired comparison between two configs, effect direction `b` minus `a`."""

    metric: str
    interval: Interval
    p_value: float | None  # None for a graded/cost comparison -- no closed-form test
    test: str  # "mcnemar" | "paired_bootstrap"
    split: str  # "dev" | "test" -- carried so a reporting layer can check it


def paired_bootstrap_ci(
    a: Sequence[float],
    b: Sequence[float],
    *,
    statistic: Callable[[Sequence[float]], float] = statistics.mean,
    name: str = "mean",
    seed: int = 42,
    iterations: int = 10_000,
    alpha: float = 0.05,
) -> Interval:
    """CI on `statistic(b) - statistic(a)`.

    Every resample draws the *same* question indices for both arms -- that is
    what makes this paired rather than two independent bootstraps, and is
    what lets question difficulty cancel out of the interval.
    """
    if len(a) != len(b):
        raise ValueError(f"paired arms must be the same length: {len(a)} vs {len(b)}")
    if not a:
        raise ValueError("cannot compare an empty sample")
    n = len(a)
    point = float(statistic(b)) - float(statistic(a))
    if n == 1:
        return Interval(point, point, point, 1, name, seed)

    rng = random.Random(seed)
    draws = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        draws.append(float(statistic([b[i] for i in idx])) - float(statistic([a[i] for i in idx])))
    draws.sort()
    lo = draws[int((alpha / 2) * iterations)]
    hi = draws[min(iterations - 1, int((1 - alpha / 2) * iterations))]
    return Interval(point, lo, hi, n, name, seed)


def mcnemar_p_value(n01: int, n10: int) -> float:
    """Exact two-sided McNemar p-value from the two discordant-pair counts.

    `n01` = questions where `a` missed and `b` hit; `n10` = the reverse. Under
    the null that a discordant pair is equally likely to go either way, the
    smaller count is Binomial(n01+n10, 0.5)-distributed; the p-value is twice
    its lower-tail probability, capped at 1.0.
    """
    if n01 < 0 or n10 < 0:
        raise ValueError("discordant counts must be non-negative")
    n = n01 + n10
    if n == 0:
        return 1.0
    k = min(n01, n10)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2 * tail)


def mcnemar_exact(
    a: Sequence[int],
    b: Sequence[int],
    *,
    split: str,
    metric: str = "binary",
    seed: int = 42,
    iterations: int = 10_000,
) -> ComparisonResult:
    """Paired binary (0/1 per question) outcomes for config `a` vs. config `b`.

    The p-value is McNemar's exact test on the discordant pairs. The effect
    size and its CI come from a paired bootstrap over the same 0/1
    sequences -- McNemar has no standard closed-form CI on the effect itself,
    and reusing the bootstrap keeps every reported interval built the same
    way regardless of outcome type.
    """
    if len(a) != len(b):
        raise ValueError(f"paired arms must be the same length: {len(a)} vs {len(b)}")
    n01 = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)
    n10 = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)
    p_value = mcnemar_p_value(n01, n10)
    interval = paired_bootstrap_ci(
        list(a),
        list(b),
        statistic=statistics.mean,
        name="mean_diff",
        seed=seed,
        iterations=iterations,
    )
    return ComparisonResult(
        metric=metric, interval=interval, p_value=p_value, test="mcnemar", split=split
    )


def paired_bootstrap_comparison(
    a: Sequence[float],
    b: Sequence[float],
    *,
    split: str,
    metric: str,
    statistic: Callable[[Sequence[float]], float] = statistics.mean,
    name: str = "mean",
    seed: int = 42,
    iterations: int = 10_000,
) -> ComparisonResult:
    """Graded or cost comparisons: no closed-form test, a bootstrap CI only."""
    interval = paired_bootstrap_ci(
        a, b, statistic=statistic, name=name, seed=seed, iterations=iterations
    )
    return ComparisonResult(metric=metric, interval=interval, p_value=None, test="paired_bootstrap", split=split)


class DevSplitSignificanceError(ValueError):
    """A p-value tried to reach a dev-split report. See module docstring."""


def assert_reportable(result: ComparisonResult) -> ComparisonResult:
    """The reporting-layer guard. Raises if `result` carries a p-value on dev."""
    if result.split == "dev" and result.p_value is not None:
        raise DevSplitSignificanceError(
            f"{result.metric}: a p-value was computed on the dev split "
            f"({result.p_value}) -- dev is for config selection, not "
            "inference (PLAN 4f). Score dev without McNemar, or move this "
            "comparison to the test split."
        )
    return result
