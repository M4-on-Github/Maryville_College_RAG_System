"""Task 15's naive baseline chunker: fixed-token windows, no paragraph awareness."""

from __future__ import annotations

from datetime import datetime, timezone

from mcrag.chunk.fixed_size_chunker import FixedSizeChunker
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


def chunker(chunk_tokens: int = 40) -> FixedSizeChunker:
    return FixedSizeChunker(FakeTokenCounter(), chunk_tokens=chunk_tokens)


def test_short_text_is_one_chunk():
    chunks = chunker(chunk_tokens=40).chunk(doc(words(10)))
    assert len(chunks) == 1
    assert chunks[0].token_count <= 40


def test_long_text_splits_into_multiple_fixed_windows():
    # FakeTokenCounter counts words + 2, so a ~40-token budget holds ~38 words.
    chunks = chunker(chunk_tokens=40).chunk(doc(words(100)))
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= 40 + 2  # one word's worth of slack at the boundary check


def test_empty_text_produces_no_chunks():
    assert chunker().chunk(doc("")) == []


def test_chunk_ids_are_stable_and_unique():
    chunks = chunker(chunk_tokens=10).chunk(doc(words(30)))
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    # Re-chunking the same doc must produce the same ids (incremental reindex
    # diffs by chunk_id, so this cannot depend on wall-clock or process state).
    again = chunker(chunk_tokens=10).chunk(doc(words(30)))
    assert [c.chunk_id for c in again] == ids


def test_no_paragraph_awareness_windows_ignore_paragraph_breaks():
    # Two short paragraphs that would stay separate under ParagraphChunker's
    # packing get windowed together here purely by word count.
    text = f"{words(5, 'a')}\n\n{words(5, 'b')}"
    chunks = chunker(chunk_tokens=40).chunk(doc(text))
    assert len(chunks) == 1
    assert "a0" in chunks[0].text and "b0" in chunks[0].text


def test_metadata_is_stamped_from_the_document():
    d = doc(words(5), silo=("finaid",), breadcrumb=("Admissions", "Financial Aid"))
    chunk = chunker().chunk(d)[0]
    assert chunk.silo == ("finaid",)
    assert chunk.breadcrumb == ("Admissions", "Financial Aid")
    assert chunk.source_url == d.url
    assert chunk.content_hash == d.content_hash
