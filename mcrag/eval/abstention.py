"""Task 21: calibrating the abstention threshold τ (PLAN Sec 4e, decisions/0009).

Pure functions, no model and no I/O: features computed from stored scores, the
coverage/precision sweep, the operating-point rule, stratified cross-validation,
and the pre-registered selection rule. The driver (`scripts/run_tau_calibration.py`)
supplies the scores.

A question is *answered* iff its feature ≥ τ. `labels[i]` is True iff question i
should be answered (decisions/0009: in scope, with every gold passage retrieved).
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mcrag.eval.nli_faithfulness import premise_windows
from mcrag.eval.stats import Interval

FLOOR = 0.95  # PLAN Sec 4e: of the questions answered, at least 95% must be correct


# ---- features --------------------------------------------------------------------


def raw_top(top_scores: Sequence[float]) -> float:
    return max(top_scores)


def margin(top_scores: Sequence[float]) -> float:
    if len(top_scores) < 2:
        raise ValueError("margin needs at least two scores")
    first, second = sorted(top_scores, reverse=True)[:2]
    return first - second


def normalized(top: float, pool: Sequence[float]) -> float:
    spread = statistics.pstdev(pool)
    return 0.0 if spread == 0 else (top - statistics.mean(pool)) / spread


def null_percentile(top: float, null_scores: Sequence[float]) -> float:
    below = sum(1 for s in null_scores if s < top)
    ties = sum(1 for s in null_scores if s == top)
    return (below + 0.5 * ties) / len(null_scores)


def maxp_scores(
    score_pairs: Callable[[list[tuple[str, str]]], list[float]],
    query: str,
    passages: Sequence[str],
    window_chars: int = 1000,
) -> list[float]:
    """Each passage's score is its best window's (MaxP).

    A cross-encoder reads 512 tokens; a query beside a 512-token chunk overflows
    that and would be scored on the passage's head alone. Windowing keeps every
    part of the passage in view. All pairs go to `score_pairs` in one call.
    """
    windows = [premise_windows(p, window_chars) or [p] for p in passages]
    scores = score_pairs([(query, w) for ws in windows for w in ws])
    best, start = [], 0
    for ws in windows:
        best.append(max(scores[start : start + len(ws)]))
        start += len(ws)
    return best


# ---- the sweep and the operating point --------------------------------------------


@dataclass(frozen=True, slots=True)
class CurvePoint:
    tau: float
    n_answered: int
    coverage: float  # answered / all questions
    precision: float | None  # should-answer among answered; None if nothing answered
    false_refusal_rate: float | None  # should-answer questions refused / should-answer
    wrong_answer_rate: float | None  # should-refuse among answered (1 - precision)


def decide(features: Sequence[float], tau: float) -> list[bool]:
    return [f >= tau for f in features]


def _point(features: Sequence[float], labels: Sequence[bool], tau: float) -> CurvePoint:
    answered = decide(features, tau)
    n_answered = sum(answered)
    correct = sum(1 for a, y in zip(answered, labels) if a and y)
    n_should = sum(labels)
    refused_should = sum(1 for a, y in zip(answered, labels) if y and not a)
    precision = correct / n_answered if n_answered else None
    return CurvePoint(
        tau=tau,
        n_answered=n_answered,
        coverage=n_answered / len(features),
        precision=precision,
        false_refusal_rate=refused_should / n_should if n_should else None,
        wrong_answer_rate=None if precision is None else 1 - precision,
    )


def sweep(features: Sequence[float], labels: Sequence[bool]) -> list[CurvePoint]:
    """One point per distinct feature value, ascending, then τ = +∞ (answer nothing)."""
    return [_point(features, labels, tau) for tau in sorted(set(features))] + [
        _point(features, labels, math.inf)
    ]


def choose_tau(features: Sequence[float], labels: Sequence[bool], floor: float = FLOOR) -> float:
    """Maximum coverage subject to precision ≥ floor: the *lowest* qualifying τ.

    Precision is not monotone in τ, so this checks every threshold rather than
    stopping at the first failure from either end.
    """
    for point in sweep(features, labels):
        if point.precision is not None and point.precision >= floor:
            return point.tau
    return math.inf


# ---- cross-validation ---------------------------------------------------------------


def stratified_kfold(strata: Sequence[str], k: int, seed: int) -> list[list[int]]:
    """k held-out folds, each stratum shuffled (seeded) and dealt round-robin.

    The deal position carries across strata, so fold sizes stay within one of
    each other overall as well as within each stratum.
    """
    rng = random.Random(seed)
    folds: list[list[int]] = [[] for _ in range(k)]
    position = 0
    for stratum in sorted(set(strata)):
        members = [i for i, s in enumerate(strata) if s == stratum]
        rng.shuffle(members)
        for i in members:
            folds[position % k].append(i)
            position += 1
    return [sorted(fold) for fold in folds]


@dataclass(frozen=True, slots=True)
class CVResult:
    oof_answered: list[bool]  # each question decided by a τ fitted without its own fold
    fold_taus: list[float]


def cross_validate(
    features: Sequence[float],
    labels: Sequence[bool],
    strata: Sequence[str],
    k: int = 5,
    seed: int = 42,
    floor: float = FLOOR,
) -> CVResult:
    folds = stratified_kfold(strata, k, seed)
    oof = [False] * len(features)
    taus = []
    for fold in folds:
        held_out = set(fold)
        train = [i for i in range(len(features)) if i not in held_out]
        tau = choose_tau([features[i] for i in train], [labels[i] for i in train], floor)
        taus.append(tau)
        for i in fold:
            oof[i] = features[i] >= tau
    return CVResult(oof_answered=oof, fold_taus=taus)


# ---- uncertainty and selection -------------------------------------------------------


def ratio_ci(
    numer: Sequence[bool],
    denom: Sequence[bool],
    *,
    seed: int = 42,
    iterations: int = 10_000,
    alpha: float = 0.05,
) -> Interval | None:
    """Percentile bootstrap over rows for (numer ∧ denom) / denom.

    Resamples whole rows, so the numerator and denominator stay paired. Draws
    whose denominator is empty are skipped rather than scored. Returns None when
    the ratio is undefined on the original data. `n` is the denominator count.
    """
    rows = list(zip(numer, denom))
    n_denom = sum(1 for _, d in rows if d)
    if n_denom == 0:
        return None
    value = sum(1 for x, d in rows if x and d) / n_denom

    rng = random.Random(seed)
    draws = []
    for _ in range(iterations):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        d = sum(1 for _, dd in sample if dd)
        if d:
            draws.append(sum(1 for x, dd in sample if x and dd) / d)
    draws.sort()
    lo = draws[int((alpha / 2) * len(draws))]
    hi = draws[min(len(draws) - 1, int((1 - alpha / 2) * len(draws)))]
    return Interval(value, lo, hi, n_denom, "ratio", seed)


def select_method(results: dict[str, tuple[float, float | None]], floor: float = FLOOR) -> str:
    """The pre-registered rule (decisions/0009). `results[m] = (coverage, precision)`,
    both out-of-fold.

    Highest coverage among methods meeting the floor; if none does, highest
    precision. Ties break on coverage, then precision, then name, so the result
    never depends on dict order.
    """
    def precision_of(m: str) -> float:
        p = results[m][1]
        return -math.inf if p is None else p

    qualifying = [m for m in results if results[m][1] is not None and results[m][1] >= floor]
    if qualifying:
        return sorted(qualifying, key=lambda m: (-results[m][0], -precision_of(m), m))[0]
    return sorted(results, key=lambda m: (-precision_of(m), -results[m][0], m))[0]
