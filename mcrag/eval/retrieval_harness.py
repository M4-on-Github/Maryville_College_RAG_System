"""Task 14: the free retrieval eval loop -- config/index/gold in, metrics.json out.

No LLM call anywhere in this module. `evaluate_question` is one retriever
search plus pure arithmetic; `run` is a loop over the gold set with the T1
run-directory conventions (resumable `per_query.jsonl`, locked provenance).

A question with no gold refs (`out_of_scope`) has nothing to score retrieval
against -- it is skipped here, not scored as a failure. Whether the pipeline
correctly abstains on it is a generation-level question (Phase 3b/4), not a
retrieval-metric one.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mcrag.eval.chunk_alignment import canonicalize_retrieved
from mcrag.eval.retrieval_metrics import all_golds_retrieved_at_k, mrr, ndcg_at_k, recall_at_k
from mcrag.eval.stats import Interval, bootstrap_ci
from mcrag.interfaces import Retriever
from mcrag.runlog import RunDir
from mcrag.types import Chunk, GoldQuestion

METRIC_NAMES = ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k")


def evaluate_question(
    retriever: Retriever,
    question: GoldQuestion,
    k: int,
    *,
    retrieved_lookup: dict[str, Chunk] | None = None,
    gold_lookup: dict[str, Chunk] | None = None,
    stale_qids: set[str] | None = None,
) -> dict[str, Any]:
    """One question's retrieval metrics, or a skip record if it has no gold.

    `retrieved_lookup`/`gold_lookup` are optional: pass both when the
    retriever's index was NOT built from the same chunk set the gold refs are
    ids into (e.g. Task 15's fixed-512-token baseline vs the production
    `ParagraphChunker` chunks) so a retrieved id that covers the same passage
    as a gold chunk -- just under a different id -- is still counted as a
    hit (`mcrag.eval.chunk_alignment`). Omit both to score a retriever
    against its own native chunking with plain exact-id matching.

    `stale_qids` is an optional set of question IDs to exclude from evaluation.
    If a question's ID is in this set, it is skipped with reason "stale".
    """
    stale_qids = stale_qids or set()
    if question.qid in stale_qids:
        return {
            "query_id": question.qid,
            "slice": question.slice,
            "conjunctive": question.conjunctive,
            "skipped": "stale",
        }
    if not question.gold:
        return {
            "query_id": question.qid,
            "slice": question.slice,
            "conjunctive": question.conjunctive,
            "skipped": "no_gold_refs",
        }

    hits = retriever.search(question.question, k)
    retrieved = [h.chunk_id for h in hits]
    if retrieved_lookup is not None and gold_lookup is not None:
        retrieved = canonicalize_retrieved(retrieved, retrieved_lookup, question.gold, gold_lookup)

    return {
        "query_id": question.qid,
        "slice": question.slice,
        "conjunctive": question.conjunctive,
        "retrieved": retrieved,
        "gold": list(question.gold),
        "recall@k": recall_at_k(question.gold, retrieved, k),
        "mrr": mrr(question.gold, retrieved, k),
        "ndcg@k": ndcg_at_k(question.gold, retrieved, k),
        "all_golds_retrieved@k": all_golds_retrieved_at_k(question.gold, retrieved, k),
    }


def _aggregate(records: list[dict[str, Any]], metric: str, seed: int) -> Interval:
    values = [r[metric] for r in records if metric in r]
    return bootstrap_ci(values, statistic=statistics.mean, name="mean", seed=seed)


def summarize(
    records: list[dict[str, Any]], seed: int = 42, *, stale_checked: bool = False
) -> dict[str, Any]:
    """Overall and per-slice metrics, each as a `{value,ci_low,ci_high,n}` Interval.

    Every leaf here is an `Interval.to_dict()` -- `RunDir.write_metrics` rejects
    a bare number anywhere (PLAN 4f), and a dict that merely *contains* the
    reserved `n`/`value`/... key names without being a full Interval trips the
    same guard, so plain counts are stringified under `run` rather than left
    as numbers (the same convention `scripts/calibrate_quota.py` uses).

    Conjunctive questions get their own `all_golds_retrieved@k` breakout too --
    that is the metric decision 0002/PLAN Phase 3b singles out for them, and
    burying it inside the overall average would hide exactly the number the
    project's central claim depends on. Its own `n` (inside the Interval) is
    the conjunctive count -- no separate bare count needed.

    Task 35: stale questions are reported as a separate count under
    `run.n_stale`, so that a shrinking denominator is never silently conflated
    with improved retrieval performance. `stale_checked` says whether anyone
    actually looked: when it is false, `n_stale` reads `unchecked` rather than
    `0`, because a run nobody checked for decay is not a run with no decay --
    the same reason a latency stage that did not run reports null and never
    0.0 (`docs/stream_contract.md`).
    """
    scored = [r for r in records if "skipped" not in r]
    stale = [r for r in records if r.get("skipped") == "stale"]
    all_skipped = [r for r in records if "skipped" in r]
    summary: dict[str, Any] = {
        "run": {
            "n_scored": str(len(scored)),
            "n_stale": str(len(stale)) if stale_checked else "unchecked",
            "n_skipped": str(len(all_skipped)),  # Total skipped (backward compat)
        }
    }
    for metric in METRIC_NAMES:
        summary[metric] = _aggregate(scored, metric, seed).to_dict()

    by_slice: dict[str, list[dict[str, Any]]] = {}
    for r in scored:
        by_slice.setdefault(r["slice"], []).append(r)
    slices: dict[str, Any] = {}
    for slice_name, group in sorted(by_slice.items()):
        slices[slice_name] = {m: _aggregate(group, m, seed).to_dict() for m in METRIC_NAMES}
    summary["by_slice"] = slices

    conjunctive = [r for r in scored if r["conjunctive"]]
    if conjunctive:
        summary["conjunctive_all_golds_retrieved@k"] = _aggregate(
            conjunctive, "all_golds_retrieved@k", seed
        ).to_dict()

    return summary


def run(
    retriever: Retriever,
    questions: Iterable[GoldQuestion],
    k: int,
    run_dir: RunDir,
    seed: int = 42,
    *,
    retrieved_lookup: dict[str, Chunk] | None = None,
    gold_lookup: dict[str, Chunk] | None = None,
    stale_qids: set[str] | None,
) -> dict[str, Any]:
    """Score every question, resuming from `run_dir` if it already has records.

    See `evaluate_question` for `retrieved_lookup`/`gold_lookup`.

    `stale_qids` is required rather than defaulted (Task 35): the whole point
    of pinning is that no eval gets scored without someone facing the decay
    number, and a default would let every existing caller keep not facing it.
    Pass the set from `gold.find_stale_questions` to exclude those questions,
    an empty set to say "checked, nothing stale", or an explicit `None` to say
    "not checked" -- which is recorded as `n_stale: unchecked` in the metrics
    and `?` in RESULTS.md rather than being rounded down to zero.
    """
    done = run_dir.completed_ids()
    for question in questions:
        if question.qid in done:
            continue
        run_dir.append(
            evaluate_question(
                retriever,
                question,
                k,
                retrieved_lookup=retrieved_lookup,
                gold_lookup=gold_lookup,
                stale_qids=stale_qids or set(),
            )
        )

    records = list(run_dir.records())
    metrics = summarize(records, seed=seed, stale_checked=stale_qids is not None)
    run_dir.write_metrics(metrics)
    return metrics
