"""Task 19: Cohen's kappa and the calibration gate that keeps an uncalibrated
judge from ever being reported as a metric (PLAN Sec 4d)."""

from __future__ import annotations

import pytest

from mcrag.eval.judge_calibration import (
    CalibrationResult,
    UncalibratedJudgeError,
    assert_calibrated,
    calibrate_judge,
    cohens_kappa,
)


# ---- cohens_kappa ------------------------------------------------------------


def test_perfect_agreement_is_kappa_1():
    a = [2, 1, 0, 2, 1, 0, 2, 2]
    assert cohens_kappa(a, a) == pytest.approx(1.0)


def test_matches_a_hand_computed_textbook_case():
    # Two raters, binary labels, classic worked example:
    # observed agreement 0.70, expected 0.54 -> kappa ~= 0.348
    a = [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    b = [1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    kappa = cohens_kappa(a, b)
    observed = sum(1 for x, y in zip(a, b) if x == y) / len(a)
    freq_a1, freq_b1 = a.count(1) / len(a), b.count(1) / len(b)
    freq_a0, freq_b0 = 1 - freq_a1, 1 - freq_b1
    expected = freq_a1 * freq_b1 + freq_a0 * freq_b0
    assert kappa == pytest.approx((observed - expected) / (1 - expected))


def test_systematic_disagreement_gives_a_low_or_negative_kappa():
    a = [0, 0, 0, 0, 1, 1, 1, 1]
    b = [1, 1, 1, 1, 0, 0, 0, 0]  # always the opposite label
    assert cohens_kappa(a, b) < 0


def test_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same items"):
        cohens_kappa([1, 2], [1, 2, 3])


def test_rejects_empty_input():
    with pytest.raises(ValueError, match="empty"):
        cohens_kappa([], [])


def test_unanimous_single_category_is_perfect_agreement_not_a_divide_by_zero():
    assert cohens_kappa([2, 2, 2, 2], [2, 2, 2, 2]) == 1.0


# ---- calibrate_judge / assert_calibrated ------------------------------------


def test_calibrate_judge_reports_kappa_n_and_categories():
    result = calibrate_judge([2, 1, 0, 2], [2, 1, 1, 2])
    assert isinstance(result, CalibrationResult)
    assert result.n == 4
    assert result.categories == (0, 1, 2)


def test_assert_calibrated_passes_a_well_calibrated_judge_through():
    result = CalibrationResult(kappa=0.75, n=25, categories=(0, 1, 2))
    assert assert_calibrated(result) is result


def test_assert_calibrated_rejects_a_judge_below_the_kappa_floor():
    result = CalibrationResult(kappa=0.4, n=25, categories=(0, 1, 2))
    with pytest.raises(UncalibratedJudgeError, match="0.40"):
        assert_calibrated(result)


def test_assert_calibrated_rejects_no_calibration_at_all():
    with pytest.raises(UncalibratedJudgeError, match="no calibration"):
        assert_calibrated(None)


def test_assert_calibrated_honors_a_custom_threshold():
    result = CalibrationResult(kappa=0.55, n=25, categories=(0, 1, 2))
    with pytest.raises(UncalibratedJudgeError):
        assert_calibrated(result, min_kappa=0.6)
    assert assert_calibrated(result, min_kappa=0.5) is result
