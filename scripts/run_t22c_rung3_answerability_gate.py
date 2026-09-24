"""Task 22c rung 3: dedicated LLM answerability self-check -- decisions/0014.

Rung 1 (`scope_strict_gemma4_31b`, kept) folds "does this passage actually
address the question's subject?" into the same call that drafts the answer.
Rung 2 (a post-hoc faithfulness override on rung 1's own answers) found no
calibrated middle ground -- either a no-op or a collateral-damage failure
on the same scale as the rejected CE gate, just smaller. Rung 3 is a
genuine two-step pipeline, not a post-hoc override: ask the scope question
*in isolation*, before any answer is drafted, and only draft an answer if
that dedicated check says the passages actually address the subject. A
NO skips the generation call entirely -- the real efficiency case rung 2
could never claim, since rung 2 could only override an answer already
paid for.

Same model both calls (`gemma4:31b`) deliberately: a cheaper gate model
would confound rung 3's own effect with an unregistered model-choice
ablation, a separate question this rung does not ask.

Parsing discipline: the check call's first line is read case-insensitively
for a leading YES/NO token. Anything else (empty completion, neither
token, both) is **not** defaulted to an answer -- it fails closed to NO
and is flagged `self_check_unparseable: true` on the record.

Three dev arms, interleaved (`run_interleaved`, question-major), all
`gemma4:31b`, frozen retrieval (decisions/0007), full 60-question dev
split (decisions/0006):

    answerability_gate_gemma4_31b -- the new two-step pipeline (this rung)
    scope_strict_gemma4_31b_a     -- rung 1's prompt alone, rerun fresh
                                      this session -- the reference
                                      (best-so-far; rung 3 stacks on rung 1,
                                      not on the free-form baseline)
    scope_strict_gemma4_31b_b     -- identical config, second live pass --
                                      the noise floor for *both* calls in
                                      the gated arm (decisions/0008: temp-0
                                      is not fully deterministic on this
                                      endpoint, and the gated arm makes two
                                      stochastic calls per question, not one)

**Primary comparison:** `answerability_gate_gemma4_31b` vs
`scope_strict_gemma4_31b_a`, `out_of_scope` false-answer rate primary;
pooled `refusal_correct`/faithfulness/citation metrics secondary, the same
collateral-damage check every rung in this ladder has used. New metric
specific to this rung, reported not gated: calls actually made (self-check:
60 fixed; generation: however many self-checks answered YES -- the cost
delta against rung 1's fixed 60) and a confusion matrix between the
self-check's NO decisions and `scope_strict`'s own in-prompt refusals.
Effect size + CI only, never a p-value (dev-split, decisions/0006).

    python scripts/run_t22c_rung3_answerability_gate.py
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
from mcrag.eval.ablation_runner import run_interleaved, unquarantined  # noqa: E402
from mcrag.eval.chunk_alignment import canonicalize_retrieved  # noqa: E402
from mcrag.eval.gold import load_gold_questions, load_split_lock  # noqa: E402
from mcrag.eval.nli_faithfulness import NLIFaithfulnessScorer  # noqa: E402
from mcrag.eval.retrieval_metrics import all_golds_retrieved_at_k, mrr, ndcg_at_k, recall_at_k  # noqa: E402
from mcrag.eval.tier0_scoring import score_tier0  # noqa: E402
from mcrag.generate.ollama_cloud import ContextOverflow, GenerationError, OllamaCloudGenerator  # noqa: E402
from mcrag.generate.prompting import (  # noqa: E402
    ANSWERABILITY_CHECK_SYSTEM_PROMPT,
    SCOPE_STRICT_SYSTEM_PROMPT,
    build_user_prompt,
)
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.runlog import Lock  # noqa: E402
from mcrag.types import GoldQuestion  # noqa: E402

# decisions/0014 rung 3. Doubles as run_interleaved's per-arm expected_model dict.
MODELS: dict[str, str] = {
    "answerability_gate_gemma4_31b": "gemma4:31b",
    "scope_strict_gemma4_31b_a": "gemma4:31b",
    "scope_strict_gemma4_31b_b": "gemma4:31b",
}
GATE_ARM = "answerability_gate_gemma4_31b"
REFERENCE_ARM = "scope_strict_gemma4_31b_a"
NOISE_FLOOR_ARM = "scope_strict_gemma4_31b_b"
PRIMARY_ARM = GATE_ARM
PRIMARY_SLICE = "out_of_scope"
SLICES = ("single_silo", "cross_silo", "out_of_scope", "adversarial", "exact_match", "temporal", "multi_turn")


def parse_self_check(text: str) -> tuple[bool, bool]:
    """(answerable, unparseable). Fails closed to NO on anything ambiguous --
    empty completion, neither token, or both -- per decisions/0014 rung 3's
    pre-registered parsing discipline."""
    stripped = text.strip()
    if not stripped:
        return False, True
    first_line = stripped.splitlines()[0].strip().upper()
    starts_yes = first_line.startswith("YES")
    starts_no = first_line.startswith("NO")
    if starts_yes and not starts_no:
        return True, False
    if starts_no and not starts_yes:
        return False, False
    return False, True


def build_configs() -> list[Config]:
    configs = []
    for arm, model in MODELS.items():
        configs.append(
            Config.from_dict(
                {
                    "name": "t22c-answerability-gate-rung3",
                    "arm": arm,
                    "chunk": {"max_tokens": 512},
                    "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
                    "generation": {"model": model, "temperature": 0.0},
                    "eval": {"gold_path": str(GOLD_PATH), "split": "dev"},
                    "notes": (
                        f"Task 22c rung 3 arm {arm}: {model}, "
                        f"{'two-step answerability gate' if arm == GATE_ARM else 'scope-strict single call'}, "
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

            if arm != GATE_ARM:
                completion = generator.complete(prompt, system=SCOPE_STRICT_SYSTEM_PROMPT)
                _fill_generated(record, completion)
                _score_generated(record, completion, question, retrieved_urls, gold_urls, faithfulness, found)
                return record

            # GATE_ARM: dedicated self-check call first, in isolation.
            check_completion = generator.complete(prompt, system=ANSWERABILITY_CHECK_SYSTEM_PROMPT)
            answerable, unparseable = parse_self_check(check_completion.text)
            record["self_check_raw"] = check_completion.text
            record["self_check_answerable"] = answerable
            record["self_check_unparseable"] = unparseable
            record["self_check_wall_s"] = check_completion.usage.wall_s
            record["self_check_completion_tokens"] = check_completion.usage.completion_tokens

            if answerable:
                completion = generator.complete(prompt, system=SCOPE_STRICT_SYSTEM_PROMPT)
                record["generation_call_made"] = True
                _fill_generated(record, completion)
                record["wall_s"] = record["wall_s"] + check_completion.usage.wall_s
                _score_generated(record, completion, question, retrieved_urls, gold_urls, faithfulness, found)
            else:
                record["generation_call_made"] = False
                record.update(
                    {
                        "model": check_completion.model,
                        "answer": "",
                        "finish_reason": check_completion.finish_reason,
                        "prompt_tokens_server": check_completion.usage.prompt_tokens,
                        "completion_tokens": 0,
                        "reasoning_chars": 0,
                        "answer_chars": 0,
                        "reasoning_char_share": None,
                        "wall_s": check_completion.usage.wall_s,
                    }
                )
                record["tier0"] = {
                    "citation_accuracy": None,
                    "citation_validity": None,
                    "refused": True,
                    "refusal_correct": True != bool(question.gold),  # noqa: E712 -- mirrors score_tier0's own `refused != expects_answer`
                    "exact_match_presence": None,
                }
            return record

        return evaluate

    return build


def _fill_generated(record: dict[str, Any], completion) -> None:
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
                reasoning_chars / (reasoning_chars + answer_chars) if (reasoning_chars + answer_chars) else None
            ),
            "wall_s": completion.usage.wall_s,
        }
    )


def _score_generated(record, completion, question, retrieved_urls, gold_urls, faithfulness, found) -> None:
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


# ---- rung-3-specific reporting -----------------------------------------------


def calls_made(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    self_checks = sum(1 for r in records if "self_check_answerable" in r)
    generation_calls = sum(1 for r in records if r.get("generation_call_made", True))
    return {
        "n_questions": n,
        "self_check_calls": self_checks,
        "generation_calls": generation_calls,
        "total_calls": self_checks + generation_calls,
        "worst_case_total_calls": self_checks * 2,
        "reference_arm_total_calls": n,  # scope_strict single-call arm, for comparison
    }


def confusion_matrix(gate_records: list[dict[str, Any]], reference_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Self-check NO (gate arm) vs scope_strict's own in-prompt refusal
    (reference arm), paired by query_id -- does the dedicated call catch
    cases the combined prompt missed, or is it mostly redundant?"""
    gate = {r["query_id"]: r for r in unquarantined(gate_records)}
    ref = {r["query_id"]: r for r in unquarantined(reference_records)}
    qids = sorted(set(gate) & set(ref))
    cells = {"no_no": 0, "no_yes": 0, "yes_no": 0, "yes_yes": 0}
    for q in qids:
        gate_no = not gate[q]["self_check_answerable"]
        ref_refused = ref[q]["tier0"]["refused"]
        key = f"{'no' if gate_no else 'yes'}_{'no' if ref_refused else 'yes'}"
        cells[key] += 1
    return {
        "n_paired": len(qids),
        "rows": "self_check(no/yes)", "cols": "scope_strict_refused(no=refused/yes=answered)",
        "counts": cells,
        "self_check_no_scope_strict_answered": cells["no_yes"],  # gate catches something the combined prompt missed
        "self_check_yes_scope_strict_refused": cells["yes_no"],  # combined prompt catches something the gate missed
    }


def absolute_out_of_scope(records: list[dict[str, Any]]) -> dict[str, Any]:
    sub = [r for r in unquarantined(records) if r["slice"] == "out_of_scope"]
    n = len(sub)
    refused = sum(1 for r in sub if r["tier0"]["refused"])
    return {"n": n, "refused": refused, "false_answer_rate": (n - refused) / n if n else None}


# ---- main -------------------------------------------------------------------


def main() -> int:
    dev_questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "dev"]
    chunks = load_chunks(CHUNKS_PATH)
    chunk_lookup = {c.chunk_id: c for c in chunks}
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
    print(
        f"{len(dev_questions)} dev questions, 3 arms interleaved -> "
        f"up to {len(dev_questions) * 2 + len(dev_questions) * 2} calls "
        f"({len(dev_questions)} self-checks + up to {len(dev_questions)} generations for the gate arm, "
        f"{len(dev_questions)} each for the two reference-arm passes)"
    )

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
        records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t22c_rung3", split="dev", slice_filter=PRIMARY_SLICE
    )
    analysis["primary_pooled"] = compare_effect_only(
        records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t22c_rung3", split="dev"
    )
    analysis["primary_by_slice"] = {
        s: compare_effect_only(records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t22c_rung3", split="dev", slice_filter=s)
        for s in SLICES
    }
    analysis["noise_floor_out_of_scope"] = compare_effect_only(
        records[REFERENCE_ARM], records[NOISE_FLOOR_ARM], "noise_floor", split="dev", slice_filter=PRIMARY_SLICE
    )
    analysis["noise_floor_pooled"] = compare_effect_only(
        records[REFERENCE_ARM], records[NOISE_FLOOR_ARM], "noise_floor", split="dev"
    )
    analysis["per_arm_summary"] = {arm: summarize(recs) for arm, recs in records.items()}
    analysis["out_of_scope_absolute"] = {arm: absolute_out_of_scope(recs) for arm, recs in records.items()}
    analysis["calls_made"] = {
        GATE_ARM: calls_made(records[GATE_ARM]),
        REFERENCE_ARM: {"n_questions": len(dev_questions), "generation_calls": len(dev_questions), "self_check_calls": 0, "total_calls": len(dev_questions)},
    }
    analysis["confusion_matrix_self_check_vs_scope_strict"] = confusion_matrix(records[GATE_ARM], records[REFERENCE_ARM])

    out_path = Path("runs/t22c_rung3_answerability_gate_analysis.json")
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

    print("\n== noise floor, pooled full dev ==")
    for k, v in analysis["noise_floor_pooled"]["b_minus_a"].items():
        print(f"  {k:<20} {fmt(v)}")

    print(f"\n== out_of_scope absolute, all arms ==")
    for arm, d in analysis["out_of_scope_absolute"].items():
        rate = d["false_answer_rate"]
        print(f"  {arm:<32} {d['refused']}/{d['n']} refused, false-answer rate {rate:.3f}" if rate is not None else f"  {arm:<32} n=0")

    print("\n== calls made ==")
    for arm, d in analysis["calls_made"].items():
        print(f"  {arm:<32} {d}")

    cm = analysis["confusion_matrix_self_check_vs_scope_strict"]
    print(f"\n== confusion matrix: self-check NO/YES vs scope_strict refused/answered (n={cm['n_paired']}) ==")
    print(f"  {cm['counts']}")
    print(f"  self-check NO but scope_strict answered: {cm['self_check_no_scope_strict_answered']}")
    print(f"  self-check YES but scope_strict refused: {cm['self_check_yes_scope_strict_refused']}")

    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
