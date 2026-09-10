"""Pipeline-level extraction tests: the manifest bookkeeping, not the HTML.

These use a stub Extractor rather than trafilatura. What is under test here is
whether the corpus and the manifest still agree after a run, and that question
has nothing to do with how well any particular extractor reads a page.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mcrag.crawl.fetcher import SnapshotStore
from mcrag.crawl.manifest import Manifest, Status
from mcrag.extract.boilerplate import BoilerplateFilter
from mcrag.extract.pipeline import ExtractedCorpus, empty_by_prefix, extract_all
from mcrag.interfaces import Extractor
from mcrag.types import Document, RawPage

BASE = "https://example.edu"


class StubExtractor(Extractor):
    """Returns the snapshot's text, or None for anything containing 'EMPTY'."""

    def extract(self, page: RawPage) -> Document | None:
        if "EMPTY" in page.html:
            return None
        return Document(
            url=page.url,
            title="stub",
            text=page.html,
            content_hash=page.content_hash,
            fetched_at=page.fetched_at,
        )


@pytest.fixture
def corpus(tmp_path):
    manifest = Manifest(path=tmp_path / "manifest.jsonl")
    store = SnapshotStore(tmp_path / "raw")
    pages = {
        "/a/": "alpha " * 60,
        "/b/": "beta " * 60,
        "/c/": "EMPTY",
    }
    for path, html in pages.items():
        url = BASE + path
        manifest.consider(url, source="posts-page")
        manifest.mark_fetched(
            url,
            http=200,
            content_hash=f"hash{path}",
            bytes_len=len(html),
            fetched_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )
        store.put(url, html, f"hash{path}")
    return manifest, store, tmp_path


def test_extracts_and_records_char_counts(corpus):
    manifest, store, tmp_path = corpus
    documents, stats = extract_all(manifest, store, StubExtractor())

    assert stats["extracted"] == 2
    assert stats["extraction_empty"] == 1
    for doc in documents:
        assert manifest.records[doc.url].extracted_chars == doc.char_len


def test_empty_extraction_is_recorded_not_dropped(corpus):
    manifest, store, _ = corpus
    extract_all(manifest, store, StubExtractor())

    record = manifest.records[BASE + "/c/"]
    assert record.status == Status.EXCLUDED
    assert record.reason == "extraction_empty"
    assert empty_by_prefix(manifest, BASE)["c"] == 1


def test_rerun_is_idempotent(corpus):
    """Stats must describe this run, not the leftovers of the last one."""
    manifest, store, _ = corpus
    _, first = extract_all(manifest, store, StubExtractor())
    _, second = extract_all(manifest, store, StubExtractor())
    assert dict(first) == dict(second)


def test_a_fixed_extractor_recovers_a_page_given_up_on(corpus):
    """A page marked empty last run must be retried, not written off."""
    manifest, store, _ = corpus
    extract_all(manifest, store, StubExtractor())
    assert manifest.records[BASE + "/c/"].status == Status.EXCLUDED

    class AlwaysWorks(StubExtractor):
        def extract(self, page: RawPage) -> Document | None:
            return Document(
                url=page.url,
                title="recovered",
                text="now there is text " * 20,
                content_hash=page.content_hash,
                fetched_at=page.fetched_at,
            )

    documents, stats = extract_all(manifest, store, AlwaysWorks())
    assert stats["extracted"] == 3
    assert manifest.records[BASE + "/c/"].status == Status.FETCHED
    assert manifest.records[BASE + "/c/"].reason is None


def test_redirected_page_maps_back_to_its_manifest_record(tmp_path):
    """Documents are keyed by the final URL, the manifest by the requested one."""
    manifest = Manifest(path=tmp_path / "manifest.jsonl")
    store = SnapshotStore(tmp_path / "raw")
    requested, final = BASE + "/old/", BASE + "/new/"
    html = "content " * 60

    manifest.consider(requested, source="posts-page")
    manifest.mark_fetched(
        requested, http=200, content_hash="h", bytes_len=len(html), final_url=final
    )
    store.put(requested, html, "h")

    documents, stats = extract_all(manifest, store, StubExtractor())
    assert stats["extracted"] == 1
    assert documents[0].url == final
    assert manifest.records[requested].extracted_chars == len(html)


def test_corpus_round_trips_through_disk(corpus):
    manifest, store, tmp_path = corpus
    extracted = ExtractedCorpus(tmp_path / "documents.jsonl")
    documents, _ = extract_all(manifest, store, StubExtractor(), extracted)

    reloaded = extracted.read()
    assert [d.url for d in reloaded] == sorted(d.url for d in documents)
    assert reloaded[0].fetched_at.tzinfo is not None


def test_boilerplate_only_pages_are_dropped_and_counted(tmp_path):
    manifest = Manifest(path=tmp_path / "manifest.jsonl")
    store = SnapshotStore(tmp_path / "raw")
    footer = "\n".join(["Contact Us", "Title IX", "Consumer Info", "All information 2026"])
    for i in range(6):
        url = f"{BASE}/p{i}/"
        html = (f"real content for page {i} " * 30 + "\n" + footer) if i < 4 else footer
        manifest.consider(url, source="posts-page")
        manifest.mark_fetched(url, http=200, content_hash=f"h{i}", bytes_len=len(html))
        store.put(url, html, f"h{i}")

    documents, stats = extract_all(
        manifest, store, StubExtractor(), None, BoilerplateFilter(min_pages=2, min_share=0.1)
    )

    assert stats["boilerplate_only"] == 2
    assert stats["extracted"] == 4
    assert all("Title IX" not in d.text for d in documents)
    assert manifest.records[f"{BASE}/p5/"].reason == "extraction_empty"
