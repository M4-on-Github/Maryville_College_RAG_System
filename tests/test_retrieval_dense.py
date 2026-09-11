"""The dense retrieval leg: LanceDB + a fake, deterministic embedder (no model download)."""

from __future__ import annotations

from tests._chunks import make_chunk

from mcrag.retrieval.dense import DenseIndex
from mcrag.retrieval.embedding_cache import EmbeddingCache


class _FakeEmbedder:
    """Maps text -> a 2D vector so 'closer' texts really do rank closer."""

    dim = 2

    def embed(self, texts):
        return [[float(len(t)), float(t.count("a"))] for t in texts]


def _index(tmp_path, name="db"):
    return DenseIndex(
        db_path=tmp_path / name,
        embedder=_FakeEmbedder(),
        cache=EmbeddingCache(tmp_path / "cache.jsonl"),
        model_name="fake-model",
    )


def test_build_and_search_returns_hits_joinable_to_chunk_id(tmp_path):
    index = _index(tmp_path)
    index.build([make_chunk("c1", "aaaa"), make_chunk("c2", "zzzzzzzzzzzz")])
    hits = index.search("aaaa", k=2)
    assert {h.chunk_id for h in hits} == {"c1", "c2"}
    assert hits[0].chunk_id == "c1"  # nearest vector to the query's own embedding


def test_delete_by_source_url_removes_only_matching_rows(tmp_path):
    index = _index(tmp_path)
    index.build(
        [
            make_chunk("c1", "aaaa", source_url="https://example.edu/a/"),
            make_chunk("c2", "bbbb", source_url="https://example.edu/b/"),
        ]
    )
    removed = index.delete_by_source_url("https://example.edu/a/")
    assert removed == 1
    hits = index.search("aaaa", k=5)
    assert [h.chunk_id for h in hits] == ["c2"]


def test_upsert_replaces_an_existing_chunk_id(tmp_path):
    index = _index(tmp_path)
    index.build([make_chunk("c1", "aaaa")])
    index.upsert([make_chunk("c1", "completely different text")])
    hits = index.search("completely different text", k=1)
    assert hits[0].chunk_id == "c1"


def test_search_on_empty_index_returns_empty(tmp_path):
    index = _index(tmp_path)
    assert index.search("anything", k=5) == []


def test_rebuild_with_unchanged_chunks_reuses_the_cache(tmp_path):
    cache_path = tmp_path / "cache.jsonl"
    embedder = _FakeEmbedder()
    cache = EmbeddingCache(cache_path)
    chunks = [make_chunk("c1", "aaaa"), make_chunk("c2", "bbbb")]

    DenseIndex(tmp_path / "db1", embedder, cache, "fake-model").build(chunks)
    assert len(cache) == 2

    calls = []
    real_embed = embedder.embed
    embedder.embed = lambda texts: (calls.append(list(texts)) or real_embed(texts))
    DenseIndex(tmp_path / "db2", embedder, EmbeddingCache(cache_path), "fake-model").build(chunks)
    assert calls == []  # every text was already in the reloaded cache
