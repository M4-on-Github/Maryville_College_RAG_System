"""Task 22b: the test-split confirmatory pass -- decisions/0013.

The one place in the project that spends the 120-question **test** split.
Three arms, interleaved, all on the frozen retrieval config (decisions/0007,
unchanged), `IdentityReformulator` (no-op, decisions/0011), free-form prompt,
no pre-generation abstention gate -- exactly Task 20 baseline's methodology,
replayed on test, plus the one axis Checkpoint E actually changed:

    t22b_baseline_20b_a       -- gpt-oss:20b, Task 20 baseline's methodology
    t22b_baseline_20b_b       -- identical config, a second live pass (the
                                  noise floor, decisions/0008's method)
    t22b_frozen_gemma4_31b    -- gemma4:31b, the frozen Checkpoint-E config

Exactly one comparison carries a p-value under this doc: frozen vs baseline,
pooled over all 120 test questions (`analysis["primary"]`). Everything else
(the noise floor, by-slice breakdowns, the retrieval sanity check) is effect
size + CI only, same convention as every dev-split ablation.

Scored with Tier 0 + Tier 1 only -- decisions/0012 (Tier 3 uncalibrated) and
this doc's own resolution (full Tier 2 skipped for this pass).

    python scripts/run_t22b_test_confirmatory.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timezone
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
)
from run_t22_metered_ablations import evaluate_fn_for, summarize  # noqa: E402

from mcrag.config import Config  # noqa: E402
from mcrag.eval.ablation_runner import run_interleaved, unquarantined  # noqa: E402
from mcrag.eval.gold import load_gold_questions, load_split_lock  # noqa: E402
from mcrag.eval.nli_faithfulness import NLIFaithfulnessScorer  # noqa: E402
from mcrag.eval.significance import assert_reportable, mcnemar_exact, paired_bootstrap_comparison  # noqa: E402
from mcrag.eval.stats import bootstrap_ci  # noqa: E402
from mcrag.generate.ollama_cloud import ContextOverflow, GenerationError  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.runlog import Lock, RunDir  # noqa: E402

# decisions/0013. Doubles as run_interleaved's per-arm expected_model dict.
MODELS: dict[str, str] = {
    "t22b_baseline_20b_a": "gpt-oss:20b",
    "t22b_baseline_20b_b": "gpt-oss:20b",
    "t22b_frozen_gemma4_31b": "gemma4:31b",
}
REFERENCE_ARM = "t22b_baseline_20b_a"
NOISE_FLOOR_ARM = "t22b_baseline_20b_b"
PRIMARY_ARM = "t22b_frozen_gemma4_31b"
SLICES = ("single_silo", "cross_silo", "out_of_scope", "adversarial", "exact_match", "temporal", "multi_turn")
NOTES_LOG_PATH = Path("notes.md")


def build_configs() -> list[Config]:
    configs = []
    for arm, model in MODELS.items():
        configs.append(
            Config.from_dict(
                {
                    "name": "t22b-test-confirmatory",
                    "arm": arm,
                    "chunk": {"max_tokens": 512},
                    "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
                    "generation": {"model": model, "temperature": 0.0},
                    "eval": {"gold_path": str(GOLD_PATH), "split": "test"},
                    "notes": (
                        f"Task 22b arm {arm}: {model}, free-form prompt, no "
                        "abstention gate, frozen retrieval (decisions/0007), "
                        "full test split. decisions/0013."
                    ),
                }
            )
        )
    return configs


def _log_test_access(configs: list[Config], split_hash: str, n_questions: int) -> None:
    """Standing rule: log every test-split access. Appended once, right
    before the first test-split question is actually sent to a generator."""
    entry = (
        f"\n## {datetime.now(timezone.utc).isoformat(timespec='seconds')} -- test-split access\n\n"
        f"Task 22b (decisions/0013): {n_questions} test questions x {len(configs)} arms "
        f"({', '.join(c.arm for c in configs)}). Frozen config: decisions/0007 retrieval, "
        f"decisions/0011 no reformulation, decisions/0010 generation model gemma4:31b vs "
        f"Task 20 baseline gpt-oss:20b. split.lock hash: {split_hash}.\n"
    )
    if not NOTES_LOG_PATH.exists():
        NOTES_LOG_PATH.write_text(
            "# Test-split access log\n\nPer the standing rule, every access of the 120-question "
            "test split is logged here, at the moment the first question is actually sent to a "
            "generator, not before.\n" + entry,
            encoding="utf-8",
        )
    else:
        with NOTES_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(entry)


# ---- comparisons ------------------------------------------------------------


def compare_licensed(a_records: list[dict], b_records: list[dict], label: str, split: str) -> dict[str, Any]:
    """The one comparison decisions/0013 licenses a p-value for: binary
    metrics get exact McNemar, graded/cost metrics get a bootstrap CI only
    (PLAN 4f). `assert_reportable` is a no-op on test (it only guards dev)
    but stays in the call path so a split typo can't silently slip through."""
    a = {r["query_id"]: r for r in unquarantined(a_records)}
    b = {r["query_id"]: r for r in unquarantined(b_records)}
    qids = sorted(set(a) & set(b))

    def binary(value_fn, metric: str) -> dict[str, Any] | None:
        both = [q for q in qids if value_fn(a[q]) is not None and value_fn(b[q]) is not None]
        if not both:
            return None
        result = assert_reportable(
            mcnemar_exact(
                [int(value_fn(a[q])) for q in both], [int(value_fn(b[q])) for q in both],
                split=split, metric=f"{label}:{metric}",
            )
        )
        return {"interval": result.interval.to_dict(), "p_value": result.p_value, "test": result.test}

    def graded(value_fn, metric: str) -> dict[str, Any] | None:
        both = [q for q in qids if value_fn(a[q]) is not None and value_fn(b[q]) is not None]
        if not both:
            return None
        result = assert_reportable(
            paired_bootstrap_comparison(
                [float(value_fn(a[q])) for q in both], [float(value_fn(b[q])) for q in both],
                split=split, metric=f"{label}:{metric}",
            )
        )
        return {"interval": result.interval.to_dict(), "p_value": result.p_value, "test": result.test}

    return {
        "label": label,
        "n_questions": len(qids),
        "b_minus_a": {
            "refusal_correct": binary(lambda r: 1 if r["tier0"]["refusal_correct"] else 0, "refusal_correct"),
            "citation_accuracy": binary(lambda r: r["tier0"]["citation_accuracy"], "citation_accuracy"),
            "citation_validity": binary(lambda r: r["tier0"]["citation_validity"], "citation_validity"),
            "faithfulness": graded(answered_faithfulness, "faithfulness"),
            "wall_s": graded(lambda r: r.get("wall_s"), "wall_s"),
            "completion_tokens": graded(lambda r: r.get("completion_tokens"), "completion_tokens"),
            "reasoning_char_share": graded(lambda r: r.get("reasoning_char_share"), "reasoning_char_share"),
        },
    }


def compare_effect_only(
    a_records: list[dict], b_records: list[dict], label: str, split: str, slice_filter: str | None = None
) -> dict[str, Any]:
    """Everything this doc does NOT license a p-value for: the noise floor,
    by-slice breakdowns, the retrieval sanity check. Effect size + CI, same
    as every dev-split comparison in the project -- never McNemar here."""
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
            split=split, metric=f"{label}:{metric}",
        )
        return result.interval.to_dict()

    def agree(field_fn) -> dict[str, Any] | None:
        if not qids:
            return None
        vals = [1.0 if field_fn(a[q]) == field_fn(b[q]) else 0.0 for q in qids]
        return bootstrap_ci(vals, statistics.mean, seed=42, name="mean").to_dict()

    def retrieval_metric(r: dict) -> float | None:
        return r["retrieval"]["all_golds_retrieved@k"] if "retrieval" in r else None

    return {
        "label": label,
        "slice": slice_filter or "pooled",
        "n_questions": len(qids),
        "exact_text_match": agree(lambda r: r.get("answer")),
        "b_minus_a": {
            "refusal_correct": paired(lambda r: 1.0 if r["tier0"]["refusal_correct"] else 0.0, "refusal_correct"),
            "faithfulness": paired(answered_faithfulness, "faithfulness"),
            "citation_accuracy": paired(lambda r: r["tier0"]["citation_accuracy"], "citation_accuracy"),
            "citation_validity": paired(lambda r: r["tier0"]["citation_validity"], "citation_validity"),
            "wall_s": paired(lambda r: r.get("wall_s"), "wall_s"),
            "completion_tokens": paired(lambda r: r.get("completion_tokens"), "completion_tokens"),
            "reasoning_char_share": paired(lambda r: r.get("reasoning_char_share"), "reasoning_char_share"),
            "all_golds_retrieved@k": paired(retrieval_metric, "all_golds_retrieved"),
        },
    }


# ---- main -------------------------------------------------------------------


def main() -> int:
    test_questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "test"]
    chunks = load_chunks(CHUNKS_PATH)
    chunk_lookup = {c.chunk_id: c for c in chunks}
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
    print(f"{len(test_questions)} test questions, 3 arms interleaved -> {len(test_questions) * 3} generation calls max")

    split_lock = load_split_lock(SPLIT_LOCK_PATH)

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
    _log_test_access(configs, split_lock["split_hash"], len(test_questions))

    results = run_interleaved(
        configs, test_questions, evaluate_fn_for(search, gold_lookup, chunk_lookup, faithfulness),
        summarize, expected_model=MODELS, root="runs",
        quota_errors=(GenerationError, ContextOverflow, requests.exceptions.RequestException),
    )

    for arm, run_dir in results.items():
        run_dir.write_lock(Lock(kind="corpus", digest="bp_off+fixed512", detail={"chunks_path": str(CHUNKS_PATH)}))
        run_dir.write_lock(Lock(kind="model", digest=f"{MODELS[arm]}", detail={"generator": MODELS[arm], "arm": arm}))
        run_dir.write_lock(Lock(kind="split", digest=split_lock["split_hash"], detail={"split": "test"}))

    records = {arm: list(run_dir.records()) for arm, run_dir in results.items()}

    analysis: dict[str, Any] = {
        "reference_arm": REFERENCE_ARM, "primary_arm": PRIMARY_ARM, "n_test": len(test_questions),
    }
    analysis["primary"] = compare_licensed(records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t22b", split="test")
    analysis["primary_by_slice"] = {
        s: compare_effect_only(records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t22b", split="test", slice_filter=s)
        for s in SLICES
    }
    analysis["noise_floor"] = compare_effect_only(records[REFERENCE_ARM], records[NOISE_FLOOR_ARM], "noise_floor", split="test")
    analysis["per_arm_summary"] = {arm: summarize(recs) for arm, recs in records.items()}

    out_path = Path("runs/t22b_test_confirmatory_analysis.json")
    out_path.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")

    def fmt(iv):
        if iv is None:
            return "--"
        v = iv.get("interval", iv)
        s = f"{v['value']:+.3f} [{v['ci_low']:+.3f}, {v['ci_high']:+.3f}] (n={v['n']})"
        if "p_value" in iv and iv["p_value"] is not None:
            s += f"  p={iv['p_value']:.4f}"
        return s

    print(f"\nrun dirs: {[str(rd.path) for rd in results.values()]}")
    print(f"\n== primary: {PRIMARY_ARM} - {REFERENCE_ARM} (pooled, n={analysis['primary']['n_questions']}) ==")
    for k, v in analysis["primary"]["b_minus_a"].items():
        print(f"  {k:<20} {fmt(v)}")

    nf = analysis["noise_floor"]["b_minus_a"]
    print(f"\n== noise floor ({NOISE_FLOOR_ARM} - {REFERENCE_ARM}) ==")
    for k, v in nf.items():
        print(f"  {k:<20} {fmt(v)}")

    print(f"\nwrote {out_path}")
    print(f"wrote {NOTES_LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
