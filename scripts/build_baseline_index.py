"""Task 15: build the Phase 3a control-condition index.

Deliberately naive (PLAN Phase 3a): fixed 512-token chunks (`FixedSizeChunker`,
not the production `ParagraphChunker`), dense-only, no literal leg. This is a
one-off baseline build, not something incremental reindex needs to track, so
it chunks straight from `corpus/extracted/documents.jsonl` in memory rather
than persisting a second `corpus/chunks.jsonl` variant.

    python scripts/build_baseline_index.py

Writes `indexes/baseline_dense/` (LanceDB table), `corpus/baseline_chunks.jsonl`
(the fixed-512-token chunk set itself -- needed at eval time so a retrieved
chunk_id can be resolved back to its text for content-overlap gold matching,
`mcrag.eval.chunk_alignment`, since this chunker's ids don't match the
production `ParagraphChunker` ids the gold set was authored against), and
`indexes/baseline_embedding_cache.jsonl` -- all kept separate from the
production `indexes/dense/`/`corpus/chunks.jsonl` so this throwaway control
never gets mistaken for them.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.chunk.fixed_size_chunker import FixedSizeChunker  # noqa: E402
from mcrag.chunk.tokenizer import HuggingFaceTokenCounter  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.types import Document  # noqa: E402


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


def main() -> int:
    index_dir = Path("indexes")
    index_dir.mkdir(exist_ok=True)

    documents = load_documents(Path("corpus/extracted/documents.jsonl"))
    chunker = FixedSizeChunker(HuggingFaceTokenCounter(), chunk_tokens=512)
    chunks = [c for doc in documents for c in chunker.chunk(doc)]
    print(f"{len(documents)} documents -> {len(chunks)} fixed-512-token chunks")

    chunks_path = Path("corpus/baseline_chunks.jsonl")
    with chunks_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            row = asdict(c)
            row["crawled_at"] = c.crawled_at.isoformat()
            f.write(json.dumps(row) + "\n")
    print(f"persisted {len(chunks)} chunks -> {chunks_path}")

    dense = DenseIndex(
        db_path=index_dir / "baseline_dense",
        embedder=BgeEmbedder(),
        cache=EmbeddingCache(index_dir / "baseline_embedding_cache.jsonl"),
        model_name=MODEL_NAME,
    )
    dense.build(chunks)
    print(f"built indexes/baseline_dense with {len(chunks)} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
