"""Task 22: metered ablations #8 (citation-forced prompt), #9 (Task 21's
abstention gate), #10 (generation model comparison) -- decisions/0010.

One interleaved sweep, six arms, all on the frozen retrieval config
(decisions/0007), all on the 60-question **dev** split (decisions/0006
addendum 3 -- test is Task 22b's job, after Checkpoint E, not this task's):

    free_form_20b_a           -- gpt-oss:20b, free-form prompt (shared reference)
    free_form_20b_b           -- identical config, a second live pass (this
                                  session's noise floor; never cached)
    citation_forced_20b       -- gpt-oss:20b, [N]-marker-forced prompt (#8)
    free_form_120b            -- gpt-oss:120b, free-form (#10)
    free_form_gemma4_31b      -- gemma4:31b, free-form (#10)
    free_form_nemotron3_nano_30b -- nemotron-3-nano:30b, free-form (#10)

#9 needs no new arm: PLAN Sec 4a #3 says reuse the free-form answers at
every threshold, so it is derived from `free_form_20b_a` plus Task 21's
already-stored per-question cross-encoder scores. Every comparison here is
dev-split selection, not inference -- effect size + CI, never a p-value
(`decisions/0006`) -- and reports the noise floor (`free_form_20b_b` vs
`_a`) beside it.

    python scripts/run_t22_metered_ablations.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

import requests

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_phase3c_baseline import (  # noqa: E402
    CANDIDATE_K,
    CHUNKS_PATH,
    GOLD_CHUNKS_PATH,
    GOLD_PATH,
    INDEX_DIR,
    K,
    SPLIT_LOCK_PATH,
    answered_faithfulness,
    build_search,
    load_chunks,
    tier1_fields,
)
from run_tau_calibration import features_for  # noqa: E402

from mcrag.config import Config  # noqa: E402
from mcrag.eval.abstention import ratio_ci  # noqa: E402
from mcrag.eval.ablation_runner import run_interleaved, unquarantined  # noqa: E402
from mcrag.eval.chunk_alignment import canonicalize_retrieved  # noqa: E402
from mcrag.eval.gold import load_gold_questions, load_split_lock  # noqa: E402
from mcrag.eval.nli_faithfulness import NLIFaithfulnessScorer  # noqa: E402
from mcrag.eval.retrieval_metrics import all_golds_retrieved_at_k, mrr, ndcg_at_k, recall_at_k  # noqa: E402
from mcrag.eval.significance import paired_bootstrap_comparison  # noqa: E402
from mcrag.eval.stats import bootstrap_ci  # noqa: E402
from mcrag.eval.tier0_scoring import score_citation_markers, score_tier0  # noqa: E402
from mcrag.generate.ollama_cloud import ContextOverflow, GenerationError, OllamaCloudGenerator  # noqa: E402
from mcrag.generate.prompting import CITATION_FORCED_SYSTEM_PROMPT, SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.runlog import Lock, RunDir  # noqa: E402
from mcrag.types import GoldQuestion  # noqa: E402

# decisions/0010: every arm's model, verified against Ollama Cloud's live
# /v1/models on 2026-09-17. This doubles as run_interleaved's per-arm
# expected_model dict for drift quarantine.
MODELS: dict[str, str] = {
    "free_form_20b_a": "gpt-oss:20b",
    "free_form_20b_b": "gpt-oss:20b",
    "citation_forced_20b": "gpt-oss:20b",
    "free_form_120b": "gpt-oss:120b",
    "free_form_gemma4_31b": "gemma4:31b",
    "free_form_nemotron3_nano_30b": "nemotron-3-nano:30b",
}
CITATION_FORCED_ARMS = {"citation_forced_20b"}
NOISE_FLOOR_PAIR = ("free_form_20b_a", "free_form_20b_b")
MODEL_COMPARISON_ARMS = ("free_form_120b", "free_form_gemma4_31b", "free_form_nemotron3_nano_30b")
REFERENCE_ARM = "free_form_20b_a"
GATE_TAU = 4.96  # decisions/0009, floor lowered to 80% post hoc
T21_RUN = Path("runs/20260917T133042Z_340a8f03a310")
SLICES = ("single_silo", "cross_silo", "out_of_scope", "adversarial", "exact_match", "temporal", "multi_turn")


def build_configs() -> list[Config]:
    configs = []
    for arm, model in MODELS.items():
        configs.append(
            Config.from_dict(
                {
                    "name": "t22-metered-ablations",
                    "arm": arm,
                    "chunk": {"max_tokens": 512},
                    "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
                    "generation": {"model": model, "temperature": 0.0},
                    "eval": {"gold_path": str(GOLD_PATH), "split": "dev"},
                    "notes": (
                        f"Task 22 arm {arm}: {model}, "
                        f"{'citation-forced' if arm in CITATION_FORCED_ARMS else 'free-form'} prompt, "
                        "frozen retrieval (decisions/0007), full dev split. decisions/0010."
                    ),
                }
            )
        )
    return configs


def evaluate_fn_for(search, gold_lookup, retrieved_lookup, faithfulness):
    def build(config: Config):
        model = config.generation.model
        arm = config.arm
        system_prompt = CITATION_FORCED_SYSTEM_PROMPT if arm in CITATION_FORCED_ARMS else SYSTEM_PROMPT
        # 180s default (calibrated against gpt-oss:20b, docs/quota-calibration.md)
        # is too tight for the other three models in #10 -- one already timed
        # out mid-sweep. quota_errors below still catches a genuine hang.
        generator = OllamaCloudGenerator(model=model, temperature=0.0, timeout_s=300.0)

        def evaluate(question: GoldQuestion) -> dict[str, Any]:
            hits = search(question.question)[:K]
            found = [h for h in hits if h.chunk is not None]
            retrieved_urls = {h.chunk.source_url for h in found}
            gold_urls = {gold_lookup[g].source_url for g in question.gold if g in gold_lookup}

            record: dict[str, Any] = {
                "query_id": question.qid,
                "slice": question.slice,
                "conjunctive": question.conjunctive,
                "question": question.question,
                "expects_answer": bool(question.gold),
                "retrieved": [
                    {"chunk_id": h.chunk_id, "url": h.chunk.source_url, "title": h.chunk.title}
                    for h in found
                ],
            }
            if question.gold:
                canon = canonicalize_retrieved(
                    [h.chunk_id for h in hits], retrieved_lookup, question.gold, gold_lookup
                )
                record["retrieval"] = {
                    "recall@k": recall_at_k(question.gold, canon, K),
                    "mrr": mrr(question.gold, canon, K),
                    "ndcg@k": ndcg_at_k(question.gold, canon, K),
                    "all_golds_retrieved@k": all_golds_retrieved_at_k(question.gold, canon, K),
                }

            prompt = build_user_prompt(question.question, [h.chunk for h in found], passage_chars=None)
            completion = generator.complete(prompt, system=system_prompt)
            reasoning_chars = len(completion.reasoning)
            answer_chars = len(completion.text)
            record.update(
                {
                    "model": completion.model,
                    "answer": completion.text,
                    "finish_reason": completion.finish_reason,
                    "prompt_tokens_server": completion.usage.prompt_tokens,
                    "completion_tokens": completion.usage.completion_tokens,
                    "reasoning_chars": reasoning_chars,
                    "answer_chars": answer_chars,
                    "reasoning_char_share": (
                        reasoning_chars / (reasoning_chars + answer_chars)
                        if (reasoning_chars + answer_chars) else None
                    ),
                    "wall_s": completion.usage.wall_s,
                }
            )

            tier0 = score_tier0(
                completion.text, question.question, retrieved_urls, gold_urls,
                expects_answer=bool(question.gold),
            )
            record["tier0"] = {
                "citation_accuracy": tier0.citation_accuracy,
                "citation_validity": tier0.citation_validity,
                "refused": tier0.refused,
                "refusal_correct": tier0.refusal_correct,
                "exact_match_presence": tier0.exact_match_presence,
            }
            record.update(tier1_fields(faithfulness, completion.text, [h.chunk.text for h in found]))

            if arm in CITATION_FORCED_ARMS:
                marker = score_citation_markers(completion.text, n_passages=len(found))
                record["citation_marker"] = {
                    "compliance": marker.compliance,
                    "n_sentences": marker.n_sentences,
                    "n_marked": marker.n_marked,
                    "n_invalid_markers": marker.n_invalid_markers,
                }
            return record

        return evaluate

    return build


def _mean_ci(values: list[float]) -> dict[str, Any]:
    return bootstrap_ci(values, statistics.mean, seed=42, name="mean").to_dict()


def _interval(iv) -> dict[str, Any] | None:
    return None if iv is None else iv.to_dict()


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = unquarantined(records)
    n_quarantined = len(records) - len(scored)
    summary: dict[str, Any] = {
        "run": {"n_total": str(len(records)), "n_quarantined": str(n_quarantined)}
    }
    summary["refusal_rate"] = _mean_ci([1.0 if r["tier0"]["refused"] else 0.0 for r in scored])
    summary["refusal_correct"] = _mean_ci([1.0 if r["tier0"]["refusal_correct"] else 0.0 for r in scored])

    for field in ("citation_accuracy", "citation_validity", "exact_match_presence"):
        values = [r["tier0"][field] for r in scored if r["tier0"][field] is not None]
        if values:
            summary[field] = _mean_ci(values)

    faith = [f for f in map(answered_faithfulness, scored) if f is not None]
    if faith:
        summary["faithfulness"] = _mean_ci(faith)

    marker = [
        r["citation_marker"]["compliance"] for r in scored
        if "citation_marker" in r and r["citation_marker"]["compliance"] is not None
    ]
    if marker:
        summary["citation_marker_compliance"] = _mean_ci(marker)

    answerable = [r for r in scored if r["expects_answer"]]
    for metric in ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k"):
        values = [r["retrieval"][metric] for r in answerable if "retrieval" in r]
        if values:
            summary[metric] = _mean_ci(values)

    for field in ("wall_s", "completion_tokens", "reasoning_char_share"):
        values = [r[field] for r in scored if r.get(field) is not None]
        if values:
            summary[field] = _mean_ci(values)

    return summary


# ---- cross-arm comparisons: #8, #10, and the noise floor -------------------


def compare_arms(a_records: list[dict], b_records: list[dict], label: str, slice_filter: str | None = None) -> dict[str, Any]:
    """`b - a`, paired by query_id. Every comparison decisions/0010 wants,
    computed the same way whether `a`/`b` are the noise-floor pair, #8's
    prompt pair, or one of #10's model pairs."""
    a = {r["query_id"]: r for r in unquarantined(a_records)}
    b = {r["query_id"]: r for r in unquarantined(b_records)}
    qids = sorted(set(a) & set(b))
    if slice_filter is not None:
        qids = [q for q in qids if a[q]["slice"] == slice_filter]

    def paired(value_fn, metric: str) -> dict[str, Any] | None:
        both = [q for q in qids if value_fn(a[q]) is not None and value_fn(b[q]) is not None]
        if not both:
            return None
        result = paired_bootstrap_comparison(
            [float(value_fn(a[q])) for q in both], [float(value_fn(b[q])) for q in both],
            split="dev", metric=metric,
        )
        return result.interval.to_dict()

    def agree(field_fn) -> dict[str, Any] | None:
        if not qids:
            return None
        return _mean_ci([1.0 if field_fn(a[q]) == field_fn(b[q]) else 0.0 for q in qids])

    return {
        "label": label,
        "slice": slice_filter or "pooled",
        "n_questions": len(qids),
        "exact_text_match": agree(lambda r: r.get("answer")),
        "b_minus_a": {
            "refusal_correct": paired(lambda r: 1.0 if r["tier0"]["refusal_correct"] else 0.0, f"{label}:refusal_correct"),
            "faithfulness": paired(answered_faithfulness, f"{label}:faithfulness"),
            "citation_accuracy": paired(lambda r: r["tier0"]["citation_accuracy"], f"{label}:citation_accuracy"),
            "citation_validity": paired(lambda r: r["tier0"]["citation_validity"], f"{label}:citation_validity"),
            "wall_s": paired(lambda r: r.get("wall_s"), f"{label}:wall_s"),
            "completion_tokens": paired(lambda r: r.get("completion_tokens"), f"{label}:completion_tokens"),
            "reasoning_char_share": paired(lambda r: r.get("reasoning_char_share"), f"{label}:reasoning_char_share"),
        },
        "agreement": {"refused": agree(lambda r: r["tier0"]["refused"])},
    }


def compare_citation_markers(citation_records: list[dict], free_form_records: list[dict]) -> dict[str, Any]:
    cf = [r for r in unquarantined(citation_records) if r.get("citation_marker", {}).get("compliance") is not None]
    ff_vals = [
        r["citation_marker"]["compliance"] for r in unquarantined(free_form_records)
        if "citation_marker" in r and r["citation_marker"]["compliance"] is not None
    ]
    return {
        "citation_forced_compliance": _mean_ci([r["citation_marker"]["compliance"] for r in cf]),
        "citation_forced_n_invalid_markers": sum(r["citation_marker"]["n_invalid_markers"] for r in cf),
        "free_form_compliance": _mean_ci(ff_vals) if ff_vals else None,
    }


# ---- #9: derived, zero quota -------------------------------------------------


def derive_gate_vs_always_answer(free_form_records: list[dict], tau: float = GATE_TAU) -> dict[str, Any]:
    t21_dev = {r["query_id"]: r for r in RunDir.open(T21_RUN).records() if r["split"] == "dev"}
    always = {r["query_id"]: r for r in unquarantined(free_form_records)}
    qids = sorted(set(always) & set(t21_dev))
    missing = set(always) - set(t21_dev)
    if missing:
        raise ValueError(f"dev questions missing from Task 21's stored scores: {sorted(missing)}")

    labels = [bool(t21_dev[q]["should_answer"]) for q in qids]
    gate_answers = [features_for(t21_dev[q], "ce")["raw"] >= tau for q in qids]
    always_answers = [True] * len(qids)

    def policy_metrics(answered_flags: list[bool]) -> dict[str, Any]:
        coverage = bootstrap_ci([1.0 if a else 0.0 for a in answered_flags], statistics.mean, name="mean", seed=42)
        return {
            "coverage": coverage.to_dict(),
            "precision": _interval(ratio_ci(labels, answered_flags)),
            "false_refusal_rate": _interval(ratio_ci([not a for a in answered_flags], labels)),
        }

    always_refusal_correct = [1.0 if always[q]["tier0"]["refusal_correct"] else 0.0 for q in qids]
    always_faith = [f for f in map(lambda q: answered_faithfulness(always[q]), qids) if f is not None]

    gate_refusal_correct: list[float] = []
    gate_faith: list[float] = []
    for q, answered in zip(qids, gate_answers):
        if answered:
            gate_refusal_correct.append(1.0 if always[q]["tier0"]["refusal_correct"] else 0.0)
            f = answered_faithfulness(always[q])
            if f is not None:
                gate_faith.append(f)
        else:
            gate_refusal_correct.append(1.0 if not always[q]["expects_answer"] else 0.0)

    def diff(gate_vals: list[float], always_vals: list[float], metric: str) -> dict[str, Any]:
        # paired_bootstrap_comparison(a, b) computes b - a; a=always, b=gate
        # here so the result really is "gate minus always_answer", matching
        # the label -- passing them the other way around (an earlier bug in
        # this function) silently computed always_answer minus gate instead.
        n = min(len(gate_vals), len(always_vals))
        result = paired_bootstrap_comparison(always_vals[:n], gate_vals[:n], split="dev", metric=metric)
        return result.interval.to_dict()

    return {
        "tau": tau,
        "n_dev": len(qids),
        "always_answer": {**policy_metrics(always_answers), "refusal_correct": _mean_ci(always_refusal_correct),
                           "faithfulness": _mean_ci(always_faith) if always_faith else None},
        "gate": {**policy_metrics(gate_answers), "refusal_correct": _mean_ci(gate_refusal_correct),
                 "faithfulness": _mean_ci(gate_faith) if gate_faith else None},
        "gate_minus_always_answer": {
            "refusal_correct": diff(gate_refusal_correct, always_refusal_correct, "gate_vs_always:refusal_correct"),
        },
    }


# ---- main ---------------------------------------------------------------------------


def main() -> int:
    dev_questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "dev"]
    chunks = load_chunks(CHUNKS_PATH)
    chunk_lookup = {c.chunk_id: c for c in chunks}
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
    print(f"{len(dev_questions)} dev questions, 6 arms interleaved -> {len(dev_questions) * 6} generation calls max")

    embedder = BgeEmbedder()
    dense = DenseIndex(
        db_path=INDEX_DIR, embedder=embedder,
        cache=EmbeddingCache(INDEX_DIR.parent / f"{INDEX_DIR.name}_cache.jsonl"), model_name=MODEL_NAME,
    )
    bm25 = BM25Index()
    bm25.build(chunks)
    literal = LiteralIndex()
    literal.build(chunks)
    search = build_search(dense, bm25, literal, chunk_lookup)
    faithfulness = NLIFaithfulnessScorer()

    configs = build_configs()
    results = run_interleaved(
        configs, dev_questions, evaluate_fn_for(search, gold_lookup, chunk_lookup, faithfulness),
        summarize, expected_model=MODELS, root="runs",
        # RequestException (a read timeout, a dropped connection) is a
        # metered-backend hiccup, not a bug -- pause and resume, don't crash.
        quota_errors=(GenerationError, ContextOverflow, requests.exceptions.RequestException),
    )

    split_lock = load_split_lock(SPLIT_LOCK_PATH)
    for arm, run_dir in results.items():
        run_dir.write_lock(Lock(kind="corpus", digest="bp_off+fixed512", detail={"chunks_path": str(CHUNKS_PATH)}))
        run_dir.write_lock(Lock(kind="model", digest=f"{MODELS[arm]}", detail={"generator": MODELS[arm], "arm": arm}))
        run_dir.write_lock(Lock(kind="split", digest=split_lock["split_hash"], detail={"split": "dev"}))

    records = {arm: list(run_dir.records()) for arm, run_dir in results.items()}
    ref = records[REFERENCE_ARM]

    analysis: dict[str, Any] = {"reference_arm": REFERENCE_ARM, "n_dev": len(dev_questions)}
    analysis["noise_floor"] = compare_arms(ref, records[NOISE_FLOOR_PAIR[1]], "noise_floor")
    analysis["ablation_8_citation_forced"] = compare_arms(ref, records["citation_forced_20b"], "ablation_8")
    analysis["ablation_8_citation_forced"]["marker_compliance"] = compare_citation_markers(
        records["citation_forced_20b"], ref
    )
    analysis["ablation_10_model_comparison"] = {
        arm: {
            "pooled": compare_arms(ref, records[arm], f"ablation_10:{arm}"),
            "by_slice": {s: compare_arms(ref, records[arm], f"ablation_10:{arm}:{s}", slice_filter=s) for s in SLICES},
        }
        for arm in MODEL_COMPARISON_ARMS
    }
    analysis["ablation_9_gate_vs_always_answer"] = derive_gate_vs_always_answer(ref)

    out_path = Path("runs/t22_metered_ablations_analysis.json")
    out_path.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")

    def fmt(iv):
        if iv is None:
            return "--"
        return f"{iv['value']:+.3f} [{iv['ci_low']:+.3f}, {iv['ci_high']:+.3f}] (n={iv['n']})"

    print(f"\nrun dirs: {[str(rd.path) for rd in results.values()]}")
    nf = analysis["noise_floor"]["b_minus_a"]
    print(f"\n== noise floor (free_form_20b_b - free_form_20b_a) ==")
    for k, v in nf.items():
        print(f"  {k:<20} {fmt(v)}")

    a8 = analysis["ablation_8_citation_forced"]
    print(f"\n== #8 citation-forced - free-form ==")
    for k, v in a8["b_minus_a"].items():
        print(f"  {k:<20} {fmt(v)}")
    print(f"  marker compliance: forced={fmt(a8['marker_compliance']['citation_forced_compliance'])} free-form={fmt(a8['marker_compliance']['free_form_compliance'])}")

    print(f"\n== #10 model comparison (pooled) ==")
    for arm, data in analysis["ablation_10_model_comparison"].items():
        print(f"  -- {arm} --")
        for k, v in data["pooled"]["b_minus_a"].items():
            print(f"    {k:<20} {fmt(v)}")

    g9 = analysis["ablation_9_gate_vs_always_answer"]
    print(f"\n== #9 gate (tau={g9['tau']}) vs always-answer (n={g9['n_dev']}) ==")
    for policy in ("always_answer", "gate"):
        p = g9[policy]
        print(f"  {policy:<14} coverage {fmt(p['coverage'])}  precision {fmt(p['precision'])}  refusal_correct {fmt(p['refusal_correct'])}")
    print(f"  gate - always_answer refusal_correct: {fmt(g9['gate_minus_always_answer']['refusal_correct'])}")

    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
