"""The literal (grep) retrieval leg: entity-triggered exact substring search."""

from __future__ import annotations

from tests._chunks import make_chunk

from mcrag.retrieval.literal import LiteralIndex, detect_entities


def test_detect_entities_finds_course_codes_and_money():
    entities = detect_entities("How much does MATH 1110 cost, around $1,500?")
    assert "MATH 1110" in entities
    assert "$1,500" in entities


def test_detect_entities_empty_for_a_plain_query():
    assert detect_entities("what is financial aid") == []


def test_search_returns_empty_when_query_has_no_entity():
    index = LiteralIndex()
    index.build([make_chunk("c1", "MATH 1110 is an intro course.")])
    assert index.search("what is financial aid", k=5) == []


def test_search_finds_exact_substring_hit():
    index = LiteralIndex()
    index.build(
        [
            make_chunk("c1", "MATH 1110 is an intro course."),
            make_chunk("c2", "This page is about something else."),
        ]
    )
    hits = index.search("Tell me about MATH 1110", k=5)
    assert [h.chunk_id for h in hits] == ["c1"]


def test_upsert_and_delete_by_source_url():
    index = LiteralIndex()
    index.build([make_chunk("c1", "MATH 1110", source_url="https://example.edu/a/")])
    index.upsert([make_chunk("c2", "MATH 1110", source_url="https://example.edu/b/")])
    assert index.delete_by_source_url("https://example.edu/a/") == 1
    hits = index.search("MATH 1110", k=5)
    assert [h.chunk_id for h in hits] == ["c2"]
