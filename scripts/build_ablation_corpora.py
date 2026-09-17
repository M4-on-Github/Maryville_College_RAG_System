"""Task 18: build the two chunk sets/dense indexes the free factorial needs
that Tasks 9/15 never had a reason to build.

Task 9 (`scripts/chunk_corpus.py`) and Task 15 (`scripts/build_baseline_index.py`)
already give two of the factorial's four index-time cells: boilerplate ON x
ParagraphChunker (`corpus/chunks.jsonl` + `indexes/dense/`) and boilerplate ON x
FixedSizeChunker(512) (`corpus/baseline_chunks.jsonl` + `indexes/baseline_dense/`).
This script builds the other two -- boilerplate OFF crossed with each chunker --
from `corpus/extracted/documents_no_boilerplate.jsonl` (built by
`scripts/extract_corpus.py --no-boilerplate-filter`, PLAN's own pre-built flag
for exactly this comparison).

    python scripts/build_ablation_corpora.py

Writes `corpus/chunks_no_boilerplate.jsonl`, `corpus/baseline_chunks_no_boilerplate.jsonl`,
`indexes/dense_no_boilerplate/`, `indexes/baseline_dense_no_boilerplate/`
(plus their own embedding caches) -- kept alongside, never overwriting, the
boilerplate-ON originals.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.chunk.fixed_size_chunker import FixedSizeChunker  # noqa: E402
from mcrag.chunk.paragraph_chunker import ParagraphChunker  # noqa: E402
from mcrag.chunk.tokenizer import HuggingFaceTokenCounter  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.types import Chunk, Document  # noqa: E402

DOCS_PATH = Path("corpus/extracted/documents_no_boilerplate.jsonl")


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


def persist(chunks: list[Chunk], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            row = asdict(c)
            row["crawled_at"] = c.crawled_at.isoformat()
            f.write(json.dumps(row) + "\n")


def build_one(
    documents: list[Document],
    chunker,
    chunks_path: Path,
    index_dir: Path,
    cache_path: Path,
) -> list[Chunk]:
    chunks = [c for doc in documents for c in chunker.chunk(doc)]
    persist(chunks, chunks_path)
    print(f"{len(documents)} documents -> {len(chunks)} chunks -> {chunks_path}")

    dense = DenseIndex(
        db_path=index_dir,
        embedder=BgeEmbedder(),
        cache=EmbeddingCache(cache_path),
        model_name=MODEL_NAME,
    )
    dense.build(chunks)
    print(f"built {index_dir} with {len(chunks)} chunks")
    return chunks


def main() -> int:
    if not DOCS_PATH.exists():
        print(
            f"{DOCS_PATH} missing -- run: "
            "python scripts/extract_corpus.py --no-boilerplate-filter "
            f"--out {DOCS_PATH}"
        )
        return 1

    documents = load_documents(DOCS_PATH)
    index_dir = Path("indexes")
    index_dir.mkdir(exist_ok=True)
    counter = HuggingFaceTokenCounter()

    build_one(
        documents,
        ParagraphChunker(counter),
        Path("corpus/chunks_no_boilerplate.jsonl"),
        index_dir / "dense_no_boilerplate",
        index_dir / "embedding_cache_no_boilerplate.jsonl",
    )
    build_one(
        documents,
        FixedSizeChunker(counter, chunk_tokens=512),
        Path("corpus/baseline_chunks_no_boilerplate.jsonl"),
        index_dir / "baseline_dense_no_boilerplate",
        index_dir / "baseline_embedding_cache_no_boilerplate.jsonl",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
