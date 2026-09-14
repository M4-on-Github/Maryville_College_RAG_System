"""Task 14: hand-computed retrieval metrics.

Every case here is worked out on paper in the comment above it, per T14's own
verification step -- these numbers are not just asserted, they're derivable
by a reader without running anything.
"""

from __future__ import annotations

import math

import pytest

from mcrag.eval.retrieval_metrics import (
    all_golds_retrieved_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)


def test_recall_at_k_single_gold_found():
    # gold = {c2}, retrieved top-3 = [c1, c2, c3] -> c2 is in there -> 1/1
    assert recall_at_k(["c2"], ["c1", "c2", "c3"], k=3) == 1.0


def test_recall_at_k_single_gold_not_found_within_k():
    # gold = {c9}, top-2 = [c1, c2] -> not present -> 0/1
    assert recall_at_k(["c9"], ["c1", "c2", "c3"], k=2) == 0.0


def test_recall_at_k_conjunctive_partial_credit():
    # gold = {c1, c9}, top-3 = [c1, c2, c3] -> only c1 found -> 1/2
    assert recall_at_k(["c1", "c9"], ["c1", "c2", "c3"], k=3) == 0.5


def test_mrr_first_hit_at_rank_1():
    # c1 is gold and is rank 1 -> 1/1
    assert mrr(["c1"], ["c1", "c2", "c3"], k=3) == 1.0


def test_mrr_first_hit_at_rank_3():
    # c3 is gold, appears at rank 3 -> 1/3
    assert mrr(["c3"], ["c1", "c2", "c3"], k=3) == pytest.approx(1 / 3)


def test_mrr_no_hit_within_k():
    assert mrr(["c9"], ["c1", "c2", "c3"], k=2) == 0.0


def test_ndcg_at_k_perfect_ranking():
    # single gold at rank 1: DCG = 1/log2(2) = 1; IDCG = 1/log2(2) = 1 -> nDCG = 1.0
    assert ndcg_at_k(["c1"], ["c1", "c2", "c3"], k=3) == pytest.approx(1.0)


def test_ndcg_at_k_gold_found_at_rank_2():
    # DCG = 1/log2(3); IDCG (best case, gold at rank 1) = 1/log2(2) = 1
    expected = (1 / math.log2(3)) / 1.0
    assert ndcg_at_k(["c2"], ["c1", "c2", "c3"], k=3) == pytest.approx(expected)


def test_ndcg_at_k_two_golds_at_ranks_1_and_3():
    # gold = {c1, c3}: DCG = 1/log2(2) + 1/log2(4); IDCG (both golds at ranks 1,2)
    # = 1/log2(2) + 1/log2(3)
    dcg = 1 / math.log2(2) + 1 / math.log2(4)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(["c1", "c3"], ["c1", "c2", "c3"], k=3) == pytest.approx(dcg / idcg)


def test_all_golds_retrieved_at_k_true_when_every_gold_present():
    assert all_golds_retrieved_at_k(["c1", "c3"], ["c1", "c2", "c3"], k=3) == 1.0


def test_all_golds_retrieved_at_k_false_on_partial_match():
    # This is the whole point of the metric: recall_at_k would give 0.5 here.
    assert all_golds_retrieved_at_k(["c1", "c9"], ["c1", "c2", "c3"], k=3) == 0.0
    assert recall_at_k(["c1", "c9"], ["c1", "c2", "c3"], k=3) == 0.5


def test_metrics_raise_on_empty_gold():
    with pytest.raises(ValueError):
        recall_at_k([], ["c1"], k=3)
    with pytest.raises(ValueError):
        ndcg_at_k([], ["c1"], k=3)
    with pytest.raises(ValueError):
        all_golds_retrieved_at_k([], ["c1"], k=3)


def test_hand_computed_three_questions_end_to_end():
    """T14's verification step: 3 worked questions, matched exactly.

    Q1 (single_silo): gold {a}, retrieved [a, b, c] -> recall 1.0, mrr 1.0,
        ndcg 1.0, all_golds 1.0.
    Q2 (single_silo, miss): gold {z}, retrieved [a, b, c] -> recall 0.0,
        mrr 0.0, ndcg 0.0, all_golds 0.0.
    Q3 (cross_silo, conjunctive): gold {a, c}, retrieved [a, b, c] ->
        recall 1.0 (both found), mrr 1.0 (first gold at rank 1),
        ndcg = (1/log2(2) + 1/log2(4)) / (1/log2(2) + 1/log2(3)),
        all_golds_retrieved 1.0.
    """
    retrieved = ["a", "b", "c"]

    assert recall_at_k(["a"], retrieved, k=3) == 1.0
    assert mrr(["a"], retrieved, k=3) == 1.0
    assert ndcg_at_k(["a"], retrieved, k=3) == pytest.approx(1.0)
    assert all_golds_retrieved_at_k(["a"], retrieved, k=3) == 1.0

    assert recall_at_k(["z"], retrieved, k=3) == 0.0
    assert mrr(["z"], retrieved, k=3) == 0.0
    assert ndcg_at_k(["z"], retrieved, k=3) == 0.0
    assert all_golds_retrieved_at_k(["z"], retrieved, k=3) == 0.0

    assert recall_at_k(["a", "c"], retrieved, k=3) == 1.0
    assert mrr(["a", "c"], retrieved, k=3) == 1.0
    dcg = 1 / math.log2(2) + 1 / math.log2(4)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(["a", "c"], retrieved, k=3) == pytest.approx(dcg / idcg)
    assert all_golds_retrieved_at_k(["a", "c"], retrieved, k=3) == 1.0
