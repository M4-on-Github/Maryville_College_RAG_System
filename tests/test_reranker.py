"""Task 18: the reranker query-time factor -- off (identity) and on (cross-encoder)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from mcrag.retrieval.reranker import CrossEncoderReranker, IdentityReranker
from mcrag.types import Chunk, Hit


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, source_url="https://example.edu/a/", title="t", text=text,
        heading_path=("t",), breadcrumb=(), silo=(), content_hash="h",
        crawled_at=datetime(2026, 1, 1, tzinfo=timezone.utc), token_count=len(text.split()),
    )


def _hit(chunk_id: str, rank: int, score: float = 1.0, chunk: Chunk | None = None) -> Hit:
    return Hit(chunk_id=chunk_id, score=score, leg="dense", rank=rank, chunk=chunk)


# ---- IdentityReranker -------------------------------------------------------


def test_identity_reranker_changes_nothing_but_length():
    hits = [_hit("a", 0), _hit("b", 1), _hit("c", 2)]
    result = IdentityReranker().rerank("q", hits, k=2)
    assert result == hits[:2]


def test_identity_reranker_on_empty_hits():
    assert IdentityReranker().rerank("q", [], k=5) == []


# ---- CrossEncoderReranker: construction and orchestration, not the real model ----
# The model itself downloads weights over the network -- not exercised here,
# matching the project's existing convention of not unit-testing BgeEmbedder's
# real model either. `_load` is monkeypatched so these tests run offline.


def test_cross_encoder_reranker_does_not_load_a_model_at_construction():
    reranker = CrossEncoderReranker()
    assert reranker._model is None  # importing/constructing must not touch the network


def test_cross_encoder_reranker_reorders_by_predicted_score():
    reranker = CrossEncoderReranker()
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.1, 0.9]  # second pair scores higher
    reranker._model = fake_model

    hits = [_hit("a", 0, chunk=_chunk("a", "irrelevant")), _hit("b", 1, chunk=_chunk("b", "relevant"))]
    result = reranker.rerank("q", hits, k=2)
    assert [h.chunk_id for h in result] == ["b", "a"]
    assert [h.rank for h in result] == [0, 1]


def test_cross_encoder_reranker_leaves_chunkless_hits_at_the_tail():
    reranker = CrossEncoderReranker()
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.5]
    reranker._model = fake_model

    scored = _hit("a", 0, chunk=_chunk("a", "text"))
    chunkless = _hit("b", 1, chunk=None)
    result = reranker.rerank("q", [scored, chunkless], k=2)
    assert [h.chunk_id for h in result] == ["a", "b"]


def test_cross_encoder_reranker_is_a_no_op_with_no_scorable_hits():
    reranker = CrossEncoderReranker()
    hits = [_hit("a", 0, chunk=None), _hit("b", 1, chunk=None)]
    assert reranker.rerank("q", hits, k=2) == hits


def test_cross_encoder_reranker_truncates_to_k():
    reranker = CrossEncoderReranker()
    fake_model = MagicMock()
    fake_model.predict.return_value = [0.9, 0.5, 0.1]
    reranker._model = fake_model
    hits = [_hit(c, i, chunk=_chunk(c, c)) for i, c in enumerate(["a", "b", "c"])]
    assert len(reranker.rerank("q", hits, k=1)) == 1
