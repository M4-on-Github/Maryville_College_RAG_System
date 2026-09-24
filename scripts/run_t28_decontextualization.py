"""Task 28, PLAN Sec4c step 5: does de-contextualizing a follow-up improve
retrieval on the multi-turn slice?

Pre-registered in `decisions/0015-decontextualization.md` **before this script
ran**: pool, arms, metric, bar and adoption rule are all fixed there. In
short --

    pool      multi_turn dev+train, n=9 (primary); dev-only n=3 (secondary)
              test (n=6) excluded: spent once at T22b, not touched here
    arm 0     IdentityReformulator          free   (control = shipped today)
    arm 1     HistoryConcatenationReformulator  free
    arm 2     LlmDecontextualizer           metered, 1 short call/question
    metric    all_golds_retrieved@5 (== recall@5: 1 gold ref per question)
    bar       >=3 of 9 improved AND 0 regressed; free arm wins a tie;
              arm 2 must also exceed its own noise floor

The bar is stated in questions, not in a CI lower bound, because at n=9 a
bootstrap CI is not an informative decision rule -- see decisions/0015. CIs
are printed anyway, as context.

    python scripts/run_t28_decontextualization.py            # arms 0+1 only
    python scripts/run_t28_decontextualization.py --metered   # + arm 2 + noise

**`--metered` spends generation quota** (~9 short rewrites, plus ~9 more for
the noise-floor rerun). Without the flag arm 2 does not run at all, so the
free arms can be re-run any number of times at no cost.

Runs at the frozen retrieval config (decisions/0007): boilerplate off,
FixedSizeChunker(512), RRF fusion on, retrieval reranker off, silo boost off,
k=5, candidate_k=20.
"""

from __future__ import annotations

import argparse
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
from mcrag.generate.ollama_cloud import OllamaCloudGenerator  # noqa: E402
from mcrag.interfaces import Reformulator  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.fusion import RRFFuser  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.retrieval.reformulation import (  # noqa: E402
    HistoryConcatenationReformulator,
    IdentityReformulator,
    LlmDecontextualizer,
)
from mcrag.types import Chunk, GoldQuestion, Hit  # noqa: E402

# The frozen config, decisions/0007.
CHUNKS_PATH = Path("corpus/baseline_chunks_no_boilerplate.jsonl")
INDEX_DIR = Path("indexes/baseline_dense_no_boilerplate")
GOLD_CHUNKS_PATH = Path("corpus/chunks.jsonl")  # what gold ids are authored against

GOLD_PATH = Path("data/gold/gold_v1.jsonl")
SPLIT_LOCK_PATH = Path("data/gold/split.lock")
K = 5
CANDIDATE_K = 20
SLICE = "multi_turn"
PRIMARY_SPLITS = ("dev", "train")  # decisions/0015; test is excluded, deliberately
SECONDARY_SPLITS = ("dev",)
MODEL = "gemma4:31b"  # Checkpoint E, decisions/0010
SUMMARY_PATH = Path("runs/t28_decontextualization_summary.json")

# Pre-registered bar (decisions/0015): stated in questions, not in a CI.
MIN_IMPROVED = 3


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
    """`search(query, history) -> (hits, rewritten_query)`.

    Differs from `scripts/run_t22_reformulation_ladder.py`'s `build_search` in
    exactly one way that matters: it **passes `history` to `reform()`**. The
    ladder's version called `reform(query)` with no history, which was
    harmless for rungs 1-2 (neither reads it) and would silently neuter every
    step-5 arm here.

    Returns the rewritten query alongside the hits so the per-question record
    can show what was actually retrieved on -- a rewrite nobody can read is a
    rewrite nobody can debug (T28's own criterion, applied to the eval as
    well as to the service).
    """
    fuser = RRFFuser()

    def retrieve_one(query: str) -> list[Hit]:
        leg_results = [
            dense.search(query, CANDIDATE_K),
            bm25.search(query, CANDIDATE_K),
            literal.search(query, CANDIDATE_K),
        ]
        return fuser.fuse(leg_results, CANDIDATE_K)

    def search(query: str, history) -> tuple[list[Hit], str]:
        queries = reformulator.reform(query, history)
        used = queries[0] if queries else query
        if len(queries) == 1:
            hits = retrieve_one(used)
        else:
            hits = fuser.fuse([retrieve_one(q) for q in queries], CANDIDATE_K)
        hits = [replace(h, chunk=chunk_lookup.get(h.chunk_id)) if h.chunk is None else h for h in hits]
        return hits, used

    return search


def evaluate(
    search, question: GoldQuestion, gold_lookup: dict[str, Chunk], retrieved_lookup: dict[str, Chunk]
) -> dict[str, Any]:
    hits, used_query = search(question.question, list(question.history))
    retrieved = [h.chunk_id for h in hits]
    canon = canonicalize_retrieved(retrieved, retrieved_lookup, question.gold, gold_lookup)
    return {
        "query_id": question.qid,
        "split": question.split,
        "question": question.question,
        "history": list(question.history),
        "query_used": used_query,
        "rewritten": used_query != question.question,
        "gold": list(question.gold),
        "recall@k": recall_at_k(question.gold, canon, K),
        "mrr": mrr(question.gold, canon, K),
        "ndcg@k": ndcg_at_k(question.gold, canon, K),
        "all_golds_retrieved@k": all_golds_retrieved_at_k(question.gold, canon, K),
    }


def run_arm(search, questions: list[GoldQuestion], gold_lookup, chunk_lookup) -> list[dict[str, Any]]:
    return [evaluate(search, q, gold_lookup, chunk_lookup) for q in questions]


def summarize(records: list[dict[str, Any]], splits: tuple[str, ...] | None = None) -> dict[str, Any]:
    rows = [r for r in records if splits is None or r["split"] in splits]
    out: dict[str, Any] = {"n": len(rows)}
    for metric in ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k"):
        values = [float(r[metric]) for r in rows]
        out[metric] = bootstrap_ci(values, statistics.mean, seed=42, name="mean").to_dict()
    return out


def compare(label: str, a_records: list[dict], b_records: list[dict], splits: tuple[str, ...]) -> dict[str, Any]:
    """`b - a`, paired by query_id, on `all_golds_retrieved@5`.

    Reports the per-question win/loss counts the pre-registered bar is stated
    in, *and* the bootstrap CI as context. decisions/0015 fixed the bar as
    counts precisely because the CI cannot carry a decision at n=9.
    """
    a_map = {r["query_id"]: r for r in a_records if r["split"] in splits}
    b_map = {r["query_id"]: r for r in b_records if r["split"] in splits}
    qids = sorted(set(a_map) & set(b_map))
    a = [float(a_map[q]["all_golds_retrieved@k"]) for q in qids]
    b = [float(b_map[q]["all_golds_retrieved@k"]) for q in qids]
    improved = [q for q, x, y in zip(qids, a, b) if y > x]
    regressed = [q for q, x, y in zip(qids, a, b) if y < x]
    result = paired_bootstrap_comparison(
        a, b, split="+".join(splits), metric=f"{label}:all_golds_retrieved@{K}"
    )
    return {
        "label": label,
        "n_paired": len(qids),
        "improved": improved,
        "regressed": regressed,
        "b_minus_a": result.interval.to_dict(),
        # The pre-registered bar, evaluated mechanically rather than by eye.
        "clears_bar": len(improved) >= MIN_IMPROVED and not regressed,
    }


def print_table(records: list[dict[str, Any]], title: str) -> None:
    print(f"\n  {title}")
    print(f"  {'qid':<7} {'split':<6} {'hit@5':<6} {'rank':<5} query used")
    for r in sorted(records, key=lambda r: r["query_id"]):
        hit = "yes" if float(r["all_golds_retrieved@k"]) > 0 else "NO"
        rank = f"{1 / r['mrr']:.0f}" if r["mrr"] else "-"
        used = r["query_used"]
        if len(used) > 78:
            used = used[:75] + "..."
        print(f"  {r['query_id']:<7} {r['split']:<6} {hit:<6} {rank:<5} {used}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metered",
        action="store_true",
        help="also run arm 2 (LlmDecontextualizer) and its noise-floor rerun -- spends generation quota",
    )
    args = parser.parse_args()

    if not CHUNKS_PATH.exists() or not INDEX_DIR.exists():
        print(f"missing {CHUNKS_PATH} / {INDEX_DIR} -- build the frozen-config corpus/index first")
        return 1

    all_questions = load_gold_questions(GOLD_PATH)
    questions = [
        q for q in all_questions if q.slice == SLICE and q.split in PRIMARY_SPLITS
    ]
    questions.sort(key=lambda q: q.qid)
    split_lock = load_split_lock(SPLIT_LOCK_PATH)

    # Guard rails, asserted rather than trusted: the pre-registered pool must
    # be what decisions/0015 says it is, and test must not leak in.
    assert all(q.split != "test" for q in questions), "test split must not appear in this eval"
    assert all(q.history for q in questions), "a multi_turn question with no history is a no-op here"
    assert all(len(q.gold) == 1 for q in questions), "decisions/0015 assumes exactly 1 gold ref per question"

    print(f"pool: {SLICE} {'+'.join(PRIMARY_SPLITS)}, n={len(questions)} (split_hash {split_lock['split_hash'][:8]})")
    print(f"excluded: {SLICE} test, n={sum(1 for q in all_questions if q.slice == SLICE and q.split == 'test')}")

    chunks = load_chunks(CHUNKS_PATH)
    chunk_lookup = {c.chunk_id: c for c in chunks}
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
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

    arms: list[tuple[str, Reformulator]] = [
        ("arm0_identity", IdentityReformulator()),
        ("arm1_history_concat", HistoryConcatenationReformulator()),
    ]
    decontextualizer: LlmDecontextualizer | None = None
    if args.metered:
        generator = OllamaCloudGenerator(model=MODEL, temperature=0.0, max_tokens=128)
        decontextualizer = LlmDecontextualizer(generator)
        arms.append(("arm2_llm_decontext", decontextualizer))
    else:
        print("\n(arm 2 skipped -- pass --metered to spend quota on it)")

    results: dict[str, list[dict[str, Any]]] = {}
    for name, reformulator in arms:
        search = build_search(dense, bm25, literal, chunk_lookup, reformulator)
        print(f"\nrunning {name} ...", end=" ", flush=True)
        records = run_arm(search, questions, gold_lookup, chunk_lookup)
        results[name] = records
        headline = statistics.mean(float(r["all_golds_retrieved@k"]) for r in records)
        print(f"all_golds_retrieved@{K} = {headline:.3f}")
        print_table(records, f"{name} per question")
        if reformulator is decontextualizer and decontextualizer is not None:
            fell_back = [r["query_id"] for r in records if not r["rewritten"]]
            print(f"  calls={decontextualizer.calls} fell_back_to_raw={fell_back or 'none'}")

    # Noise floor for the metered arm (decisions/0015; same method as
    # decisions/0010): one identical rerun, reported beside the effect.
    noise: dict[str, Any] | None = None
    if decontextualizer is not None:
        rerun_gen = OllamaCloudGenerator(model=MODEL, temperature=0.0, max_tokens=128)
        rerun = LlmDecontextualizer(rerun_gen)
        search = build_search(dense, bm25, literal, chunk_lookup, rerun)
        print("\nrunning arm2 noise-floor rerun ...", end=" ", flush=True)
        rerun_records = run_arm(search, questions, gold_lookup, chunk_lookup)
        results["arm2_rerun"] = rerun_records
        headline = statistics.mean(float(r["all_golds_retrieved@k"]) for r in rerun_records)
        print(f"all_golds_retrieved@{K} = {headline:.3f}")
        noise = compare("arm2_noise_floor", results["arm2_llm_decontext"], rerun_records, PRIMARY_SPLITS)
        identical = [
            r["query_id"]
            for r, s in zip(
                sorted(results["arm2_llm_decontext"], key=lambda r: r["query_id"]),
                sorted(rerun_records, key=lambda r: r["query_id"]),
            )
            if r["query_used"] != s["query_used"]
        ]
        noise["rewrites_that_differed_between_runs"] = identical
        print(
            f"  noise floor (rerun - run): {noise['b_minus_a']['value']:+.4f} "
            f"[{noise['b_minus_a']['ci_low']:+.4f}, {noise['b_minus_a']['ci_high']:+.4f}]; "
            f"rewrites differing between runs: {identical or 'none'}"
        )

    print("\n--- summaries -------------------------------------------------")
    summaries: dict[str, Any] = {}
    for name, records in results.items():
        summaries[name] = {
            "primary_dev_train": summarize(records, PRIMARY_SPLITS),
            "secondary_dev_only": summarize(records, SECONDARY_SPLITS),
        }
        p = summaries[name]["primary_dev_train"]["all_golds_retrieved@k"]
        s = summaries[name]["secondary_dev_only"]["all_golds_retrieved@k"]
        print(f"{name:<22} primary n=9 {p['value']:.3f}   secondary n=3 {s['value']:.3f}")

    print("\n--- comparisons vs arm 0 (control) ---------------------------")
    comparisons = []
    for name in results:
        if name in ("arm0_identity", "arm2_rerun"):
            continue
        cmp = compare(name, results["arm0_identity"], results[name], PRIMARY_SPLITS)
        cmp["secondary_dev_only"] = compare(
            name, results["arm0_identity"], results[name], SECONDARY_SPLITS
        )
        comparisons.append(cmp)
        print(
            f"{name:<22} {cmp['b_minus_a']['value']:+.4f} "
            f"[{cmp['b_minus_a']['ci_low']:+.4f}, {cmp['b_minus_a']['ci_high']:+.4f}]  "
            f"improved={len(cmp['improved'])} regressed={len(cmp['regressed'])}  "
            f"-> {'CLEARS BAR' if cmp['clears_bar'] else 'fails bar'}"
        )
    if "arm2_llm_decontext" in results:
        head_to_head = compare(
            "arm2_vs_arm1", results["arm1_history_concat"], results["arm2_llm_decontext"], PRIMARY_SPLITS
        )
        comparisons.append(head_to_head)
        print(
            f"{'arm2 vs arm1':<22} {head_to_head['b_minus_a']['value']:+.4f} "
            f"[{head_to_head['b_minus_a']['ci_low']:+.4f}, {head_to_head['b_minus_a']['ci_high']:+.4f}]  "
            f"improved={len(head_to_head['improved'])} regressed={len(head_to_head['regressed'])}"
        )

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(
        json.dumps(
            {
                "headline_k": K,
                "slice": SLICE,
                "primary_splits": list(PRIMARY_SPLITS),
                "secondary_splits": list(SECONDARY_SPLITS),
                "split_hash": split_lock["split_hash"],
                "metered": args.metered,
                "model": MODEL if args.metered else None,
                "min_improved_bar": MIN_IMPROVED,
                "summaries": summaries,
                "comparisons": comparisons,
                "noise_floor": noise,
                "records": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
