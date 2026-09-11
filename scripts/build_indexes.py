"""Task 11: build the three indexes over the persisted chunk set, via Task 10's
incremental-reindex pipeline (a from-scratch run is just the pipeline's first
run: every url is "changed").

    python scripts/build_indexes.py

Writes:
- `indexes/dense/` -- LanceDB table
- `indexes/embedding_cache.jsonl` -- (model_name, chunk_text_hash) -> vector
- `indexes/corpus.lock` -- content-hash snapshot driving future incremental runs
- `indexes/bm25.pkl`, `indexes/literal.pkl` -- pickled in-memory indexes.
  Rebuilding either from `corpus/chunks.jsonl` costs milliseconds at this
  corpus size; they're persisted anyway so a service process can load them
  without re-reading and re-chunking the whole corpus at startup.
"""

from __future__ import annotations

import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.index_pipeline import incremental_reindex  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.types import Chunk, Document  # noqa: E402


class _PrechunkedChunker:
    """Adapts a persisted chunk set to the `Chunker` interface's per-document call.

    `incremental_reindex` chunks documents itself so it stays index-agnostic
    for T10's unit tests, but Task 9's chunker output is already persisted to
    `corpus/chunks.jsonl` -- re-chunking here would silently double-chunk (and
    could drift from what T9 validated). This wraps the persisted chunks so
    the pipeline's `chunker.chunk(doc)` calls return the ones already on disk.
    """

    def __init__(self, chunks: list[Chunk]) -> None:
        self._by_url: dict[str, list[Chunk]] = {}
        for c in chunks:
            self._by_url.setdefault(c.source_url, []).append(c)

    def chunk(self, doc: Document) -> list[Chunk]:
        return self._by_url.get(doc.url, [])


def load_documents(path: Path) -> list[Document]:
    docs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line)
            docs.append(
                Document(
                    url=raw["url"],
                    title=raw.get("title", ""),
                    text=raw["text"],
                    content_hash=raw["content_hash"],
                    fetched_at=datetime.fromisoformat(raw["fetched_at"]),
                    breadcrumb=tuple(raw.get("breadcrumb") or ()),
                    silo=tuple(raw.get("silo") or ()),
                    catalog_year=raw.get("catalog_year"),
                    lastmod=raw.get("lastmod"),
                )
            )
    return docs


def load_chunks(path: Path) -> list[Chunk]:
    chunks = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line)
            chunks.append(
                Chunk(
                    chunk_id=raw["chunk_id"],
                    source_url=raw["source_url"],
                    title=raw["title"],
                    text=raw["text"],
                    heading_path=tuple(raw["heading_path"]),
                    breadcrumb=tuple(raw["breadcrumb"]),
                    silo=tuple(raw["silo"]),
                    content_hash=raw["content_hash"],
                    crawled_at=datetime.fromisoformat(raw["crawled_at"]),
                    token_count=raw["token_count"],
                    catalog_year=raw.get("catalog_year"),
                )
            )
    return chunks


def main() -> int:
    index_dir = Path("indexes")
    index_dir.mkdir(exist_ok=True)

    documents = load_documents(Path("corpus/extracted/documents.jsonl"))
    chunks = load_chunks(Path("corpus/chunks.jsonl"))
    print(f"{len(documents)} documents, {len(chunks)} persisted chunks")

    dense = DenseIndex(
        db_path=index_dir / "dense",
        embedder=BgeEmbedder(),
        cache=EmbeddingCache(index_dir / "embedding_cache.jsonl"),
        model_name=MODEL_NAME,
    )
    bm25 = BM25Index()
    literal = LiteralIndex()

    result = incremental_reindex(
        documents,
        [dense, bm25, literal],
        _PrechunkedChunker(chunks),
        index_dir / "corpus.lock",
    )

    with (index_dir / "bm25.pkl").open("wb") as f:
        pickle.dump(bm25, f)
    with (index_dir / "literal.pkl").open("wb") as f:
        pickle.dump(literal, f)

    print(
        f"{len(result.changed_urls)} changed, {len(result.removed_urls)} removed, "
        f"{result.chunks_written} chunks written (no-op: {result.is_noop})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
