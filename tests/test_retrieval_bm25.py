"""The BM25 retrieval leg."""

from __future__ import annotations

from tests._chunks import make_chunk

from mcrag.retrieval.bm25 import BM25Index


def test_search_ranks_the_matching_chunk_first():
    # 3+ chunks: with only 2 documents, Okapi idf is exactly 0 for any term
    # that appears in just one of them, which would mask a real match.
    index = BM25Index()
    index.build(
        [
            make_chunk("c1", "financial aid deadlines and scholarship forms"),
            make_chunk("c2", "athletics schedule for the soccer team"),
            make_chunk("c3", "campus dining hall hours and menu"),
        ]
    )
    hits = index.search("scholarship deadline", k=5)
    assert hits[0].chunk_id == "c1"


def test_search_on_empty_index_returns_empty():
    index = BM25Index()
    index.build([])
    assert index.search("anything", k=5) == []


def test_delete_by_source_url_removes_matching_chunks_and_rebuilds():
    index = BM25Index()
    index.build(
        [
            make_chunk("c1", "financial aid", source_url="https://example.edu/a/"),
            make_chunk("c2", "athletics", source_url="https://example.edu/b/"),
        ]
    )
    removed = index.delete_by_source_url("https://example.edu/a/")
    assert removed == 1
    hits = index.search("financial aid", k=5)
    assert hits == []


def test_upsert_adds_a_new_chunk_findable_by_search():
    index = BM25Index()
    index.build([make_chunk("c1", "financial aid"), make_chunk("c3", "campus dining hall")])
    index.upsert([make_chunk("c2", "athletics schedule")])
    hits = index.search("athletics", k=5)
    assert hits[0].chunk_id == "c2"
