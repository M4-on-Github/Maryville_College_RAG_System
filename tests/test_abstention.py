"""Task 21: the abstention threshold analysis (decisions/0009).

Every expected value here is hand-computed from the tiny inputs beside it,
never produced by calling the function under test.
"""

from __future__ import annotations

import math

import pytest

from mcrag.eval.abstention import (
    FLOOR,
    choose_tau,
    cross_validate,
    decide,
    margin,
    maxp_scores,
    normalized,
    null_percentile,
    raw_top,
    ratio_ci,
    select_method,
    stratified_kfold,
    sweep,
)

# ---- features ------------------------------------------------------------------


def test_raw_top_is_the_best_score():
    assert raw_top([1.0, 5.0, -2.0]) == 5.0


def test_margin_is_best_minus_second_best_regardless_of_input_order():
    assert margin([1.0, 5.0, 3.0]) == 2.0


def test_margin_needs_two_scores():
    with pytest.raises(ValueError):
        margin([4.0])


def test_normalized_is_a_population_z_score_of_the_top_score():
    # pool = [0, 2, 4]: mean 2, pstdev sqrt(8/3); top 4 -> 2 / sqrt(8/3)
    assert normalized(4.0, [0.0, 2.0, 4.0]) == pytest.approx(2 / math.sqrt(8 / 3))


def test_normalized_is_zero_for_a_constant_pool():
    assert normalized(3.0, [3.0, 3.0, 3.0]) == 0.0


def test_null_percentile_counts_ties_as_half():
    # null [1, 2, 2, 3], top 2 -> (1 below + 0.5 * 2 equal) / 4 = 0.5
    assert null_percentile(2.0, [1.0, 2.0, 2.0, 3.0]) == 0.5


def test_null_percentile_saturates_at_one_above_every_null_score():
    assert null_percentile(10.0, [1.0, 2.0, 3.0]) == 1.0


# ---- sweep / choose_tau ------------------------------------------------------------

FEATURES = [0.1, 0.4, 0.5, 0.9]
LABELS = [False, True, False, True]  # should_answer


def test_decide_answers_at_or_above_tau():
    assert decide(FEATURES, 0.5) == [False, False, True, True]


def test_sweep_matches_hand_computed_points():
    points = {p.tau: p for p in sweep(FEATURES, LABELS)}
    # tau 0.1: answer all 4, 2 correct
    assert points[0.1].coverage == 1.0 and points[0.1].precision == 0.5
    # tau 0.4: answer {0.4, 0.5, 0.9}, correct {0.4, 0.9} -> 2/3; no should-answer refused
    assert points[0.4].precision == pytest.approx(2 / 3)
    assert points[0.4].false_refusal_rate == 0.0
    # tau 0.5: answer {0.5, 0.9}, correct {0.9} -> 1/2; refused one of two should-answer
    assert points[0.5].precision == 0.5 and points[0.5].false_refusal_rate == 0.5
    # tau 0.9: answer {0.9}, correct -> 1.0
    assert points[0.9].precision == 1.0 and points[0.9].coverage == 0.25


def test_sweep_includes_the_answer_nothing_point():
    last = sweep(FEATURES, LABELS)[-1]
    assert last.tau == math.inf
    assert last.n_answered == 0 and last.coverage == 0.0 and last.precision is None
    assert last.false_refusal_rate == 1.0


def test_choose_tau_is_the_lowest_threshold_meeting_the_floor():
    assert choose_tau(FEATURES, LABELS, floor=0.95) == 0.9
    assert choose_tau(FEATURES, LABELS, floor=0.6) == 0.4


def test_choose_tau_takes_max_coverage_even_when_precision_is_not_monotone():
    # floor 0.75. tau 0.1 -> 3/4 = 0.75 (meets); tau 0.2 -> 2/3 (fails);
    # tau 0.3 -> 1/2 (fails); tau 0.4 -> 1/1 (meets). Maximum coverage at the
    # floor is tau 0.1 -- a scan that stopped at the first failure from the top
    # would wrongly return 0.4.
    features = [0.1, 0.2, 0.3, 0.4]
    labels = [True, True, False, True]
    assert choose_tau(features, labels, floor=0.75) == 0.1


def test_choose_tau_with_every_question_correct_answers_everything():
    assert choose_tau([0.2, 0.3, 0.5, 0.8], [True, True, True, True], floor=0.95) == 0.2


def test_choose_tau_is_infinite_when_nothing_meets_the_floor():
    assert choose_tau([0.1, 0.2], [False, False]) == math.inf


def test_default_floor_is_the_pre_registered_95_percent():
    assert FLOOR == 0.95


# ---- stratified_kfold / cross_validate ---------------------------------------------

STRATA = ["a"] * 6 + ["b"] * 4


def test_every_index_lands_in_exactly_one_fold():
    folds = stratified_kfold(STRATA, k=3, seed=7)
    flat = sorted(i for fold in folds for i in fold)
    assert flat == list(range(len(STRATA)))


def test_folds_are_balanced_within_each_stratum():
    folds = stratified_kfold(STRATA, k=2, seed=7)
    for fold in folds:
        assert sum(1 for i in fold if STRATA[i] == "a") == 3
        assert sum(1 for i in fold if STRATA[i] == "b") == 2


def test_folds_are_deterministic_for_a_seed():
    assert stratified_kfold(STRATA, k=3, seed=7) == stratified_kfold(STRATA, k=3, seed=7)


def test_cross_validation_fits_each_fold_without_its_own_questions():
    features = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
    labels = [False, False, True, False, True, True, True, False, True, True]
    strata = ["s"] * 10
    result = cross_validate(features, labels, strata, k=5, seed=3, floor=0.8)
    folds = stratified_kfold(strata, k=5, seed=3)
    for fold, tau in zip(folds, result.fold_taus):
        train = [i for i in range(10) if i not in fold]
        assert tau == choose_tau([features[i] for i in train], [labels[i] for i in train], floor=0.8)
        for i in fold:
            assert result.oof_answered[i] == (features[i] >= tau)


# ---- ratio_ci ----------------------------------------------------------------------


def test_ratio_ci_point_value_is_the_plain_ratio():
    numer = [True, False, True, False]
    denom = [True, True, True, False]
    interval = ratio_ci(numer, denom, seed=1, iterations=200)
    assert interval.value == pytest.approx(2 / 3)
    assert interval.n == 3  # the denominator count, not all rows


def test_ratio_ci_is_none_for_an_empty_denominator():
    assert ratio_ci([False, False], [False, False]) is None


# ---- select_method -------------------------------------------------------------------


def test_selects_highest_coverage_among_methods_meeting_the_floor():
    results = {"margin": (0.40, 0.96), "normalized": (0.55, 0.95), "percentile": (0.70, 0.90)}
    assert select_method(results, floor=0.95) == "normalized"


def test_falls_back_to_highest_precision_when_none_meets_the_floor():
    results = {"margin": (0.40, 0.91), "normalized": (0.55, 0.93), "percentile": (0.0, None)}
    assert select_method(results, floor=0.95) == "normalized"


def test_selection_ties_break_on_coverage_then_name():
    results = {"b": (0.5, 0.97), "a": (0.5, 0.97)}
    assert select_method(results, floor=0.95) == "a"


# ---- maxp_scores ----------------------------------------------------------------------


def test_maxp_scores_each_passage_by_its_best_window():
    seen: list[tuple[str, str]] = []

    def fake_score_pairs(pairs):
        seen.extend(pairs)
        return [10.0 if "deposit" in window else 0.0 for _, window in pairs]

    filler = " ".join(f"Unrelated sentence {i} about parking." for i in range(40))
    passages = [filler + " The deposit is refundable.", filler]
    scores = maxp_scores(fake_score_pairs, "deposit?", passages, window_chars=200)
    assert scores == [10.0, 0.0]
    assert all(len(window) <= 200 for _, window in seen)
    assert len(seen) > 2  # long passages really were windowed
