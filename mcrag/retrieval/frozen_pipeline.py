"""The one frozen retrieval config (`decisions/0007`), extracted so every
caller that needs it -- the Task 20 generation baseline, every Task 22/22c
ablation script, and now Task 24's answer service -- builds it identically
rather than each keeping its own copy to keep in sync by hand.

Boilerplate off, `FixedSizeChunker(512)`, RRF fusion on, reranker off, silo
boost off, k=5 over a 20-passage fused candidate pool. Nothing here may
change without a new decision doc: this module is the frozen config, not a
default one.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from mcrag.interfaces import Embedder
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder
from mcrag.retrieval.bm25 import BM25Index
from mcrag.retrieval.dense import DenseIndex
from mcrag.retrieval.embedding_cache import EmbeddingCache
from mcrag.retrieval.fusion import RRFFuser
from mcrag.retrieval.literal import LiteralIndex
from mcrag.types import Chunk, Hit

CHUNKS_PATH = Path("corpus/baseline_chunks_no_boilerplate.jsonl")
INDEX_DIR = Path("indexes/baseline_dense_no_boilerplate")
GOLD_CHUNKS_PATH = Path("corpus/chunks.jsonl")  # what gold ids are authored against
K = 5
CANDIDATE_K = 20


def load_chunks(path: Path) -> list[Chunk]:
    import json

    chunks = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line)
            chunks.append(
                Chunk(
                    chunk_id=raw["chunk_id"], source_url=raw["source_url"], title=raw["title"],
                    text=raw["text"], heading_path=tuple(raw["heading_path"]),
                    breadcrumb=tuple(raw["breadcrumb"]), silo=tuple(raw["silo"]),
                    content_hash=raw["content_hash"], crawled_at=datetime.fromisoformat(raw["crawled_at"]),
                    token_count=raw["token_count"], catalog_year=raw.get("catalog_year"),
                )
            )
    return chunks


def build_search(dense: DenseIndex, bm25: BM25Index, literal: LiteralIndex, chunk_lookup: dict[str, Chunk]):
    """A closure over the three legs and the fuser -- the exact shape every
    caller since Task 20 has passed to its own `evaluate_fn`."""
    fuser = RRFFuser()

    def search(query: str) -> list[Hit]:
        leg_results = [
            dense.search(query, CANDIDATE_K),
            bm25.search(query, CANDIDATE_K),
            literal.search(query, CANDIDATE_K),
        ]
        hits = fuser.fuse(leg_results, CANDIDATE_K)
        return [replace(h, chunk=chunk_lookup.get(h.chunk_id)) if h.chunk is None else h for h in hits]

    return search


def build_indexes() -> tuple[DenseIndex, BM25Index, LiteralIndex, dict[str, Chunk], Embedder]:
    """Load the frozen chunk set and stand up all three retrieval legs.

    Expensive (loads the embedder, opens the LanceDB table, builds two
    in-memory indexes) -- callers that serve more than one question should
    build this once and reuse it, not call it per request. The embedder is
    returned alongside `dense` (rather than left private inside it) so a
    caller that needs to time embedding as its own stage -- Task 24's
    per-stage `latency_ms`, since `DenseIndex.search` embeds internally with
    no seam to inject a precomputed vector -- can call it directly with the
    same instance `dense` uses, not a second one.
    """
    chunks = load_chunks(CHUNKS_PATH)
    chunk_lookup = {c.chunk_id: c for c in chunks}
    embedder = BgeEmbedder()
    dense = DenseIndex(
        db_path=INDEX_DIR, embedder=embedder,
        cache=EmbeddingCache(INDEX_DIR.parent / f"{INDEX_DIR.name}_cache.jsonl"), model_name=MODEL_NAME,
    )
    bm25 = BM25Index()
    bm25.build(chunks)
    literal = LiteralIndex()
    literal.build(chunks)
    return dense, bm25, literal, chunk_lookup, embedder
