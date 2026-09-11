"""Document -> Chunk over the whole corpus, persisted to `corpus/chunks.jsonl`.

Task 9 built and validated `ParagraphChunker` in-memory against the corpus;
nothing before this script wrote the result to disk. Task 10/11 (incremental
reindex, the three indexes) need a stable chunk set to diff and index against,
and Task 13 (gold-set authoring) needs real chunk ids to write heading/chunk-
level gold refs against -- both need this file to exist.

    python scripts/chunk_corpus.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.chunk.paragraph_chunker import ParagraphChunker  # noqa: E402
from mcrag.chunk.tokenizer import HuggingFaceTokenCounter  # noqa: E402
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
    docs = load_documents(Path("corpus/extracted/documents.jsonl"))
    chunker = ParagraphChunker(HuggingFaceTokenCounter())

    out_path = Path("corpus/chunks.jsonl")
    total = 0
    max_tokens_seen = 0
    with out_path.open("w", encoding="utf-8") as f:
        for doc in docs:
            for chunk in chunker.chunk(doc):
                row = asdict(chunk)
                row["crawled_at"] = chunk.crawled_at.isoformat()
                f.write(json.dumps(row) + "\n")
                total += 1
                max_tokens_seen = max(max_tokens_seen, chunk.token_count)

    print(f"{len(docs)} documents -> {total} chunks, max {max_tokens_seen} tokens -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
