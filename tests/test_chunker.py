"""The chunker, tested against the shape found in the rehearsal corpus.

`FakeTokenCounter` counts words + 2, so the arithmetic in these tests is
plain word counts -- no real tokenizer download needed to exercise the
packing, overlap, and hard-limit logic.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mcrag.chunk.paragraph_chunker import ParagraphChunker
from mcrag.chunk.tokenizer import FakeTokenCounter
from mcrag.types import Document


def doc(text: str, **kwargs) -> Document:
    kwargs.setdefault("url", "https://www.maryvillecollege.edu/about/")
    kwargs.setdefault("title", "About")
    kwargs.setdefault("content_hash", "abc123")
    kwargs.setdefault("fetched_at", datetime(2026, 9, 10, tzinfo=timezone.utc))
    return Document(text=text, **kwargs)


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def chunker(**kwargs) -> ParagraphChunker:
    kwargs.setdefault("max_tokens", 40)
    kwargs.setdefault("overlap_ratio", 0.25)
    kwargs.setdefault("hard_limit", 60)
    return ParagraphChunker(FakeTokenCounter(), **kwargs)


# ---- packing -------------------------------------------------------------


def test_short_document_is_a_single_chunk():
    chunks = chunker().chunk(doc(words(10)))
    assert len(chunks) == 1
    assert chunks[0].token_count == 12  # 10 words + CLS/SEP


def test_paragraphs_are_packed_up_to_the_target():
    text = "\n\n".join([words(15, "a"), words(15, "b"), words(15, "c")])
    chunks = chunker(max_tokens=40, overlap_ratio=0.0).chunk(doc(text))
    # Two paragraphs (15+2 tokens each counted alone, but packed together the
    # +2 overhead is only paid once per FakeTokenCounter's whole-string count)
    # must not spill a third paragraph past the 40-token target.
    assert len(chunks) >= 2
    assert all(c.token_count <= 40 for c in chunks)


def test_every_chunk_stays_under_the_hard_limit():
    text = "\n\n".join(words(20, f"p{i}") for i in range(10))
    chunks = chunker(max_tokens=40, hard_limit=60).chunk(doc(text))
    assert all(c.token_count <= 60 for c in chunks)


# ---- overlap ---------------------------------------------------------------


def test_consecutive_chunks_share_trailing_content():
    # Small paragraphs relative to the target: overlap can only ever carry a
    # whole paragraph (the chunker never splits mid-paragraph for overlap), so
    # the paragraphs have to be small enough to fit inside the overlap target.
    paragraphs = [words(5, f"p{i}_") for i in range(8)]
    chunks = chunker(max_tokens=25, overlap_ratio=0.3, hard_limit=100).chunk(
        doc("\n\n".join(paragraphs))
    )
    assert len(chunks) >= 2
    tail_of_first = chunks[0].text.split()[-3:]
    assert any(w in chunks[1].text for w in tail_of_first)


def test_zero_overlap_shares_nothing():
    text = "\n\n".join([words(20, "a"), words(20, "b")])
    chunks = chunker(max_tokens=25, overlap_ratio=0.0, hard_limit=100).chunk(doc(text))
    assert len(chunks) == 2
    assert not set(chunks[0].text.split()) & set(chunks[1].text.split())


# ---- the paragraph too long to fit ----------------------------------------


def test_a_paragraph_over_the_hard_limit_is_split_without_losing_words():
    # One giant paragraph, no breaks at all -- the Department Directory case.
    text = words(200, "name")
    chunks = chunker(max_tokens=40, hard_limit=60).chunk(doc(text))
    assert all(c.token_count <= 60 for c in chunks)
    recovered = " ".join(c.text for c in chunks).split()
    assert recovered == text.split(), "splitting must not drop or reorder words"


def test_the_hard_limit_is_asserted_on_every_chunk_produced():
    """`chunk()` re-checks every packed chunk against the real count.

    The packer is expected to already respect the limit -- this asserts that
    expectation rather than trusting it, so a future change to the packing
    logic that quietly breaks the invariant fails loudly instead of silently
    truncating at index time.
    """
    text = "\n\n".join(words(20, f"p{i}") for i in range(10))
    for chunk in chunker(max_tokens=40, hard_limit=60).chunk(doc(text)):
        assert chunk.token_count <= 60


# ---- metadata stamping -----------------------------------------------------


def test_every_chunk_carries_required_metadata():
    d = doc(
        words(10),
        breadcrumb=("About", "Faith"),
        silo=("about",),
        catalog_year="2026-2027",
    )
    chunk = chunker().chunk(d)[0]
    assert chunk.source_url == d.url
    assert chunk.title == d.title
    assert chunk.breadcrumb == ("About", "Faith")
    assert chunk.silo == ("about",)
    assert chunk.content_hash == d.content_hash
    assert chunk.crawled_at == d.fetched_at
    assert chunk.catalog_year == "2026-2027"
    assert chunk.heading_path  # best-effort until the extractor preserves real headings


def test_chunk_ids_are_stable_across_reruns():
    d = doc(words(10))
    first = chunker().chunk(d)
    second = chunker().chunk(d)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_chunk_ids_are_unique_within_a_document():
    text = "\n\n".join(words(20, f"p{i}") for i in range(5))
    chunks = chunker(max_tokens=25, hard_limit=60).chunk(doc(text))
    assert len(chunks) > 1
    assert len({c.chunk_id for c in chunks}) == len(chunks)


# ---- edge cases -------------------------------------------------------------


def test_empty_document_produces_no_chunks():
    assert chunker().chunk(doc("")) == []


def test_a_near_empty_leftover_chunk_is_dropped():
    """A trailing scrap under min_tokens must not become an unhelpful chunk."""
    text = words(38, "a") + "\n\n" + "x"
    chunks = chunker(max_tokens=40, overlap_ratio=0.0, min_tokens=5).chunk(doc(text))
    assert all(c.token_count >= 5 for c in chunks)


def test_config_rejects_a_hard_limit_below_the_target():
    with pytest.raises(ValueError, match="hard_limit"):
        ParagraphChunker(FakeTokenCounter(), max_tokens=500, hard_limit=400)


def test_config_rejects_a_nonpositive_max_tokens():
    with pytest.raises(ValueError, match="max_tokens"):
        ParagraphChunker(FakeTokenCounter(), max_tokens=0)


def test_config_rejects_an_overlap_ratio_out_of_range():
    with pytest.raises(ValueError, match="overlap_ratio"):
        ParagraphChunker(FakeTokenCounter(), overlap_ratio=1.0)
