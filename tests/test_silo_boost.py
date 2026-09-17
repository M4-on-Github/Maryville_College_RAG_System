"""Task 18: the silo-boost query-time factor -- a soft, additive score bump
toward whichever silo the candidate list itself already agrees on."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mcrag.retrieval.silo_boost import SiloBoostReranker
from mcrag.types import Chunk, Hit


def _chunk(chunk_id: str, silo: tuple[str, ...]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, source_url="https://example.edu/a/", title="t", text="t",
        heading_path=("t",), breadcrumb=(), silo=silo, content_hash="h",
        crawled_at=datetime(2026, 1, 1, tzinfo=timezone.utc), token_count=1,
    )


def _hit(chunk_id: str, rank: int, score: float, silo: tuple[str, ...] = ()) -> Hit:
    return Hit(chunk_id=chunk_id, score=score, leg="dense", rank=rank, chunk=_chunk(chunk_id, silo))


def test_rejects_a_negative_boost():
    with pytest.raises(ValueError):
        SiloBoostReranker(boost=-0.1)


def test_zero_boost_is_an_exact_no_op():
    hits = [_hit("a", 0, 1.0, ("financial_aid",)), _hit("b", 1, 0.9, ("admissions",))]
    result = SiloBoostReranker(boost=0.0).rerank("q", hits, k=2)
    assert result == hits[:2]


def test_boost_promotes_a_lower_scored_hit_sharing_the_modal_silo():
    # financial_aid is the modal silo (2 of 3); "c" starts behind "b" but
    # shares the modal silo, and a strong enough boost should overtake it.
    hits = [
        _hit("a", 0, 1.0, ("financial_aid",)),
        _hit("b", 1, 0.95, ("admissions",)),
        _hit("c", 2, 0.9, ("financial_aid",)),
    ]
    result = SiloBoostReranker(boost=0.2).rerank("q", hits, k=3)
    assert [h.chunk_id for h in result] == ["a", "c", "b"]


def test_boost_does_not_change_order_when_no_silo_dominates():
    # every hit has a distinct silo -- Counter.most_common(1) still picks one
    # deterministically, but the boost then only touches one hit at the tail,
    # which cannot promote it in front of higher-scored ones.
    hits = [_hit("a", 0, 1.0, ("s1",)), _hit("b", 1, 0.9, ("s2",)), _hit("c", 2, 0.1, ("s3",))]
    result = SiloBoostReranker(boost=0.1).rerank("q", hits, k=3)
    assert [h.chunk_id for h in result][0] == "a"


def test_hits_with_no_silo_label_are_left_alone_and_still_returned():
    hits = [_hit("a", 0, 1.0, ()), _hit("b", 1, 0.5, ())]
    result = SiloBoostReranker(boost=0.3).rerank("q", hits, k=2)
    assert result == hits[:2]  # nothing to boost toward -- an effective no-op


def test_reassigns_ranks_after_reordering():
    hits = [
        _hit("a", 0, 1.0, ("financial_aid",)),
        _hit("b", 1, 0.95, ("admissions",)),
        _hit("c", 2, 0.9, ("financial_aid",)),
    ]
    result = SiloBoostReranker(boost=0.2).rerank("q", hits, k=3)
    assert [h.rank for h in result] == [0, 1, 2]


def test_truncates_to_k():
    hits = [_hit(str(i), i, 1.0 - i * 0.1, ("s",)) for i in range(5)]
    assert len(SiloBoostReranker(boost=0.1).rerank("q", hits, k=2)) == 2
