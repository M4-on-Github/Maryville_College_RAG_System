"""Task 21: τ calibration study -- the analysis pre-registered in decisions/0009.

For every train + dev question (180; test questions are filtered out at load
and never evaluated): run the frozen retrieval pipeline (decisions/0007),
label the question should-answer iff it is in scope and every gold passage is
in the top 5, and score its passages with the cross-encoder (MaxP windows,
raw logits) and with dense cosine similarity. Every raw score is stored per
question, so the analysis re-derives offline.

Then: each method's feature, 5-fold stratified cross-validation of the
maximum-coverage-at-95%-precision threshold, the pre-registered selection rule,
tradeoff curves, and a dev-only cross-tab of the gate against the model's own
refusals from the Task 20 control. Zero generation quota.

    python scripts/run_tau_calibration.py
    python scripts/run_tau_calibration.py --from-run runs/<dir> --floor 0.80 --include-raw   # post hoc
"""

from __future__ import annotations

import json
import os
import random
import statistics
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

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
    build_search,
    load_chunks,
)

from mcrag.config import Config  # noqa: E402
from mcrag.eval.ablation_runner import run_arm  # noqa: E402
from mcrag.eval.abstention import (  # noqa: E402
    FLOOR,
    choose_tau,
    cross_validate,
    margin,
    maxp_scores,
    normalized,
    null_percentile,
    raw_top,
    ratio_ci,
    select_method,
    sweep,
)
from mcrag.eval.chunk_alignment import canonicalize_retrieved  # noqa: E402
from mcrag.eval.gold import load_gold_questions, load_split_lock  # noqa: E402
from mcrag.eval.retrieval_metrics import all_golds_retrieved_at_k  # noqa: E402
from mcrag.eval.significance import paired_bootstrap_comparison  # noqa: E402
from mcrag.eval.stats import bootstrap_ci  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache, embed_with_cache  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.retrieval.reranker import DEFAULT_MODEL as CE_MODEL  # noqa: E402
from mcrag.retrieval.reranker import CrossEncoderReranker  # noqa: E402
from mcrag.runlog import Lock, RunDir  # noqa: E402
from mcrag.types import GoldQuestion  # noqa: E402

SPLITS = ("train", "dev")
N_NULL = 100
NULL_SEED = 42
WINDOW_CHARS = 1000
FOLDS = 5
CV_SEED = 42
CANDIDATES = ("normalized", "margin", "percentile")
REFERENCE = "raw"
METHODS = (REFERENCE, *CANDIDATES)
SIGNALS = ("ce", "dense")  # ce is primary; dense is an exploratory reference, never selectable
EMBED_CACHE = Path("indexes/baseline_embedding_cache_no_boilerplate.jsonl")
CONTROL_RUN = Path("runs/20260917T044122Z_c1d4b7284f0f")


# ---- per-question scores ----------------------------------------------------------


def evaluate_fn_for(search, reranker, embedder, cache, gold_lookup, retrieved_lookup, null_texts):
    null_vectors = embed_with_cache(embedder, MODEL_NAME, null_texts, cache)

    def evaluate(question: GoldQuestion) -> dict[str, Any]:
        pool = [h for h in search(question.question) if h.chunk is not None]
        if len(pool) < 2:
            raise ValueError(f"{question.qid}: {len(pool)} candidates; margin needs 2")
        texts = [h.chunk.text for h in pool]

        should_answer, agr = False, None
        if question.gold:
            canon = canonicalize_retrieved(
                [h.chunk_id for h in pool[:K]], retrieved_lookup, question.gold, gold_lookup
            )
            agr = all_golds_retrieved_at_k(question.gold, canon, K)
            should_answer = agr == 1.0

        truncated = 0

        def score_pairs(pairs):
            nonlocal truncated
            truncated += reranker.count_truncated(pairs)
            return reranker.score_pairs(pairs)

        query_vector = embedder.embed([question.question])[0]
        pool_vectors = embed_with_cache(embedder, MODEL_NAME, texts, cache)

        def dot(v):
            return float(sum(a * b for a, b in zip(query_vector, v)))

        return {
            "query_id": question.qid,
            "split": question.split,
            "slice": question.slice,
            "conjunctive": question.conjunctive,
            "expects_answer": bool(question.gold),
            "all_golds_retrieved@5": agr,
            "should_answer": should_answer,
            "pool_ids": [h.chunk_id for h in pool],
            "ce_pool": maxp_scores(score_pairs, question.question, texts, WINDOW_CHARS),
            "ce_null": maxp_scores(score_pairs, question.question, null_texts, WINDOW_CHARS),
            "ce_truncated_pairs": truncated,
            "dense_pool": [dot(v) for v in pool_vectors],
            "dense_null": [dot(v) for v in null_vectors],
        }

    return evaluate


def features_for(record: dict[str, Any], signal: str) -> dict[str, float]:
    pool = record[f"{signal}_pool"]
    top = pool[:K]
    s1 = raw_top(top)
    return {
        "raw": s1,
        "normalized": normalized(s1, pool),
        "margin": margin(top),
        "percentile": null_percentile(s1, record[f"{signal}_null"]),
    }


# ---- analysis -----------------------------------------------------------------------


def _interval(iv) -> dict[str, Any] | None:
    return None if iv is None else iv.to_dict()


def analyze(
    records: list[dict[str, Any]], floor: float = FLOOR, candidates: tuple[str, ...] = CANDIDATES
) -> dict[str, Any]:
    labels = [bool(r["should_answer"]) for r in records]
    strata = [r["slice"] for r in records]
    analysis: dict[str, Any] = {
        "floor": floor,
        "candidates": list(candidates),
        "n_questions": len(records),
        "n_should_answer": sum(labels),
        "splits": sorted({r["split"] for r in records}),
        "ce_truncated_pairs": sum(r["ce_truncated_pairs"] for r in records),
        "signals": {},
    }
    for signal in SIGNALS:
        per_method: dict[str, Any] = {}
        oof_flags: dict[str, list[bool]] = {}
        for method in METHODS:
            f = [features_for(r, signal)[method] for r in records]
            cv = cross_validate(f, labels, strata, FOLDS, CV_SEED, floor)
            oof = cv.oof_answered
            oof_flags[method] = oof
            coverage = bootstrap_ci([1.0 if a else 0.0 for a in oof], statistics.mean, name="mean", seed=42)
            precision = ratio_ci(labels, oof)
            false_refusal = ratio_ci([not a for a in oof], labels)
            final_tau = choose_tau(f, labels, floor)
            per_method[method] = {
                "oof_coverage": coverage.to_dict(),
                "oof_precision": _interval(precision),
                "oof_false_refusal_rate": _interval(false_refusal),
                "fold_taus": cv.fold_taus,
                "final_tau": final_tau,
                "curve": [asdict(p) for p in sweep(f, labels)],
            }
        rule_input = {
            m: (per_method[m]["oof_coverage"]["value"],
                None if per_method[m]["oof_precision"] is None else per_method[m]["oof_precision"]["value"])
            for m in candidates
        }
        selected = select_method(rule_input, floor)
        comparisons = {}
        for other in METHODS:
            if other == selected:
                continue
            result = paired_bootstrap_comparison(
                [1.0 if a else 0.0 for a in oof_flags[other]],
                [1.0 if a else 0.0 for a in oof_flags[selected]],
                split="train+dev", metric=f"oof_coverage[{selected}-{other}]",
            )
            comparisons[f"{selected}_minus_{other}"] = result.interval.to_dict()
        meets = [m for m in candidates if rule_input[m][1] is not None and rule_input[m][1] >= floor]
        analysis["signals"][signal] = {
            "selectable": signal == "ce",
            "methods": per_method,
            "rule_selected": selected,
            "candidates_meeting_floor_oof": meets,
            "oof_coverage_differences": comparisons,
        }
    return analysis


def model_refusal_crosstab(records: list[dict[str, Any]], analysis: dict[str, Any]) -> dict[str, Any]:
    """Dev only: the gate (selected method, final τ fitted on all 180, so in-sample)
    against the model's own refusals in the Task 20 control, and PLAN's
    any-signal-wins combination."""
    control = {r["query_id"]: r for r in RunDir.open(CONTROL_RUN).records()}
    ce = analysis["signals"]["ce"]
    method = ce["rule_selected"]
    tau = ce["methods"][method]["final_tau"]
    dev = [r for r in records if r["split"] == "dev"]

    label_mismatches = [
        r["query_id"] for r in dev
        if r["expects_answer"]
        and control[r["query_id"]]["retrieval"]["all_golds_retrieved@k"] != r["all_golds_retrieved@5"]
    ]

    rows = []
    for r in dev:
        rows.append({
            "gate_answers": features_for(r, "ce")[method] >= tau,
            "model_refused": bool(control[r["query_id"]]["tier0"]["refused"]),
            "should_answer": bool(r["should_answer"]),
        })
    counts: dict[str, int] = {}
    for row in rows:
        key = (f"gate_{'answer' if row['gate_answers'] else 'refuse'}"
               f"|model_{'refused' if row['model_refused'] else 'answered'}"
               f"|{'should_answer' if row['should_answer'] else 'should_refuse'}")
        counts[key] = counts.get(key, 0) + 1

    labels = [row["should_answer"] for row in rows]

    def policy(answered: list[bool]) -> dict[str, Any]:
        return {
            "coverage": bootstrap_ci([1.0 if a else 0.0 for a in answered], statistics.mean, name="mean", seed=42).to_dict(),
            "precision": _interval(ratio_ci(labels, answered)),
            "false_refusal_rate": _interval(ratio_ci([not a for a in answered], labels)),
        }

    return {
        "method": method,
        "tau": tau,
        "n_dev": len(rows),
        "label_mismatches_vs_t20_control": label_mismatches,
        "counts": dict(sorted(counts.items())),
        "policies": {
            "always_answer": policy([True] * len(rows)),
            "model_only": policy([not row["model_refused"] for row in rows]),
            "gate_only": policy([row["gate_answers"] for row in rows]),
            "any_signal_wins": policy([row["gate_answers"] and not row["model_refused"] for row in rows]),
        },
    }


def metrics_from(analysis: dict[str, Any]) -> dict[str, Any]:
    """RunDir's guard allows intervals only: thresholds and names go in as strings."""
    ce = analysis["signals"]["ce"]
    metrics: dict[str, Any] = {
        "run": {
            "n_questions": str(analysis["n_questions"]),
            "n_should_answer": str(analysis["n_should_answer"]),
            "splits": ",".join(analysis["splits"]),
            "test_split_evaluated": "false",
            "ce_truncated_pairs": str(analysis["ce_truncated_pairs"]),
            "rule_selected": ce["rule_selected"],
            "selected_final_tau": repr(ce["methods"][ce["rule_selected"]]["final_tau"]),
        }
    }
    for signal, data in analysis["signals"].items():
        metrics[signal] = {
            m: {
                "oof_coverage": d["oof_coverage"],
                "oof_precision": d["oof_precision"],
                "oof_false_refusal_rate": d["oof_false_refusal_rate"],
            }
            for m, d in data["methods"].items()
        }
    return metrics


def plot(analysis: dict[str, Any], out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    styles = {"raw": ("gray", "--"), "normalized": ("tab:blue", "-"), "margin": ("tab:orange", "-"), "percentile": ("tab:green", "-")}
    titles = {"ce": "Cross-encoder, MaxP logits (primary)", "dense": "Dense cosine (exploratory, not selectable)"}
    for row, signal in enumerate(SIGNALS):
        data = analysis["signals"][signal]
        for method in METHODS:
            color, line = styles[method]
            curve = [p for p in data["methods"][method]["curve"] if p["precision"] is not None]
            label = method + ("" if method in analysis["candidates"] else " (reference, not eligible)")
            axes[row][0].plot([p["coverage"] for p in curve], [p["precision"] for p in curve], line, color=color, label=label)
            axes[row][1].plot(
                [p["false_refusal_rate"] for p in curve], [p["wrong_answer_rate"] for p in curve], line, color=color, label=label
            )
            oof = data["methods"][method]
            if oof["oof_precision"] is not None:
                axes[row][0].plot(oof["oof_coverage"]["value"], oof["oof_precision"]["value"], "x", color=color, markersize=10, mew=2)
        axes[row][0].axhline(analysis["floor"], color="red", linewidth=0.8, linestyle=":", label=f"{analysis['floor']:.0%} precision floor")
        axes[row][0].set(title=f"{titles[signal]}: precision vs coverage", xlabel="coverage (answered / all)", ylabel="precision (correct / answered)")
        axes[row][1].set(title=f"{titles[signal]}: refusal tradeoff", xlabel="false-refusal rate (should-answer refused)", ylabel="wrong-answer rate (1 - precision)")
        axes[row][0].legend(loc="lower left", fontsize=8)
        axes[row][1].legend(loc="upper right", fontsize=8)
    fig.suptitle(f"τ calibration, train+dev (n={analysis['n_questions']}). Lines: in-sample sweep. ×: out-of-fold estimate at the cross-validated τ.")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ---- main ---------------------------------------------------------------------------------


def report(analysis: dict[str, Any], run_path: Path) -> None:
    def fmt(iv):
        return "--" if iv is None else f"{iv['value']:.3f} [{iv['ci_low']:.3f}, {iv['ci_high']:.3f}] (n={iv['n']})"

    print(f"\nrun dir: {run_path} | floor {analysis['floor']:.0%} | eligible: {', '.join(analysis['candidates'])}")
    print(f"should-answer: {analysis['n_should_answer']}/{analysis['n_questions']} | cross-encoder truncated pairs: {analysis['ce_truncated_pairs']}")
    for signal, data in analysis["signals"].items():
        print(f"\n== {signal} ({'primary' if data['selectable'] else 'exploratory, not selectable'}) ==")
        for m in METHODS:
            d = data["methods"][m]
            print(f"  {m:<11} tau={d['final_tau']!r:<22} oof coverage {fmt(d['oof_coverage'])}  precision {fmt(d['oof_precision'])}  false-refusal {fmt(d['oof_false_refusal_rate'])}")
        print(f"  eligible meeting floor out of fold: {data['candidates_meeting_floor_oof'] or 'none'} | rule selects: {data['rule_selected']}")
        for k, v in data["oof_coverage_differences"].items():
            print(f"    coverage {k}: {fmt(v)}")
    x = analysis["model_refusals_dev"]
    print(f"\n== dev, gate ({x['method']}, tau={x['tau']!r}) vs model refusals (in-sample) ==")
    print(f"  label mismatches vs T20 control: {x['label_mismatches_vs_t20_control'] or 'none'}")
    for k, v in x["counts"].items():
        print(f"  {k:<48} {v}")
    for name, p in x["policies"].items():
        print(f"  {name:<16} coverage {fmt(p['coverage'])}  precision {fmt(p['precision'])}  false-refusal {fmt(p['false_refusal_rate'])}")


def reselect(run_path: Path, floor: float, include_raw: bool) -> int:
    """Post-hoc re-selection on an existing run's stored scores: no re-scoring,
    no quota. Writes beside the pre-registered artifacts, never over them."""
    candidates = (REFERENCE, *CANDIDATES) if include_raw else CANDIDATES
    records = list(RunDir.open(run_path).records())
    tag = f"floor{round(floor * 100)}{'_raw_eligible' if include_raw else ''}"
    analysis = analyze(records, floor=floor, candidates=candidates)
    analysis["post_hoc"] = True
    analysis["model_refusals_dev"] = model_refusal_crosstab(records, analysis)
    (run_path / f"tau_calibration_{tag}.json").write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")
    plot(analysis, run_path / f"tau_curves_{tag}.png")
    print(f"POST-HOC re-selection ({tag}); pre-registered artifacts untouched")
    report(analysis, run_path)
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-run", type=Path, help="re-select post hoc from a finished run's stored scores")
    parser.add_argument("--floor", type=float, default=FLOOR)
    parser.add_argument("--include-raw", action="store_true", help="make the raw score eligible for selection")
    args = parser.parse_args()
    if args.from_run:
        return reselect(args.from_run, args.floor, args.include_raw)
    if args.floor != FLOOR or args.include_raw:
        parser.error("--floor/--include-raw change the pre-registered analysis; use them with --from-run only")


    questions = [q for q in load_gold_questions(GOLD_PATH) if q.split in SPLITS]
    assert questions and all(q.split in SPLITS for q in questions)
    chunks = load_chunks(CHUNKS_PATH)
    lookup = {c.chunk_id: c for c in chunks}
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
    print(f"{len(questions)} questions ({', '.join(SPLITS)}); test questions filtered out at load")

    embedder = BgeEmbedder()
    cache = EmbeddingCache(EMBED_CACHE)
    dense = DenseIndex(db_path=INDEX_DIR, embedder=embedder, cache=cache, model_name=MODEL_NAME)
    bm25 = BM25Index()
    bm25.build(chunks)
    literal = LiteralIndex()
    literal.build(chunks)
    search = build_search(dense, bm25, literal, lookup)
    reranker = CrossEncoderReranker()
    null_ids = random.Random(NULL_SEED).sample(sorted(lookup), N_NULL)
    null_texts = [lookup[i].text for i in null_ids]

    config = Config.from_dict(
        {
            "name": "tau-calibration",
            "arm": "t21-ce-maxp-gate",
            "chunk": {"max_tokens": 512},
            "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
            "eval": {"gold_path": str(GOLD_PATH), "split": "train+dev"},
            "notes": (
                "Task 21, pre-registered in decisions/0009. Frozen retrieval (decisions/0007). "
                f"Label: in scope and all_golds_retrieved@{K}. Signal: {CE_MODEL} raw logits, "
                f"MaxP over {WINDOW_CHARS}-char windows; dense cosine as exploratory reference. "
                f"Methods: raw (reference), normalized (z vs {CANDIDATE_K}-pool), margin (s1-s2), "
                f"percentile (vs {N_NULL} null passages, seed {NULL_SEED}). {FOLDS}-fold CV by slice, "
                f"seed {CV_SEED}, floor {FLOOR}. Zero generation quota."
            ),
        }
    )

    cached_analysis: dict[str, Any] = {}

    def summarize(records):
        cached_analysis["value"] = analyze(records)
        return metrics_from(cached_analysis["value"])

    run_dir = run_arm(
        config, questions,
        evaluate_fn_for(search, reranker, embedder, cache, gold_lookup, lookup, null_texts),
        summarize, root="runs",
    )
    split_lock = load_split_lock(SPLIT_LOCK_PATH)
    run_dir.write_lock(Lock(kind="corpus", digest="bp_off+fixed512", detail={"chunks_path": str(CHUNKS_PATH)}))
    run_dir.write_lock(Lock(kind="model", digest=f"{MODEL_NAME}+{CE_MODEL}", detail={"embedder": MODEL_NAME, "cross_encoder": CE_MODEL}))
    run_dir.write_lock(Lock(kind="split", digest=split_lock["split_hash"], detail={"splits": list(SPLITS), "test_evaluated": False}))

    records = list(run_dir.records())
    analysis = cached_analysis.get("value") or analyze(records)
    analysis["model_refusals_dev"] = model_refusal_crosstab(records, analysis)
    analysis["null_passage_ids"] = null_ids
    (run_dir.path / "tau_calibration.json").write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")
    plot(analysis, run_dir.path / "tau_curves.png")

    report(analysis, run_dir.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
