"""Task 19: the calibration gate an LLM judge (Tier 3) must pass before its
output is ever reported as a metric (PLAN Sec 4d).

"The rule that makes Tier 3 legitimate: hand-score a calibration set first,
measure judge-human agreement (Cohen's kappa), use the judge only where
agreement is acceptable, and report that agreement number in the writeup.
An uncalibrated judge is worse than no judge." -- so `assert_calibrated`
mechanically enforces the boundary the same way `mcrag.eval.significance`'s
`assert_reportable` enforces the dev/test split boundary: a caller can run
`assert_calibrated` on every judge score it's about to report, rather than
trusting every call site to remember to check kappa first.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Landis & Koch's bands call 0.6-0.8 "substantial" agreement; this project
# treats "substantial" as the floor for grading answer quality (a 2/1/0
# scale, PLAN Sec 4d), not "moderate" (0.4-0.6) -- a judge that only
# moderately agrees with a human is exactly PLAN's "worse than no judge".
MIN_ACCEPTABLE_KAPPA = 0.6


class UncalibratedJudgeError(ValueError):
    """A judge's kappa against its human calibration set is below the floor,
    or no calibration was ever run -- either way, its output must not be
    reported as a metric."""


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    kappa: float
    n: int
    categories: tuple[int, ...]


def cohens_kappa(a: Sequence[int], b: Sequence[int]) -> float:
    """Unweighted Cohen's kappa for two raters over the same n items.

    kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement),
    where expected agreement is what the raters' own marginal label
    frequencies would produce by chance alone -- the standard correction
    that makes kappa harder to inflate than raw percent agreement on a
    lopsided label distribution (most answers scoring 2, say).
    """
    if len(a) != len(b):
        raise ValueError(f"raters must score the same items: got {len(a)} vs {len(b)}")
    if not a:
        raise ValueError("cohens_kappa is undefined for an empty calibration set")

    n = len(a)
    categories = sorted(set(a) | set(b))
    observed = sum(1 for x, y in zip(a, b) if x == y) / n

    freq_a = {c: sum(1 for x in a if x == c) / n for c in categories}
    freq_b = {c: sum(1 for x in b if x == c) / n for c in categories}
    expected = sum(freq_a[c] * freq_b[c] for c in categories)

    if expected == 1.0:
        # Both raters used exactly one category, unanimously -- no
        # disagreement was possible, so kappa's usual denominator is 0/0.
        # Treat that as perfect agreement rather than raising: the raters
        # agree on every item, which is the actual, unambiguous fact here.
        return 1.0
    return (observed - expected) / (1 - expected)


def calibrate_judge(judge_labels: Sequence[int], human_labels: Sequence[int]) -> CalibrationResult:
    kappa = cohens_kappa(judge_labels, human_labels)
    categories = tuple(sorted(set(judge_labels) | set(human_labels)))
    return CalibrationResult(kappa=kappa, n=len(judge_labels), categories=categories)


def assert_calibrated(
    result: CalibrationResult | None, min_kappa: float = MIN_ACCEPTABLE_KAPPA
) -> CalibrationResult:
    """Raises unless `result` exists and clears `min_kappa`. Call this at
    the point a judge score is about to be reported -- not merely once,
    trusting every downstream caller to remember."""
    if result is None:
        raise UncalibratedJudgeError(
            "no calibration has been run against a human-scored set -- "
            "PLAN Sec 4d: an uncalibrated judge is worse than no judge"
        )
    if result.kappa < min_kappa:
        raise UncalibratedJudgeError(
            f"judge kappa {result.kappa:.2f} (n={result.n}) is below the "
            f"{min_kappa:.2f} minimum against the human calibration set"
        )
    return result
