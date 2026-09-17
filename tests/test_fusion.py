"""Task 18: reciprocal rank fusion, the query-time 'fusion mode' factor."""

from __future__ import annotations

import pytest

from mcrag.retrieval.fusion import RRFFuser
from mcrag.types import Hit


def _hit(chunk_id: str, rank: int, leg: str, score: float = 1.0) -> Hit:
    return Hit(chunk_id=chunk_id, score=score, leg=leg, rank=rank)


def test_rejects_a_non_positive_k_constant():
    with pytest.raises(ValueError):
        RRFFuser(k_constant=0)


def test_a_chunk_ranked_by_every_leg_outranks_one_ranked_by_one():
    dense = [_hit("a", 0, "dense"), _hit("b", 1, "dense")]
    bm25 = [_hit("a", 0, "bm25"), _hit("c", 1, "bm25")]
    literal = [_hit("a", 0, "literal")]
    fused = RRFFuser().fuse([dense, bm25, literal], k=3)
    assert fused[0].chunk_id == "a"
    assert set(h.chunk_id for h in fused) == {"a", "b", "c"}


def test_fused_score_matches_the_rrf_formula():
    fuser = RRFFuser(k_constant=60)
    dense = [_hit("a", 0, "dense"), _hit("b", 1, "dense")]
    bm25 = [_hit("b", 0, "bm25")]
    fused = {h.chunk_id: h.score for h in fuser.fuse([dense, bm25], k=2)}
    assert fused["a"] == pytest.approx(1 / 60)
    assert fused["b"] == pytest.approx(1 / 61 + 1 / 60)


def test_leg_name_records_every_contributing_leg():
    dense = [_hit("a", 0, "dense")]
    bm25 = [_hit("a", 0, "bm25")]
    fused = RRFFuser().fuse([dense, bm25], k=1)
    assert fused[0].leg == "bm25+dense"


def test_ranks_are_reassigned_0_based_in_fused_order():
    dense = [_hit("a", 0, "dense"), _hit("b", 1, "dense")]
    fused = RRFFuser().fuse([dense], k=2)
    assert [h.rank for h in fused] == [0, 1]


def test_truncates_to_k():
    dense = [_hit(str(i), i, "dense") for i in range(10)]
    fused = RRFFuser().fuse([dense], k=3)
    assert len(fused) == 3


def test_empty_leg_results_produce_no_hits():
    assert RRFFuser().fuse([[], []], k=5) == []


def test_a_single_leg_preserves_its_own_rank_order():
    dense = [_hit("a", 0, "dense"), _hit("b", 1, "dense"), _hit("c", 2, "dense")]
    fused = RRFFuser().fuse([dense], k=3)
    assert [h.chunk_id for h in fused] == ["a", "b", "c"]
