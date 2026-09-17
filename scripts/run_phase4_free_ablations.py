"""Task 18: the free retrieval factorial -- boilerplate x chunking scheme
(index-time, 4 builds) x reranker x fusion mode x silo boost (query-time, 8
per build) = 32 cells, scored on dev, zero generation calls.

`k` is swept *inside* each cell (3, 5, 10, 20), not as its own factor -- PLAN
Sec 2c already couples chunk size and k, so treating it as orthogonal would
misrepresent the design. Each cell's `metrics.json` carries the primary
metric (`all_golds_retrieved@k`) at every k; the headline value used for the
factorial analysis is k=5, matching the k every prior Phase 3 run reported at.

    python scripts/run_phase4_free_ablations.py

Requires `scripts/extract_corpus.py --no-boilerplate-filter` and
`scripts/build_ablation_corpora.py` to have already been run (the
boilerplate-OFF chunk sets/indexes this script's other two index-time cells
need; the boilerplate-ON ones already exist from Tasks 9/15).

⚠️ `extract_corpus.py` writes back to whatever `--manifest` path it's given
(default `corpus/manifest.jsonl`, the *production* manifest) as a side
effect of scoring `extraction_empty`/`boilerplate_only` per page -- running
it with `--no-boilerplate-filter` overwrites that manifest with the
boilerplate-OFF run's per-page outcomes, silently corrupting the record of
what the real (boilerplate-ON) production crawl actually did. Either pass
`--manifest corpus/manifest_scratch.jsonl` for this comparison, or
`git checkout -- corpus/manifest.jsonl` immediately after.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from dataclasses import replace
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any

# This is a zero-quota, zero-*network* sweep once weights are cached (both
# BgeEmbedder and CrossEncoderReranker load lazily from the local HF cache).
# Without this, an ordinary HF "is there a newer version" HEAD check runs on
# every single reranker construction -- 16 of the 32 cells -- and a single
# transient DNS hiccup mid-sweep turns a free, offline run into one that
# fails on flaky network it never needed to depend on.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.config import Config  # noqa: E402
from mcrag.eval.ablation_runner import run_arm  # noqa: E402
from mcrag.eval.chunk_alignment import canonicalize_retrieved  # noqa: E402
from mcrag.eval.factorial import Cell, factorial_effects  # noqa: E402
from mcrag.eval.gold import load_gold_questions, load_split_lock  # noqa: E402
from mcrag.eval.retrieval_metrics import (  # noqa: E402
    all_golds_retrieved_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)
from mcrag.eval.stats import Interval, bootstrap_ci  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.fusion import RRFFuser  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.retrieval.reranker import CrossEncoderReranker, IdentityReranker  # noqa: E402
from mcrag.retrieval.silo_boost import SiloBoostReranker  # noqa: E402
from mcrag.runlog import Lock, RunDir  # noqa: E402
from mcrag.types import Chunk, GoldQuestion, Hit  # noqa: E402

GOLD_PATH = Path("data/gold/gold_v1.jsonl")
SPLIT_LOCK_PATH = Path("data/gold/split.lock")
GOLD_CHUNKS_PATH = Path("corpus/chunks.jsonl")  # what the gold set's ids are authored against

K_LEVELS = (3, 5, 10, 20)
CANDIDATE_K = 20  # per leg, pre-fusion/rerank -- also the largest K_LEVELS value
HEADLINE_K = 5  # matches every prior Phase 3 report; used for the factorial analysis
SILO_BOOST_ON = 0.15
RUN_ROOT = Path("runs")  # flat, so scripts/generate_results.py's leaderboard picks up all 32 rows
FACTORIAL_SUMMARY_PATH = Path("runs/phase4_free_factorial_summary.json")

INDEX_TIME_CELLS = {
    (True, "paragraph"): ("corpus/chunks.jsonl", "indexes/dense"),
    (True, "fixed512"): ("corpus/baseline_chunks.jsonl", "indexes/baseline_dense"),
    (False, "paragraph"): ("corpus/chunks_no_boilerplate.jsonl", "indexes/dense_no_boilerplate"),
    (False, "fixed512"): (
        "corpus/baseline_chunks_no_boilerplate.jsonl",
        "indexes/baseline_dense_no_boilerplate",
    ),
}


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


def _attach_chunks(hits: list[Hit], lookup: dict[str, Chunk]) -> list[Hit]:
    return [replace(h, chunk=lookup.get(h.chunk_id)) if h.chunk is None else h for h in hits]


def build_pipeline(
    dense, bm25, literal, chunk_lookup: dict[str, Chunk], *, fusion: bool, reranker: bool, silo_boost: bool
):
    """A `search(query) -> list[Hit]` closure for one of the 8 query-time arms."""
    fuser = RRFFuser() if fusion else None
    booster = SiloBoostReranker(boost=SILO_BOOST_ON if silo_boost else 0.0)
    rr = CrossEncoderReranker() if reranker else IdentityReranker()

    def search(query: str) -> list[Hit]:
        if fusion:
            leg_results = [
                dense.search(query, CANDIDATE_K),
                bm25.search(query, CANDIDATE_K),
                literal.search(query, CANDIDATE_K),
            ]
            hits = fuser.fuse(leg_results, CANDIDATE_K)
        else:
            hits = dense.search(query, CANDIDATE_K)
        hits = _attach_chunks(hits, chunk_lookup)
        hits = booster.rerank(query, hits, CANDIDATE_K)
        hits = rr.rerank(query, hits, CANDIDATE_K)
        return hits

    return search


def evaluate_fn_for(search, gold_lookup: dict[str, Chunk], retrieved_lookup: dict[str, Chunk]):
    def evaluate(question: GoldQuestion) -> dict[str, Any]:
        if not question.gold:
            return {"query_id": question.qid, "slice": question.slice, "skipped": "no_gold_refs"}

        hits = search(question.question)
        retrieved = [h.chunk_id for h in hits]
        canon = canonicalize_retrieved(retrieved, retrieved_lookup, question.gold, gold_lookup)

        by_k = {}
        for k in K_LEVELS:
            by_k[str(k)] = {
                "recall@k": recall_at_k(question.gold, canon, k),
                "mrr": mrr(question.gold, canon, k),
                "ndcg@k": ndcg_at_k(question.gold, canon, k),
                "all_golds_retrieved@k": all_golds_retrieved_at_k(question.gold, canon, k),
            }
        return {
            "query_id": question.qid,
            "slice": question.slice,
            "conjunctive": question.conjunctive,
            "retrieved": canon[:HEADLINE_K],
            "gold": list(question.gold),
            "by_k": by_k,
        }

    return evaluate


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in records if "skipped" not in r]
    summary: dict[str, Any] = {
        "run": {"n_scored": str(len(scored)), "n_skipped": str(len(records) - len(scored))}
    }
    # Flat, top-level keys at HEADLINE_K too -- this is what lets the existing
    # `mcrag.eval.results_table` leaderboard (Task 15's METRIC_COLUMNS) render
    # every one of these 32 cells as an ordinary RESULTS.md row, unchanged.
    for metric in ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k"):
        values = [r["by_k"][str(HEADLINE_K)][metric] for r in scored]
        summary[metric] = bootstrap_ci(values, statistics.mean, seed=42, name="mean").to_dict()
    for k in K_LEVELS:
        for metric in ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k"):
            values = [r["by_k"][str(k)][metric] for r in scored]
            summary.setdefault(f"k={k}", {})[metric] = bootstrap_ci(
                values, statistics.mean, seed=42, name="mean"
            ).to_dict()
    conjunctive = [r for r in scored if r.get("conjunctive")]
    if conjunctive:
        for k in K_LEVELS:
            values = [r["by_k"][str(k)]["all_golds_retrieved@k"] for r in conjunctive]
            summary.setdefault(f"conjunctive_k={k}", {})["all_golds_retrieved@k"] = bootstrap_ci(
                values, statistics.mean, seed=42, name="mean"
            ).to_dict()
    return summary


def main() -> int:
    for boilerplate, scheme in INDEX_TIME_CELLS:
        chunks_path, index_dir = INDEX_TIME_CELLS[(boilerplate, scheme)]
        if not Path(chunks_path).exists() or not Path(index_dir).exists():
            print(
                f"missing {chunks_path} / {index_dir} -- run "
                "scripts/extract_corpus.py --no-boilerplate-filter and "
                "scripts/build_ablation_corpora.py first"
            )
            return 1

    dev_questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "dev"]
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
    split_lock = load_split_lock(SPLIT_LOCK_PATH)
    print(f"{len(dev_questions)} dev questions")

    query_time_arms = list(product((False, True), repeat=3))  # fusion, reranker, silo_boost
    cell_results: list[tuple[dict[str, bool], RunDir]] = []

    for boilerplate, scheme in sorted(INDEX_TIME_CELLS, key=str):
        chunks_path, index_dir = INDEX_TIME_CELLS[(boilerplate, scheme)]
        chunks = load_chunks(Path(chunks_path))
        chunk_lookup = {c.chunk_id: c for c in chunks}
        print(f"\n== index-time cell: boilerplate={boilerplate} chunking={scheme} "
              f"({len(chunks)} chunks) ==")

        embedder = BgeEmbedder()
        dense = DenseIndex(
            db_path=Path(index_dir),
            embedder=embedder,
            cache=EmbeddingCache(Path(index_dir).parent / f"{Path(index_dir).name}_cache.jsonl"),
            model_name=MODEL_NAME,
        )
        bm25 = BM25Index()
        bm25.build(chunks)
        literal = LiteralIndex()
        literal.build(chunks)

        for fusion, reranker, silo_boost in query_time_arms:
            arm = (
                f"bp_{'on' if boilerplate else 'off'}-{scheme}"
                f"-fusion_{'on' if fusion else 'off'}"
                f"-rerank_{'on' if reranker else 'off'}"
                f"-silo_{'on' if silo_boost else 'off'}"
            )
            config = Config.from_dict(
                {
                    "name": "phase4-free-factorial",
                    "arm": arm,
                    "chunk": {"max_tokens": 512 if scheme == "fixed512" else 400},
                    "retrieval": {
                        "k": HEADLINE_K,
                        "candidate_k": CANDIDATE_K,
                        "silo_boost": SILO_BOOST_ON if silo_boost else 0.0,
                    },
                    "eval": {"gold_path": str(GOLD_PATH), "split": "dev"},
                    "notes": (
                        f"Task 18 free factorial cell: boilerplate={boilerplate}, "
                        f"chunking={scheme}, fusion={fusion}, reranker={reranker}, "
                        f"silo_boost={silo_boost}."
                    ),
                }
            )
            search = build_pipeline(
                dense, bm25, literal, chunk_lookup,
                fusion=fusion, reranker=reranker, silo_boost=silo_boost,
            )
            print(f"  running {arm} ...", end=" ", flush=True)
            run_dir = run_arm(
                config,
                dev_questions,
                evaluate_fn_for(search, gold_lookup, chunk_lookup),
                summarize,
                root=RUN_ROOT,
            )
            run_dir.write_lock(
                Lock(kind="corpus", digest=f"{boilerplate}+{scheme}", detail={"chunks_path": chunks_path})
            )
            run_dir.write_lock(Lock(kind="model", digest=MODEL_NAME, detail={"embedder": MODEL_NAME}))
            run_dir.write_lock(
                Lock(kind="split", digest=split_lock["split_hash"], detail={"split": "dev"})
            )
            headline = run_dir.read_metrics()[f"k={HEADLINE_K}"]["all_golds_retrieved@k"]["value"]
            print(f"all_golds_retrieved@{HEADLINE_K} = {headline:.3f}")
            cell_results.append(
                (
                    {
                        "boilerplate": boilerplate,
                        "chunking_fixed512": scheme == "fixed512",
                        "fusion": fusion,
                        "reranker": reranker,
                        "silo_boost": silo_boost,
                    },
                    run_dir,
                )
            )

    cells = [
        Cell(levels=levels, value=run_dir.read_metrics()[f"k={HEADLINE_K}"]["all_golds_retrieved@k"]["value"])
        for levels, run_dir in cell_results
    ]
    result = factorial_effects(cells)

    print(f"\n=== main effects (all_golds_retrieved@{HEADLINE_K}, {result.n_cells} cells) ===")
    for factor, effect in sorted(result.main_effects.items(), key=lambda kv: -abs(kv[1])):
        print(f"  {factor:<18} {effect:+.4f}")

    print("\n=== two-way interactions ===")
    for pair, effect in sorted(result.interactions.items(), key=lambda kv: -abs(kv[1])):
        print(f"  {pair[0]} x {pair[1]:<18} {effect:+.4f}")

    out = FACTORIAL_SUMMARY_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "headline_k": HEADLINE_K,
                "n_cells": result.n_cells,
                "main_effects": result.main_effects,
                "interactions": {f"{a}*{b}": v for (a, b), v in result.interactions.items()},
                "cells": [{"levels": c.levels, "value": c.value} for c in cells],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
