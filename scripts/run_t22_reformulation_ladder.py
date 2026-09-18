"""Task 22, ablation #6: the query-reformulation ladder, rungs 1-2 (free,
deterministic). Zero generation quota -- retrieval only, scored on dev.

Pre-registered in `decisions/0011-reformulation-ladder.md` before this script
ran: cumulative comparisons against the best config so far, via
`paired_bootstrap_comparison` on `all_golds_retrieved@5`. A rung is kept only
if its CI lower bound on the improvement is > 0; the ladder stops at the
first rung that doesn't clear that bar. Rungs 3-7 (decomposition,
multi-query, de-contextualization, step-back, HyDE) are metered and are
built in a later pass, contingent on rungs 1-2's outcome here.

    python scripts/run_t22_reformulation_ladder.py

Runs at the frozen retrieval config (decisions/0007): boilerplate off,
FixedSizeChunker(512), RRF fusion on, reranker off, silo boost off, k=5.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.config import Config  # noqa: E402
from mcrag.eval.ablation_runner import run_arm  # noqa: E402
from mcrag.eval.chunk_alignment import canonicalize_retrieved  # noqa: E402
from mcrag.eval.gold import load_gold_questions, load_split_lock  # noqa: E402
from mcrag.eval.retrieval_metrics import (  # noqa: E402
    all_golds_retrieved_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)
from mcrag.eval.significance import paired_bootstrap_comparison  # noqa: E402
from mcrag.eval.stats import bootstrap_ci  # noqa: E402
from mcrag.interfaces import Reformulator  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.fusion import RRFFuser  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.retrieval.reformulation import (  # noqa: E402
    AcronymDictionaryReformulator,
    ChainedReformulator,
    IdentityReformulator,
    SpellingNormalizer,
)
from mcrag.runlog import Lock, RunDir  # noqa: E402
from mcrag.types import Chunk, GoldQuestion, Hit  # noqa: E402

# The frozen config, decisions/0007: boilerplate off, FixedSizeChunker(512).
CHUNKS_PATH = Path("corpus/baseline_chunks_no_boilerplate.jsonl")
INDEX_DIR = Path("indexes/baseline_dense_no_boilerplate")
GOLD_CHUNKS_PATH = Path("corpus/chunks.jsonl")  # what gold ids are authored against

GOLD_PATH = Path("data/gold/gold_v1.jsonl")
SPLIT_LOCK_PATH = Path("data/gold/split.lock")
K = 5
CANDIDATE_K = 20
RUN_ROOT = Path("runs")
LADDER_SUMMARY_PATH = Path("runs/t22_reformulation_ladder_summary.json")

# Rung 0 is the control (today's frozen config, no reformulation) -- every
# later rung is compared against the best rung kept so far, not against rung
# 0 independently (decisions/0011, "cumulative, not independent").
RUNGS: list[Reformulator] = [
    IdentityReformulator(),
    AcronymDictionaryReformulator(),
    ChainedReformulator([AcronymDictionaryReformulator(), SpellingNormalizer()]),
]


def load_chunks(path: Path) -> list[Chunk]:
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


def build_search(dense, bm25, literal, chunk_lookup: dict[str, Chunk], reformulator: Reformulator):
    """A `search(query) -> list[Hit]` closure. `reformulator.reform()` runs
    first; when it returns more than one query, each is retrieved separately
    and the resulting Hit lists are RRF-fused as extra legs -- the same
    `RRFFuser` T18 already built, no new fusion code needed."""
    fuser = RRFFuser()

    def retrieve_one(query: str) -> list[Hit]:
        leg_results = [
            dense.search(query, CANDIDATE_K),
            bm25.search(query, CANDIDATE_K),
            literal.search(query, CANDIDATE_K),
        ]
        return fuser.fuse(leg_results, CANDIDATE_K)

    def search(query: str) -> list[Hit]:
        queries = reformulator.reform(query)
        if len(queries) == 1:
            hits = retrieve_one(queries[0])
        else:
            hits = fuser.fuse([retrieve_one(q) for q in queries], CANDIDATE_K)
        return [replace(h, chunk=chunk_lookup.get(h.chunk_id)) if h.chunk is None else h for h in hits]

    return search


def evaluate_fn_for(search, gold_lookup: dict[str, Chunk], retrieved_lookup: dict[str, Chunk]):
    def evaluate(question: GoldQuestion) -> dict[str, Any]:
        if not question.gold:
            return {"query_id": question.qid, "slice": question.slice, "skipped": "no_gold_refs"}

        hits = search(question.question)
        retrieved = [h.chunk_id for h in hits]
        canon = canonicalize_retrieved(retrieved, retrieved_lookup, question.gold, gold_lookup)

        return {
            "query_id": question.qid,
            "slice": question.slice,
            "conjunctive": question.conjunctive,
            "retrieved": canon[:K],
            "gold": list(question.gold),
            "recall@k": recall_at_k(question.gold, canon, K),
            "mrr": mrr(question.gold, canon, K),
            "ndcg@k": ndcg_at_k(question.gold, canon, K),
            "all_golds_retrieved@k": all_golds_retrieved_at_k(question.gold, canon, K),
        }

    return evaluate


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in records if "skipped" not in r]
    summary: dict[str, Any] = {
        "run": {"n_scored": str(len(scored)), "n_skipped": str(len(records) - len(scored))}
    }
    for metric in ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k"):
        values = [r[metric] for r in scored]
        summary[metric] = bootstrap_ci(values, statistics.mean, seed=42, name="mean").to_dict()
    return summary


def compare(label: str, prev_records: list[dict], curr_records: list[dict]) -> dict[str, Any]:
    """`curr - prev`, paired by query_id, on `all_golds_retrieved@5`."""
    prev = {r["query_id"]: r for r in prev_records if "skipped" not in r}
    curr = {r["query_id"]: r for r in curr_records if "skipped" not in r}
    qids = sorted(set(prev) & set(curr))
    a = [float(prev[q]["all_golds_retrieved@k"]) for q in qids]
    b = [float(curr[q]["all_golds_retrieved@k"]) for q in qids]
    result = paired_bootstrap_comparison(a, b, split="dev", metric=f"{label}:all_golds_retrieved@{K}")
    interval = result.interval.to_dict()
    kept = interval["ci_low"] > 0
    return {"label": label, "n_paired": len(qids), "b_minus_a": interval, "kept": kept}


def main() -> int:
    if not CHUNKS_PATH.exists() or not INDEX_DIR.exists():
        print(f"missing {CHUNKS_PATH} / {INDEX_DIR} -- run the frozen-config corpus/index build first")
        return 1

    dev_questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "dev"]
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
    split_lock = load_split_lock(SPLIT_LOCK_PATH)
    print(f"{len(dev_questions)} dev questions")

    chunks = load_chunks(CHUNKS_PATH)
    chunk_lookup = {c.chunk_id: c for c in chunks}
    embedder = BgeEmbedder()
    dense = DenseIndex(
        db_path=INDEX_DIR,
        embedder=embedder,
        cache=EmbeddingCache(INDEX_DIR.parent / f"{INDEX_DIR.name}_cache.jsonl"),
        model_name=MODEL_NAME,
    )
    bm25 = BM25Index()
    bm25.build(chunks)
    literal = LiteralIndex()
    literal.build(chunks)

    rung_records: list[list[dict[str, Any]]] = []
    ladder_report: list[dict[str, Any]] = []
    best_idx = 0  # rung 0 (identity) is always the starting "best so far"

    for i, reformulator in enumerate(RUNGS):
        arm = f"rung{i}_{reformulator.name}"
        config = Config.from_dict(
            {
                "name": "t22-reformulation-ladder",
                "arm": arm,
                "chunk": {"max_tokens": 512},
                "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
                "eval": {"gold_path": str(GOLD_PATH), "split": "dev"},
                "notes": f"Task 22 #6 rung {i}: reformulator={reformulator.name}.",
            }
        )
        search = build_search(dense, bm25, literal, chunk_lookup, reformulator)
        print(f"running {arm} ...", end=" ", flush=True)
        run_dir = run_arm(
            config,
            dev_questions,
            evaluate_fn_for(search, gold_lookup, chunk_lookup),
            summarize,
            root=RUN_ROOT,
        )
        run_dir.write_lock(
            Lock(kind="corpus", digest="frozen_config", detail={"chunks_path": str(CHUNKS_PATH)})
        )
        run_dir.write_lock(Lock(kind="model", digest=MODEL_NAME, detail={"embedder": MODEL_NAME}))
        run_dir.write_lock(Lock(kind="split", digest=split_lock["split_hash"], detail={"split": "dev"}))

        headline = run_dir.read_metrics()["all_golds_retrieved@k"]["value"]
        print(f"all_golds_retrieved@{K} = {headline:.3f}")
        records = list(run_dir.records())
        rung_records.append(records)

        if i == 0:
            ladder_report.append(
                {"rung": i, "arm": arm, "all_golds_retrieved@k": headline, "vs_best_so_far": None, "kept": True}
            )
            continue

        cmp = compare(arm, rung_records[best_idx], records)
        cmp["rung"] = i
        cmp["arm"] = arm
        cmp["all_golds_retrieved@k"] = headline
        ladder_report.append(cmp)
        print(
            f"  vs rung {best_idx}: {cmp['b_minus_a']['value']:+.4f} "
            f"[{cmp['b_minus_a']['ci_low']:+.4f}, {cmp['b_minus_a']['ci_high']:+.4f}] "
            f"-> {'KEPT' if cmp['kept'] else 'STOPPED'}"
        )
        if cmp["kept"]:
            best_idx = i
        else:
            print(f"ladder stops at rung {i}: CI does not clear zero over rung {best_idx}.")
            break

    out = LADDER_SUMMARY_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"headline_k": K, "best_rung": best_idx, "ladder": ladder_report}, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
