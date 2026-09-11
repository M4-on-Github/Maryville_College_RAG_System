"""Task 10: incremental reindex, driven by a content-hash diff against `corpus.lock`.

Index-agnostic: this module only knows the `Indexer`/`Chunker` interfaces, so
it drives the dense, BM25, and literal indexes identically without knowing
which is which. `lastmod` is deliberately not read here -- it is already used
as a cheap pre-filter one stage earlier, at fetch time (T5's fetcher), so a
page whose `lastmod` didn't change is never even re-extracted. By the time a
`Document` reaches this module, its `content_hash` is the only signal that
matters: it is exact, where `lastmod` is a claim the server could get wrong.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from mcrag.interfaces import Chunker, Indexer
from mcrag.types import Document


@dataclass(frozen=True, slots=True)
class ReindexResult:
    changed_urls: tuple[str, ...]
    removed_urls: tuple[str, ...]
    chunks_written: int

    @property
    def is_noop(self) -> bool:
        return not self.changed_urls and not self.removed_urls


def load_lock(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["urls"]


def _snapshot_hash(url_hashes: dict[str, str]) -> str:
    canonical = json.dumps(dict(sorted(url_hashes.items())), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_lock(path: Path, url_hashes: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"snapshot_hash": _snapshot_hash(url_hashes), "urls": dict(sorted(url_hashes.items()))}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def incremental_reindex(
    documents: list[Document],
    indexers: list[Indexer],
    chunker: Chunker,
    lock_path: Path,
) -> ReindexResult:
    """Delete-by-source_url then upsert for every changed or removed page.

    An unchanged corpus (every url's content_hash matches the lock) touches no
    indexer at all -- a true no-op, not a rebuild that happens to produce the
    same rows.
    """
    old_hashes = load_lock(lock_path)
    new_hashes = {doc.url: doc.content_hash for doc in documents}

    changed_urls = sorted(url for url, h in new_hashes.items() if old_hashes.get(url) != h)
    removed_urls = sorted(url for url in old_hashes if url not in new_hashes)

    for url in [*changed_urls, *removed_urls]:
        for indexer in indexers:
            indexer.delete_by_source_url(url)

    changed_docs = [doc for doc in documents if doc.url in set(changed_urls)]
    new_chunks = [chunk for doc in changed_docs for chunk in chunker.chunk(doc)]
    if new_chunks:
        for indexer in indexers:
            indexer.upsert(new_chunks)

    write_lock(lock_path, new_hashes)
    return ReindexResult(
        changed_urls=tuple(changed_urls),
        removed_urls=tuple(removed_urls),
        chunks_written=len(new_chunks),
    )
