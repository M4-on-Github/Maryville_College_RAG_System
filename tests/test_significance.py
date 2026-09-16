"""Task 16b: paired comparison tooling -- exact McNemar, paired bootstrap,
and the guard that keeps a p-value off a dev-split report (PLAN 4f)."""

from __future__ import annotations

import random
import statistics

import pytest

from mcrag.eval.significance import (
    ComparisonResult,
    DevSplitSignificanceError,
    assert_reportable,
    mcnemar_exact,
    mcnemar_p_value,
    paired_bootstrap_ci,
    paired_bootstrap_comparison,
)
from mcrag.eval.stats import Interval


# ---- paired_bootstrap_ci -------------------------------------------------


def test_paired_bootstrap_ci_recovers_a_constant_known_effect():
    a = [0.5] * 30
    b = [0.7] * 30  # every question improves by exactly 0.2
    iv = paired_bootstrap_ci(a, b, seed=1)
    assert iv.value == pytest.approx(0.2)
    assert iv.ci_low == pytest.approx(0.2) and iv.ci_high == pytest.approx(0.2)
    assert iv.n == 30


def test_paired_bootstrap_ci_requires_equal_length_arms():
    with pytest.raises(ValueError, match="same length"):
        paired_bootstrap_ci([1, 2], [1, 2, 3])


def test_paired_bootstrap_ci_rejects_empty_sample():
    with pytest.raises(ValueError, match="empty"):
        paired_bootstrap_ci([], [])


def test_paired_bootstrap_ci_single_observation_is_degenerate_not_an_error():
    iv = paired_bootstrap_ci([0.3], [0.5])
    assert iv.value == pytest.approx(0.2)
    assert iv.ci_low == iv.ci_high == pytest.approx(0.2)


def test_paired_bootstrap_ci_uses_median_for_cost_style_comparisons():
    a = [1.0, 1.0, 1.0, 1.0, 100.0]  # one cold-start outlier
    b = [0.8, 0.8, 0.8, 0.8, 90.0]
    iv = paired_bootstrap_ci(a, b, statistic=statistics.median, name="median_diff", seed=3)
    assert iv.value == pytest.approx(-0.2)  # the outlier does not dominate the median
    assert iv.statistic == "median_diff"


def test_paired_bootstrap_ci_resamples_the_same_question_indices_for_both_arms():
    # If a resample drew independent indices for a and b, a real per-question
    # correlation would be destroyed and the interval would widen -- the
    # narrow interval here is only possible because pairing is preserved.
    rng = random.Random(0)
    a = [rng.random() for _ in range(40)]
    b = [x + 0.15 for x in a]  # perfectly correlated, constant offset
    iv = paired_bootstrap_ci(a, b, seed=7)
    assert iv.ci_high - iv.ci_low < 0.01


# ---- mcnemar_p_value / mcnemar_exact -------------------------------------


def test_mcnemar_p_value_is_one_when_fully_symmetric():
    assert mcnemar_p_value(0, 0) == 1.0
    assert mcnemar_p_value(5, 5) == 1.0


def test_mcnemar_p_value_matches_a_hand_computed_case():
    # n01=1, n10=9: textbook exact McNemar example, p ~= 0.0215
    assert mcnemar_p_value(1, 9) == pytest.approx(0.02148, abs=1e-4)


def test_mcnemar_p_value_shrinks_as_the_imbalance_grows():
    p_balanced = mcnemar_p_value(4, 6)
    p_skewed = mcnemar_p_value(1, 9)
    assert p_skewed < p_balanced


def test_mcnemar_p_value_rejects_negative_counts():
    with pytest.raises(ValueError):
        mcnemar_p_value(-1, 3)


def test_mcnemar_exact_effect_size_matches_the_raw_mean_difference():
    a = [1, 1, 0, 0, 1, 0, 0, 0, 0, 0]
    b = [1, 1, 1, 1, 1, 1, 1, 0, 0, 0]
    result = mcnemar_exact(a, b, split="test")
    assert result.interval.value == pytest.approx(statistics.mean(b) - statistics.mean(a))
    assert result.test == "mcnemar"
    assert result.split == "test"


def test_mcnemar_exact_p_value_matches_the_discordant_counts_directly():
    a = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    b = [1, 1, 1, 1, 1, 1, 1, 1, 1, 0]
    # n01 (a=0,b=1) = 8, n10 (a=1,b=0) = 0
    result = mcnemar_exact(a, b, split="test")
    assert result.p_value == pytest.approx(mcnemar_p_value(8, 0))


def test_mcnemar_exact_requires_equal_length_arms():
    with pytest.raises(ValueError, match="same length"):
        mcnemar_exact([1, 0], [1, 0, 1], split="test")


# ---- the reporting guard --------------------------------------------------


def test_assert_reportable_raises_on_a_dev_split_p_value():
    result = mcnemar_exact([1, 0, 1, 0], [1, 1, 1, 0], split="dev")
    with pytest.raises(DevSplitSignificanceError):
        assert_reportable(result)


def test_assert_reportable_allows_a_test_split_p_value():
    result = mcnemar_exact([1, 0, 1, 0], [1, 1, 1, 0], split="test")
    assert assert_reportable(result) is result


def test_assert_reportable_allows_a_dev_bootstrap_only_comparison():
    # Graded/cost comparisons carry no p_value at all, dev or not -- ranking
    # configs on dev is exactly what these exist for.
    result = paired_bootstrap_comparison([0.5, 0.6], [0.7, 0.8], split="dev", metric="ndcg@k")
    assert result.p_value is None
    assert assert_reportable(result) is result


def test_comparison_result_never_carries_a_bare_float_interval():
    result = paired_bootstrap_comparison([0.5, 0.6], [0.7, 0.8], split="test", metric="ndcg@k")
    assert isinstance(result.interval, Interval)
    d = result.interval.to_dict()
    assert {"value", "ci_low", "ci_high", "n"} <= set(d)


# ---- calibration: does the interval cover the truth at the nominal rate --
# T16b's own verification step: "Round-trip a known-effect synthetic pair
# through both tests and confirm the CI covers the truth at the nominal rate."


def test_paired_bootstrap_ci_covers_a_known_effect_at_roughly_95_percent():
    true_effect = 0.2
    n_questions = 30
    n_replications = 100
    covered = 0
    master = random.Random(99)
    for rep in range(n_replications):
        difficulty = [master.random() for _ in range(n_questions)]
        a = [1.0 if d < 0.5 else 0.0 for d in difficulty]
        # b succeeds whenever a does, plus on an extra true_effect-wide band
        # of difficulty -- so E[mean(b) - mean(a)] = true_effect exactly.
        b = [1.0 if d < 0.5 + true_effect else 0.0 for d in difficulty]
        # Real-valued jitter so ties don't make every replication identical.
        a = [x + master.gauss(0, 0.05) for x in a]
        b = [x + master.gauss(0, 0.05) for x in b]
        iv = paired_bootstrap_ci(a, b, seed=rep, iterations=200)
        if iv.ci_low <= true_effect <= iv.ci_high:
            covered += 1
    rate = covered / n_replications
    assert 0.85 <= rate <= 1.0, f"95% CI covered the true effect {rate:.0%} of the time"


def test_mcnemar_exact_p_value_is_uniform_under_the_null():
    # Under the null (no true effect), the exact p-value should reject at
    # roughly the nominal alpha rate, not more -- the calibration check for
    # the significance side of the same round-trip.
    n_questions = 30
    n_replications = 100
    alpha = 0.05
    rejections = 0
    master = random.Random(123)
    for rep in range(n_replications):
        a = [1 if master.random() < 0.5 else 0 for _ in range(n_questions)]
        b = [1 if master.random() < 0.5 else 0 for _ in range(n_questions)]
        result = mcnemar_exact(a, b, split="test", seed=rep, iterations=200)
        if result.p_value < alpha:
            rejections += 1
    rate = rejections / n_replications
    assert rate <= 0.12, f"exact McNemar rejected the null {rate:.0%} of the time at alpha={alpha}"
