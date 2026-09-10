"""Run an Extractor over the snapshot store and write the extracted corpus.

Nothing here knows which extractor it is running: the seam is the interface, so
an extraction ablation is a config change, not an edit to this file.

Empty extractions are written back to the manifest as ``extraction_empty``
rather than dropped. That status is the only reason the difference between "the
page has no answer" and "our extractor broke on that silo" is visible later.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from mcrag.crawl.fetcher import SnapshotStore
from mcrag.crawl.manifest import Manifest, Status
from mcrag.extract.boilerplate import BoilerplateFilter
from mcrag.interfaces import Extractor
from mcrag.types import Document, RawPage


class ExtractedCorpus:
    """Extracted documents on disk, one JSON object per line.

    JSONL rather than one file per document: the whole corpus is a few tens of
    megabytes, every consumer reads all of it, and one file is far cheaper to
    move, hash and diff than 2,400.
    """

    def __init__(self, path: str | Path = "corpus/extracted/documents.jsonl") -> None:
        self.path = Path(path)

    def write(self, documents: list[Document]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for doc in sorted(documents, key=lambda d: d.url):
                data = asdict(doc)
                data["fetched_at"] = doc.fetched_at.isoformat()
                data["breadcrumb"] = list(doc.breadcrumb)
                data["silo"] = list(doc.silo)
                handle.write(json.dumps(data, sort_keys=True) + "\n")
        return len(documents)

    def read(self) -> list[Document]:
        if not self.path.exists():
            return []
        documents = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            raw["fetched_at"] = datetime.fromisoformat(raw["fetched_at"])
            raw["breadcrumb"] = tuple(raw.get("breadcrumb", ()))
            raw["silo"] = tuple(raw.get("silo", ()))
            documents.append(Document(**raw))
        return documents

    def __len__(self) -> int:
        return len(self.read())


def extract_all(
    manifest: Manifest,
    store: SnapshotStore,
    extractor: Extractor,
    corpus: ExtractedCorpus | None = None,
    boilerplate: BoilerplateFilter | None = None,
) -> tuple[list[Document], Counter[str]]:
    """Extract every fetched page. Returns the documents and a tally.

    The tally is the deliverable as much as the documents are: an extraction run
    that produced 2,000 documents from 2,400 fetched pages is either fine or
    badly broken, and only the per-silo breakdown of the 400 says which.
    """
    stats: Counter[str] = Counter()
    documents: list[Document] = []
    # A Document is keyed by its canonical URL, the manifest by the URL that was
    # requested. On a redirected page those differ, so map back before writing.
    requested: dict[str, str] = {}

    # Every page we hold a snapshot for, not just those currently marked
    # ``fetched``. A page marked ``extraction_empty`` by an earlier run is
    # exactly the page a fixed extractor should be re-tried on; skipping it
    # would make each run's stats depend on the last one's failures.
    for record in sorted(manifest.records.values(), key=lambda r: r.url):
        html = store.get(record.url)
        if html is None:
            continue

        page = RawPage(
            url=record.canonical_url,
            http_status=record.http or 200,
            content_hash=record.content_hash or "",
            fetched_at=record.fetched_at or datetime.now(timezone.utc),
            html=html,
        )
        doc = extractor.extract(page)
        if doc is None:
            manifest.mark_extraction_empty(record.url)
            stats["extraction_empty"] += 1
            continue

        documents.append(doc)
        requested[doc.url] = record.url
        stats["extracted"] += 1

    if boilerplate is not None:
        documents, report = boilerplate.apply(documents)
        for url in report.dropped:
            manifest.mark_extraction_empty(requested[url])
            stats["extracted"] -= 1
            stats["boilerplate_only"] += 1
        stats["boilerplate_lines"] = len(report.lines)
        stats["boilerplate_chars_removed"] = report.chars_removed

    # Stamped only for documents that survived, and after filtering, so the
    # manifest's char count is the length of what is actually indexed. The
    # status is restored too: a page an earlier run gave up on and this one
    # extracted is a fetched page again.
    for doc in documents:
        manifest.update(
            requested[doc.url],
            status=Status.FETCHED,
            reason=None,
            extracted_chars=doc.char_len,
        )

    if corpus is not None:
        corpus.write(documents)
    manifest.save()
    return documents, stats


def empty_by_prefix(manifest: Manifest, base: str) -> Counter[str]:
    """Empty extractions grouped by top-level path.

    A flat count of failures is not actionable. A count concentrated in one path
    prefix names the template that broke.
    """
    counts: Counter[str] = Counter()
    for record in manifest.records.values():
        if record.status == Status.EXCLUDED and record.reason == "extraction_empty":
            counts[record.url.replace(base, "").strip("/").split("/")[0] or "(root)"] += 1
    return counts
