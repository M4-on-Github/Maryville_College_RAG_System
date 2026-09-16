"""Content-overlap matching between gold refs and a differently-chunked index."""

from __future__ import annotations

from datetime import datetime, timezone

from mcrag.eval.chunk_alignment import canonicalize_retrieved, chunks_overlap
from mcrag.types import Chunk


def make_chunk(chunk_id: str, text: str, source_url: str = "https://example.edu/a/") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_url=source_url,
        title="t",
        text=text,
        heading_path=("t",),
        breadcrumb=(),
        silo=(),
        content_hash="h",
        crawled_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        token_count=len(text.split()),
    )


def test_chunks_overlap_exact_containment():
    assert chunks_overlap("the quick brown fox jumps", "quick brown fox")


def test_chunks_overlap_false_for_unrelated_text():
    assert not chunks_overlap("the quick brown fox", "completely different sentence here")


def test_chunks_overlap_respects_threshold():
    a = "one two three four"
    b = "one two five six"  # 2/4 words shared -> ratio 0.5
    assert chunks_overlap(a, b, threshold=0.5)
    assert not chunks_overlap(a, b, threshold=0.9)


def test_canonicalize_passes_through_exact_gold_id_unchanged():
    retrieved = ["g1", "other"]
    canon = canonicalize_retrieved(retrieved, {}, ["g1"], {})
    assert canon == ["g1", "other"]


def test_canonicalize_relabels_a_content_matching_retrieved_id():
    gold_chunk = make_chunk("g1", "financial aid deadlines are in February for priority consideration")
    retrieved_chunk = make_chunk(
        "fixed-0",
        "Introduction. financial aid deadlines are in February for priority consideration. More text after.",
    )
    canon = canonicalize_retrieved(
        ["fixed-0"], {"fixed-0": retrieved_chunk}, ["g1"], {"g1": gold_chunk}
    )
    assert canon == ["g1"]


def test_canonicalize_does_not_relabel_across_different_urls():
    gold_chunk = make_chunk("g1", "financial aid deadlines", source_url="https://example.edu/a/")
    retrieved_chunk = make_chunk(
        "fixed-0", "financial aid deadlines", source_url="https://example.edu/b/"
    )
    canon = canonicalize_retrieved(
        ["fixed-0"], {"fixed-0": retrieved_chunk}, ["g1"], {"g1": gold_chunk}
    )
    assert canon == ["fixed-0"]


def test_canonicalize_claims_a_gold_id_only_once():
    # Two different fixed-size windows both cover the same gold paragraph --
    # relabeling both would let ndcg_at_k count one passage as two hits at
    # two ranks and report a score above 1.0 (T16's real run hit this: two
    # overlapping "Immigration Information" windows both matched one gold
    # chunk, producing ndcg@k=1.13).
    gold_chunk = make_chunk("g1", "report an address change within 10 days of moving")
    retrieved_a = make_chunk(
        "fixed-1", "Intro. report an address change within 10 days of moving. More."
    )
    retrieved_b = make_chunk(
        "fixed-2", "report an address change within 10 days of moving, per SEVIS rules."
    )
    canon = canonicalize_retrieved(
        ["other", "fixed-1", "fixed-2"],
        {"fixed-1": retrieved_a, "fixed-2": retrieved_b},
        ["g1"],
        {"g1": gold_chunk},
    )
    assert canon == ["other", "g1", "fixed-2"]
    assert canon.count("g1") == 1


def test_canonicalize_leaves_a_genuine_miss_unchanged():
    gold_chunk = make_chunk("g1", "financial aid deadlines are in February")
    retrieved_chunk = make_chunk("fixed-0", "completely unrelated content about the dining hall menu")
    canon = canonicalize_retrieved(
        ["fixed-0"], {"fixed-0": retrieved_chunk}, ["g1"], {"g1": gold_chunk}
    )
    assert canon == ["fixed-0"]
