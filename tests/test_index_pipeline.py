"""Task 10: incremental reindex — content-hash diff, delete+upsert, no-op detection."""

from __future__ import annotations

from datetime import datetime, timezone

from tests._chunks import make_chunk

from mcrag.index_pipeline import incremental_reindex, load_lock
from mcrag.types import Document


def _doc(url: str, content_hash: str, text: str = "some text") -> Document:
    return Document(
        url=url,
        title="t",
        text=text,
        content_hash=content_hash,
        fetched_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )


class _FakeIndexer:
    """Records every call so a test can assert exactly what moved."""

    def __init__(self):
        self.deleted: list[str] = []
        self.upserted: list[str] = []

    def build(self, chunks):
        pass

    def upsert(self, chunks):
        self.upserted.extend(c.chunk_id for c in chunks)

    def delete_by_source_url(self, url):
        self.deleted.append(url)
        return 0


class _OneChunkPerDocChunker:
    """Deterministic stand-in: one chunk per document, id = doc url."""

    def chunk(self, doc):
        return [make_chunk(doc.url, doc.text, source_url=doc.url)]


def test_first_run_treats_every_document_as_changed(tmp_path):
    indexer = _FakeIndexer()
    docs = [_doc("https://e.edu/a/", "h1"), _doc("https://e.edu/b/", "h2")]
    result = incremental_reindex(docs, [indexer], _OneChunkPerDocChunker(), tmp_path / "corpus.lock")
    assert set(result.changed_urls) == {"https://e.edu/a/", "https://e.edu/b/"}
    assert result.removed_urls == ()
    assert not result.is_noop
    assert set(indexer.upserted) == {"https://e.edu/a/", "https://e.edu/b/"}


def test_unchanged_corpus_is_a_true_noop(tmp_path):
    indexer = _FakeIndexer()
    docs = [_doc("https://e.edu/a/", "h1")]
    lock_path = tmp_path / "corpus.lock"
    incremental_reindex(docs, [indexer], _OneChunkPerDocChunker(), lock_path)

    indexer2 = _FakeIndexer()
    result = incremental_reindex(docs, [indexer2], _OneChunkPerDocChunker(), lock_path)
    assert result.is_noop
    assert indexer2.deleted == []
    assert indexer2.upserted == []


def test_changed_page_is_deleted_then_reinserted(tmp_path):
    lock_path = tmp_path / "corpus.lock"
    indexer = _FakeIndexer()
    incremental_reindex(
        [_doc("https://e.edu/a/", "h1")], [indexer], _OneChunkPerDocChunker(), lock_path
    )

    indexer2 = _FakeIndexer()
    result = incremental_reindex(
        [_doc("https://e.edu/a/", "h2-changed")],
        [indexer2],
        _OneChunkPerDocChunker(),
        lock_path,
    )
    assert result.changed_urls == ("https://e.edu/a/",)
    assert indexer2.deleted == ["https://e.edu/a/"]
    assert indexer2.upserted == ["https://e.edu/a/"]


def test_removed_page_is_deleted_but_nothing_is_upserted(tmp_path):
    lock_path = tmp_path / "corpus.lock"
    incremental_reindex(
        [_doc("https://e.edu/a/", "h1"), _doc("https://e.edu/b/", "h2")],
        [_FakeIndexer()],
        _OneChunkPerDocChunker(),
        lock_path,
    )

    indexer2 = _FakeIndexer()
    result = incremental_reindex(
        [_doc("https://e.edu/a/", "h1")], [indexer2], _OneChunkPerDocChunker(), lock_path
    )
    assert result.removed_urls == ("https://e.edu/b/",)
    assert indexer2.deleted == ["https://e.edu/b/"]
    assert indexer2.upserted == []


def test_lock_records_the_new_content_hashes(tmp_path):
    lock_path = tmp_path / "corpus.lock"
    incremental_reindex(
        [_doc("https://e.edu/a/", "h1")], [_FakeIndexer()], _OneChunkPerDocChunker(), lock_path
    )
    assert load_lock(lock_path) == {"https://e.edu/a/": "h1"}
