"""Task 15: run the Phase 3a naive baseline against the dev split.

Dense-only, k=5, no literal leg, no rerank, no rewriting -- against
`indexes/baseline_dense/` (`scripts/build_baseline_index.py`'s fixed-512-token
chunks), scored on **dev**, never test. Writes a run dir under `runs/` and
regenerates `RESULTS.md`.

    python scripts/run_baseline_eval.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.config import Config  # noqa: E402
from mcrag.eval.gold import (  # noqa: E402
    find_stale_questions,
    load_chunks,
    load_gold_questions,
    load_split_lock,
)
from mcrag.eval.results_table import write_results_md  # noqa: E402
from mcrag.eval.retrieval_harness import run  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.runlog import Lock, RunDir  # noqa: E402
from mcrag.types import Chunk  # noqa: E402

K = 5
CORPUS_PATH = Path("corpus/extracted/documents.jsonl")
GOLD_PATH = Path("data/gold/gold_v1.jsonl")
SPLIT_LOCK_PATH = Path("data/gold/split.lock")
# The production chunk set gold refs are ids into, and this baseline's own
# differently-chunked set -- both needed for content-overlap gold matching
# (mcrag.eval.chunk_alignment), since a FixedSizeChunker id never equals a
# ParagraphChunker id even when the two chunks cover the same passage.
GOLD_CHUNKS_PATH = Path("corpus/chunks.jsonl")
BASELINE_CHUNKS_PATH = Path("corpus/baseline_chunks.jsonl")


def _corpus_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "absent"


def load_chunk_lookup(path: Path) -> dict[str, Chunk]:
    lookup: dict[str, Chunk] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line)
            lookup[raw["chunk_id"]] = Chunk(
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
    return lookup


def main() -> int:
    index_dir = Path("indexes")
    dense = DenseIndex(
        db_path=index_dir / "baseline_dense",
        embedder=BgeEmbedder(),
        cache=EmbeddingCache(index_dir / "baseline_embedding_cache.jsonl"),
        model_name=MODEL_NAME,
    )

    questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "dev"]
    print(f"{len(questions)} dev questions")

    config = Config.from_dict(
        {
            "name": "phase3a-retrieval-baseline",
            "arm": "3a-dense-only-naive-chunks",
            "chunk": {"max_tokens": 512, "overlap_ratio": 0.0},
            "retrieval": {"k": K, "legs": [{"class": "mcrag.retrieval.dense:DenseIndex"}]},
            "eval": {"gold_path": "data/gold/gold_v1.jsonl", "split": "dev"},
            "notes": (
                "Phase 3a control condition: fixed 512-token chunks "
                "(FixedSizeChunker, not the production ParagraphChunker), "
                "dense-only, k=5, no literal leg, no rerank, no query "
                "rewriting. Scored on dev. This is the baseline everything "
                "in Phase 4's ablations is measured against."
            ),
        }
    )

    run_dir = RunDir.create(config)
    print(f"run dir: {run_dir.path}")

    run_dir.write_lock(
        Lock(
            kind="model",
            digest=MODEL_NAME,
            detail={"embedder": MODEL_NAME, "generator": None},
        )
    )
    run_dir.write_lock(
        Lock(
            kind="corpus",
            digest=_corpus_digest(CORPUS_PATH),
            detail={"corpus": CORPUS_PATH.as_posix(), "chunker": "FixedSizeChunker(512)"},
        )
    )
    split_lock = load_split_lock(SPLIT_LOCK_PATH)
    run_dir.write_lock(
        Lock(
            kind="split",
            digest=split_lock["split_hash"],
            detail={"split_lock": SPLIT_LOCK_PATH.as_posix(), "split": "dev"},
        )
    )

    gold_lookup = load_chunk_lookup(GOLD_CHUNKS_PATH)
    retrieved_lookup = load_chunk_lookup(BASELINE_CHUNKS_PATH)
    print(f"gold_lookup: {len(gold_lookup)} chunks, retrieved_lookup: {len(retrieved_lookup)} chunks")

    # Task 35: check the pins before scoring anything. A question whose page has
    # changed since its answer was read is no longer evidence about retrieval,
    # so it drops out rather than being scored against a gold answer that may no
    # longer be on the page -- and the count it drops into is printed, because a
    # denominator that shrinks for reasons other than retrieval has to be visible.
    stale = find_stale_questions(questions, load_chunks(GOLD_CHUNKS_PATH))
    stale_qids = {s.qid for s in stale}
    for record in stale:
        print(f"stale: {record.qid} {record.gold_ref} {record.source_url}")

    metrics = run(
        dense,
        questions,
        k=K,
        run_dir=run_dir,
        seed=config.seed,
        retrieved_lookup=retrieved_lookup,
        gold_lookup=gold_lookup,
        stale_qids=stale_qids,
    )

    print(
        f"n_scored={metrics['run']['n_scored']} "
        f"n_stale={metrics['run']['n_stale']} "
        f"n_skipped={metrics['run']['n_skipped']}"
    )
    for key in ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k"):
        m = metrics[key]
        print(f"{key}: {m['value']:.3f} [{m['ci_low']:.3f}, {m['ci_high']:.3f}] (n={m['n']})")
    if "conjunctive_all_golds_retrieved@k" in metrics:
        m = metrics["conjunctive_all_golds_retrieved@k"]
        print(f"conjunctive all_golds_retrieved@k: {m['value']:.3f} (n={m['n']})")

    write_results_md()
    print("RESULTS.md regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
