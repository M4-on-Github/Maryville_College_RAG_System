"""Task 22c rung 1: strengthened refusal instruction -- decisions/0014.

T22b (decisions/0013) found 100% of false-answer errors on the frozen
Checkpoint-E config are `out_of_scope`. decisions/0009 already rejected a
pre-generation retrieval-score gate as the fix; rung 0 of decisions/0014
found real (not clean) answer-level separation in stored Tier 1
faithfulness scores, enough to justify building an actual mechanism. Rung
1 is the cheapest one: a prompt-only edit, zero new code paths, still the
existing `Generator` interface -- `SCOPE_STRICT_SYSTEM_PROMPT`
(`mcrag/generate/prompting.py`) explicitly asks the model to check whether
the passages address the question's specific subject before answering,
and to refuse rather than infer from tangential overlap.

Three dev arms, interleaved (`run_interleaved`, question-major, per
decisions/0008's interleaving requirement), all `gemma4:31b` (Checkpoint
E, decisions/0010), all on the frozen retrieval config (decisions/0007),
full 60-question **dev** split (dev is selection, not inference --
decisions/0006):

    scope_strict_gemma4_31b    -- SCOPE_STRICT_SYSTEM_PROMPT (the new arm)
    free_form_gemma4_31b_a     -- SYSTEM_PROMPT (current prompt), rerun
                                   fresh this session -- not reusing
                                   decisions/0010's older run, per that
                                   doc's own same-session-pairing rationale
    free_form_gemma4_31b_b     -- identical config, a second live pass
                                   (the noise floor, decisions/0008's method)

**Primary comparison:** `scope_strict_gemma4_31b` vs `free_form_gemma4_31b_a`,
restricted to the `out_of_scope` slice -- `refusal_correct` there is exactly
"1 - false-answer rate" (`out_of_scope` questions have no gold, so
`tier0_scoring.score_tier0`'s `refusal_correct = refused != expects_answer`
collapses to `refused` itself). Pooled `refusal_correct`, `faithfulness`,
`citation_accuracy`/`citation_validity` over the full dev split are reported
beside it as collateral-damage checks -- a rung that "fixes" `out_of_scope`
by making the model refuse everything is not a win (decisions/0009's
coverage collapse already taught this lesson once). Effect size + CI only,
never a p-value (dev-split, decisions/0006). Noise floor from the `_b` pair.

    python scripts/run_t22c_scope_signal.py
"""

from __future__ import annotations

import json
import os
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
    build_search,
    load_chunks,
    tier1_fields,
)
from run_t22_metered_ablations import summarize  # noqa: E402
from run_t22b_test_confirmatory import compare_effect_only  # noqa: E402

from mcrag.config import Config  # noqa: E402
from mcrag.eval.ablation_runner import run_interleaved  # noqa: E402
from mcrag.eval.chunk_alignment import canonicalize_retrieved  # noqa: E402
from mcrag.eval.gold import load_gold_questions, load_split_lock  # noqa: E402
from mcrag.eval.nli_faithfulness import NLIFaithfulnessScorer  # noqa: E402
from mcrag.eval.retrieval_metrics import all_golds_retrieved_at_k, mrr, ndcg_at_k, recall_at_k  # noqa: E402
from mcrag.eval.tier0_scoring import score_tier0  # noqa: E402
from mcrag.generate.ollama_cloud import ContextOverflow, GenerationError, OllamaCloudGenerator  # noqa: E402
from mcrag.generate.prompting import SCOPE_STRICT_SYSTEM_PROMPT, SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.runlog import Lock  # noqa: E402
from mcrag.types import GoldQuestion  # noqa: E402

# decisions/0014 rung 1. Doubles as run_interleaved's per-arm expected_model dict.
MODELS: dict[str, str] = {
    "scope_strict_gemma4_31b": "gemma4:31b",
    "free_form_gemma4_31b_a": "gemma4:31b",
    "free_form_gemma4_31b_b": "gemma4:31b",
}
SCOPE_STRICT_ARMS = {"scope_strict_gemma4_31b"}
REFERENCE_ARM = "free_form_gemma4_31b_a"
NOISE_FLOOR_ARM = "free_form_gemma4_31b_b"
PRIMARY_ARM = "scope_strict_gemma4_31b"
PRIMARY_SLICE = "out_of_scope"
SLICES = ("single_silo", "cross_silo", "out_of_scope", "adversarial", "exact_match", "temporal", "multi_turn")


def build_configs() -> list[Config]:
    configs = []
    for arm, model in MODELS.items():
        configs.append(
            Config.from_dict(
                {
                    "name": "t22c-scope-signal-rung1",
                    "arm": arm,
                    "chunk": {"max_tokens": 512},
                    "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
                    "generation": {"model": model, "temperature": 0.0},
                    "eval": {"gold_path": str(GOLD_PATH), "split": "dev"},
                    "notes": (
                        f"Task 22c rung 1 arm {arm}: {model}, "
                        f"{'scope-strict' if arm in SCOPE_STRICT_ARMS else 'free-form'} prompt, "
                        "frozen retrieval (decisions/0007), full dev split. decisions/0014."
                    ),
                }
            )
        )
    return configs


def evaluate_fn_for(search, gold_lookup, retrieved_lookup, faithfulness):
    def build(config: Config):
        model = config.generation.model
        arm = config.arm
        system_prompt = SCOPE_STRICT_SYSTEM_PROMPT if arm in SCOPE_STRICT_ARMS else SYSTEM_PROMPT
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
            return record

        return evaluate

    return build


# ---- main -------------------------------------------------------------------


def main() -> int:
    dev_questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "dev"]
    chunks = load_chunks(CHUNKS_PATH)
    chunk_lookup = {c.chunk_id: c for c in chunks}
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
    print(f"{len(dev_questions)} dev questions, 3 arms interleaved -> {len(dev_questions) * 3} generation calls max")

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
        quota_errors=(GenerationError, ContextOverflow, requests.exceptions.RequestException),
    )

    split_lock = load_split_lock(SPLIT_LOCK_PATH)
    for arm, run_dir in results.items():
        run_dir.write_lock(Lock(kind="corpus", digest="bp_off+fixed512", detail={"chunks_path": str(CHUNKS_PATH)}))
        run_dir.write_lock(Lock(kind="model", digest=f"{MODELS[arm]}", detail={"generator": MODELS[arm], "arm": arm}))
        run_dir.write_lock(Lock(kind="split", digest=split_lock["split_hash"], detail={"split": "dev"}))

    records = {arm: list(run_dir.records()) for arm, run_dir in results.items()}

    analysis: dict[str, Any] = {
        "reference_arm": REFERENCE_ARM, "primary_arm": PRIMARY_ARM, "n_dev": len(dev_questions),
    }
    analysis["primary_out_of_scope"] = compare_effect_only(
        records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t22c", split="dev", slice_filter=PRIMARY_SLICE
    )
    analysis["primary_pooled"] = compare_effect_only(
        records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t22c", split="dev"
    )
    analysis["primary_by_slice"] = {
        s: compare_effect_only(records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t22c", split="dev", slice_filter=s)
        for s in SLICES
    }
    analysis["noise_floor_out_of_scope"] = compare_effect_only(
        records[REFERENCE_ARM], records[NOISE_FLOOR_ARM], "noise_floor", split="dev", slice_filter=PRIMARY_SLICE
    )
    analysis["noise_floor_pooled"] = compare_effect_only(
        records[REFERENCE_ARM], records[NOISE_FLOOR_ARM], "noise_floor", split="dev"
    )
    analysis["per_arm_summary"] = {arm: summarize(recs) for arm, recs in records.items()}

    out_path = Path("runs/t22c_scope_signal_analysis.json")
    out_path.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")

    def fmt(iv):
        if iv is None:
            return "--"
        v = iv.get("interval", iv)
        return f"{v['value']:+.3f} [{v['ci_low']:+.3f}, {v['ci_high']:+.3f}] (n={v['n']})"

    print(f"\nrun dirs: {[str(rd.path) for rd in results.values()]}")

    print(f"\n== primary, out_of_scope slice: {PRIMARY_ARM} - {REFERENCE_ARM} (n={analysis['primary_out_of_scope']['n_questions']}) ==")
    print("   (refusal_correct here IS 1 - false-answer rate: out_of_scope has no gold)")
    for k, v in analysis["primary_out_of_scope"]["b_minus_a"].items():
        print(f"  {k:<20} {fmt(v)}")

    print(f"\n== primary, pooled full dev (n={analysis['primary_pooled']['n_questions']}) ==")
    for k, v in analysis["primary_pooled"]["b_minus_a"].items():
        print(f"  {k:<20} {fmt(v)}")

    print(f"\n== noise floor, out_of_scope slice ({NOISE_FLOOR_ARM} - {REFERENCE_ARM}) ==")
    for k, v in analysis["noise_floor_out_of_scope"]["b_minus_a"].items():
        print(f"  {k:<20} {fmt(v)}")

    print(f"\n== noise floor, pooled full dev ==")
    for k, v in analysis["noise_floor_pooled"]["b_minus_a"].items():
        print(f"  {k:<20} {fmt(v)}")

    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
