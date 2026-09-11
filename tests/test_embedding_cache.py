"""Embedding cache: keyed on (model_name, chunk_text_hash), no re-embedding on a hit."""

from __future__ import annotations

from mcrag.retrieval.embedding_cache import EmbeddingCache, embed_with_cache


class _CountingEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t)), 0.0] for t in texts]


def test_embed_with_cache_only_computes_missing_texts(tmp_path):
    cache = EmbeddingCache(tmp_path / "cache.jsonl")
    embedder = _CountingEmbedder()

    vectors_1 = embed_with_cache(embedder, "model-a", ["hello", "world"], cache)
    assert embedder.calls == [["hello", "world"]]
    assert vectors_1 == [[5.0, 0.0], [5.0, 0.0]]

    vectors_2 = embed_with_cache(embedder, "model-a", ["hello", "brand-new"], cache)
    assert embedder.calls[-1] == ["brand-new"]  # "hello" was cached, not re-embedded
    assert vectors_2 == [[5.0, 0.0], [9.0, 0.0]]


def test_cache_is_scoped_per_model_name(tmp_path):
    cache = EmbeddingCache(tmp_path / "cache.jsonl")
    embedder = _CountingEmbedder()

    embed_with_cache(embedder, "model-a", ["hello"], cache)
    embed_with_cache(embedder, "model-b", ["hello"], cache)
    assert embedder.calls == [["hello"], ["hello"]]  # different model, cache miss


def test_cache_persists_across_instances(tmp_path):
    path = tmp_path / "cache.jsonl"
    embedder = _CountingEmbedder()
    embed_with_cache(embedder, "model-a", ["hello"], EmbeddingCache(path))

    reloaded = EmbeddingCache(path)
    assert len(reloaded) == 1
    embed_with_cache(embedder, "model-a", ["hello"], reloaded)
    assert len(embedder.calls) == 1  # never called again on the reloaded cache
