"""Task 41b: the decision field moved to the END of the reply -- decisions/0018.

T41 (decisions/0017) rejected the prefix form: the label was reliable and caught 12/12
out-of-scope cases, but committing to ABSTAIN on line one stopped the model writing the
partial answer the adopted prompt gives (median completion tokens 63.5 -> 53.5,
`cross_silo` refusal_correct -0.500). This arm writes the answer first and labels it
afterwards, which is the one mechanism that rejection identified.

Three dev arms, interleaved question-major (`run_interleaved`, decisions/0008), all
`gemma4:31b` at temperature 0, frozen retrieval (decisions/0007), full 60-question
**dev** split:

    suffix_field_gemma4_31b     -- SUFFIX_DECISION_FIELD_SYSTEM_PROMPT (the candidate)
    scope_strict_gemma4_31b_a   -- SCOPE_STRICT_SYSTEM_PROMPT, the adopted config
                                   (decisions/0014 rung 1), rerun fresh this session
    scope_strict_gemma4_31b_b   -- identical to `_a`; the noise floor

Channels and metrics are identical to the T41 runner so the two candidates can be read
side by side. The addition is **criterion 5** (decisions/0018): the paired
completion-token check plus a dump of every in-scope ABSTAIN beside what the control
wrote for the same question, so the hand triage T41 had to do post-hoc is produced by
the run itself.

Adopt/reject rule and all metrics were fixed in decisions/0018 before this ran.

    python scripts/run_t41b_suffix_field.py
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
from mcrag.eval.significance import paired_bootstrap_comparison  # noqa: E402
from mcrag.eval.stats import bootstrap_ci  # noqa: E402
from mcrag.eval.tier0_scoring import score_tier0  # noqa: E402
from mcrag.generate.decision_field import ABSTAIN, parse_trailing_decision  # noqa: E402
from mcrag.generate.ollama_cloud import ContextOverflow, GenerationError, OllamaCloudGenerator  # noqa: E402
from mcrag.generate.prompting import (  # noqa: E402
    SCOPE_STRICT_SYSTEM_PROMPT,
    SUFFIX_DECISION_FIELD_SYSTEM_PROMPT,
    build_user_prompt,
)
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
from mcrag.runlog import Lock  # noqa: E402
from mcrag.service.refusal import NarrowPhraseClassifier  # noqa: E402
from mcrag.types import GoldQuestion  # noqa: E402

# Doubles as run_interleaved's per-arm expected_model dict.
MODELS: dict[str, str] = {
    "suffix_field_gemma4_31b": "gemma4:31b",
    "scope_strict_gemma4_31b_a": "gemma4:31b",
    "scope_strict_gemma4_31b_b": "gemma4:31b",
}
DECISION_ARMS = {"suffix_field_gemma4_31b"}
REFERENCE_ARM = "scope_strict_gemma4_31b_a"
NOISE_FLOOR_ARM = "scope_strict_gemma4_31b_b"
PRIMARY_ARM = "suffix_field_gemma4_31b"
PRIMARY_SLICE = "out_of_scope"
SLICES = ("single_silo", "cross_silo", "out_of_scope", "adversarial", "exact_match", "temporal", "multi_turn")

T40 = NarrowPhraseClassifier()


def build_configs() -> list[Config]:
    configs = []
    for arm, model in MODELS.items():
        configs.append(
            Config.from_dict(
                {
                    "name": "t41b-suffix-field",
                    "arm": arm,
                    "chunk": {"max_tokens": 512},
                    "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
                    "generation": {"model": model, "temperature": 0.0},
                    "eval": {"gold_path": str(GOLD_PATH), "split": "dev"},
                    "notes": (
                        f"Task 41b arm {arm}: {model}, "
                        f"{'trailing decision field' if arm in DECISION_ARMS else 'scope-strict (adopted)'} prompt, "
                        "frozen retrieval (decisions/0007), full dev split. decisions/0018."
                    ),
                }
            )
        )
    return configs


def evaluate_fn_for(search, gold_lookup, retrieved_lookup, faithfulness):
    def build(config: Config):
        model = config.generation.model
        arm = config.arm
        uses_field = arm in DECISION_ARMS
        system_prompt = SUFFIX_DECISION_FIELD_SYSTEM_PROMPT if uses_field else SCOPE_STRICT_SYSTEM_PROMPT
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
            raw = completion.text
            decision, scoreable = parse_trailing_decision(raw)

            reasoning_chars = len(completion.reasoning)
            answer_chars = len(scoreable)
            record.update(
                {
                    "model": completion.model,
                    "answer": scoreable,
                    "answer_raw": raw,
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

            # Scoring runs on `scoreable` -- the trailing line removed (decisions/0018).
            tier0 = score_tier0(
                scoreable, question.question, retrieved_urls, gold_urls,
                expects_answer=bool(question.gold),
            )
            record["tier0"] = {
                "citation_accuracy": tier0.citation_accuracy,
                "citation_validity": tier0.citation_validity,
                "refused": tier0.refused,
                "refusal_correct": tier0.refusal_correct,
                "exact_match_presence": tier0.exact_match_presence,
            }
            record.update(tier1_fields(faithfulness, scoreable, [h.chunk.text for h in found]))

            # Three channels, recorded for every arm; `shipped` is what this arm
            # would do in production. `field` is null where the arm has no field.
            field_refused = None if not uses_field or decision is None else (decision == ABSTAIN)
            t40_refused = T40.is_refusal(scoreable)
            shipped_refused = t40_refused if field_refused is None else field_refused
            expects = bool(question.gold)
            record["refusal_channels"] = {
                "field_present": bool(uses_field and decision is not None),
                "field_value": decision,
                "protocol_violation": bool(uses_field and decision is None),
                "frozen": {"refused": tier0.refused, "correct": tier0.refused != expects},
                "t40": {"refused": t40_refused, "correct": t40_refused != expects},
                "field": None if field_refused is None else {
                    "refused": field_refused, "correct": field_refused != expects
                },
                "shipped": {"refused": shipped_refused, "correct": shipped_refused != expects},
            }
            return record

        return evaluate

    return build


# ---- analysis ---------------------------------------------------------------


def _iv(interval) -> dict[str, Any]:
    return interval.to_dict()


def compare_shipped(a_records: list[dict], b_records: list[dict], label: str, slice_filter: str | None = None):
    """The primary statistic: `refusal_correct` under each arm's own detection
    channel. `compare_effect_only` cannot do this -- it reads `tier0`, which is the
    frozen channel by construction. Effect size + CI, never a p-value (dev)."""
    a = {r["query_id"]: r for r in unquarantined(a_records)}
    b = {r["query_id"]: r for r in unquarantined(b_records)}
    qids = sorted(set(a) & set(b))
    if slice_filter is not None:
        qids = [q for q in qids if a[q]["slice"] == slice_filter]
    if not qids:
        return None
    out: dict[str, Any] = {"label": label, "slice": slice_filter or "pooled", "n_questions": len(qids)}
    for channel in ("shipped", "frozen", "t40"):
        result = paired_bootstrap_comparison(
            [1.0 if a[q]["refusal_channels"][channel]["correct"] else 0.0 for q in qids],
            [1.0 if b[q]["refusal_channels"][channel]["correct"] else 0.0 for q in qids],
            split="dev", metric=f"{label}:refusal_correct[{channel}]",
        )
        out[channel] = _iv(result.interval)
    return out


def arm_report(records: list[dict]) -> dict[str, Any]:
    scored = unquarantined(records)
    oos = [r for r in scored if r["slice"] == PRIMARY_SLICE]
    answered_in_scope = [
        r for r in scored
        if r["expects_answer"] and not r["refusal_channels"]["shipped"]["refused"]
        and r.get("tier1_faithfulness") is not None
    ]
    report: dict[str, Any] = {
        "n": len(scored),
        "protocol_violations": sum(1 for r in scored if r["refusal_channels"]["protocol_violation"]),
        "field_present": sum(1 for r in scored if r["refusal_channels"]["field_present"]),
        "out_of_scope_answered": sum(
            1 for r in oos if not r["refusal_channels"]["shipped"]["refused"]
        ),
        "out_of_scope_n": len(oos),
        "field_vs_t40_disagree": sum(
            1 for r in scored
            if r["refusal_channels"]["field"] is not None
            and r["refusal_channels"]["field"]["refused"] != r["refusal_channels"]["t40"]["refused"]
        ),
    }
    for channel in ("shipped", "frozen", "t40"):
        report[f"refusal_correct[{channel}]"] = _iv(
            bootstrap_ci(
                [1.0 if r["refusal_channels"][channel]["correct"] else 0.0 for r in scored],
                statistics.mean, name="mean",
            )
        )
    if answered_in_scope:
        report["faithfulness_answered_in_scope"] = _iv(
            bootstrap_ci([r["tier1_faithfulness"] for r in answered_in_scope], statistics.mean, name="mean")
        )
    # Cost as a median, never a mean (decisions/0011).
    for field in ("completion_tokens", "wall_s"):
        values = [r[field] for r in scored if r.get(field) is not None]
        if values:
            report[f"median_{field}"] = _iv(bootstrap_ci(values, statistics.median, name="median"))
    return report


def write_triage(cand_records: list[dict], ctrl_records: list[dict], out_path: Path) -> dict[str, Any]:
    """Criterion 5's raw material (decisions/0018): every in-scope question the
    candidate labelled ABSTAIN, beside what the control wrote for the same question.
    Pre-registered so the triage T41 did post-hoc is produced by the run itself.
    The *classification* of each case is still a human call, made in decisions/0018."""
    cand = {r["query_id"]: r for r in unquarantined(cand_records)}
    ctrl = {r["query_id"]: r for r in unquarantined(ctrl_records)}
    cases = [
        q for q in sorted(cand)
        if cand[q]["expects_answer"] and cand[q]["refusal_channels"]["field_value"] == ABSTAIN
    ]
    lines = [
        "# T41b: in-scope ABSTAIN triage (decisions/0018, criterion 5)",
        "",
        f"{len(cases)} of the candidate's in-scope answers carry a trailing `DECISION: ABSTAIN`. "
        "Each is shown beside what control `_a` wrote for the same question, with both "
        "token counts. Classify each by hand as: control also refused / content lost / "
        "label disagrees with its own body.",
    ]
    for q in cases:
        c, k = cand[q], ctrl[q]
        lines += [
            "", f"## {q} ({c['slice']})", "",
            f"- candidate ({c['completion_tokens']} tokens, t40_refusal={T40.is_refusal(c['answer'])}):",
            f"  > {c['answer'][:1200]}",
            f"- control `_a` ({k['completion_tokens']} tokens, t40_refusal={T40.is_refusal(k['answer'])}):",
            f"  > {k['answer'][:1200]}",
        ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return {"n_in_scope_abstain": len(cases), "case_ids": cases, "path": str(out_path)}


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
        "pre_registration": "decisions/0018-suffix-decision-field.md",
    }
    analysis["primary_pooled"] = compare_shipped(records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t41b")
    analysis["primary_out_of_scope"] = compare_shipped(
        records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t41b", slice_filter=PRIMARY_SLICE
    )
    analysis["noise_floor_pooled"] = compare_shipped(
        records[REFERENCE_ARM], records[NOISE_FLOOR_ARM], "noise_floor_t41b"
    )
    analysis["noise_floor_out_of_scope"] = compare_shipped(
        records[REFERENCE_ARM], records[NOISE_FLOOR_ARM], "noise_floor_t41b", slice_filter=PRIMARY_SLICE
    )
    analysis["primary_by_slice"] = {
        s: compare_shipped(records[REFERENCE_ARM], records[PRIMARY_ARM], "primary_t41b", slice_filter=s)
        for s in SLICES
    }
    # Collateral: the standard frozen-channel comparison, same shape as every prior arm.
    analysis["collateral_pooled"] = compare_effect_only(
        records[REFERENCE_ARM], records[PRIMARY_ARM], "collateral_t41b", split="dev"
    )
    analysis["collateral_noise_floor"] = compare_effect_only(
        records[REFERENCE_ARM], records[NOISE_FLOOR_ARM], "collateral_noise_floor", split="dev"
    )
    analysis["per_arm"] = {arm: arm_report(recs) for arm, recs in records.items()}
    analysis["triage"] = write_triage(
        records[PRIMARY_ARM], records[REFERENCE_ARM], Path("docs/t41b_abstain_triage.md")
    )
    analysis["per_arm_summary"] = {arm: summarize(recs) for arm, recs in records.items()}

    out_path = Path("runs/t41b_suffix_field_analysis.json")
    out_path.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")

    def fmt(iv):
        if iv is None:
            return "--"
        v = iv.get("interval", iv)
        return f"{v['value']:+.3f} [{v['ci_low']:+.3f}, {v['ci_high']:+.3f}] (n={v['n']})"

    print(f"\nrun dirs: {[str(rd.path) for rd in results.values()]}")

    for title, key in (
        ("primary, pooled dev (candidate - control)", "primary_pooled"),
        ("primary, out_of_scope slice", "primary_out_of_scope"),
        ("noise floor, pooled dev (control_b - control_a)", "noise_floor_pooled"),
        ("noise floor, out_of_scope slice", "noise_floor_out_of_scope"),
    ):
        block = analysis[key]
        print(f"\n== {title} ==")
        if block is None:
            print("  --")
            continue
        for channel in ("shipped", "frozen", "t40"):
            print(f"  refusal_correct[{channel:<7}] {fmt(block[channel])}")

    print("\n== per arm ==")
    for arm, rep in analysis["per_arm"].items():
        print(f"\n  {arm}")
        print(f"    protocol violations   {rep['protocol_violations']}/{rep['n']}")
        print(f"    out_of_scope answered {rep['out_of_scope_answered']}/{rep['out_of_scope_n']}")
        print(f"    field vs t40 disagree {rep['field_vs_t40_disagree']}")
        for k in ("refusal_correct[shipped]", "refusal_correct[frozen]",
                  "faithfulness_answered_in_scope", "median_completion_tokens", "median_wall_s"):
            if k in rep:
                print(f"    {k:<32} {fmt(rep[k])}")

    print("\n== criterion 5: paired cost vs the control (decisions/0018) ==")
    print(f"  completion_tokens {fmt(analysis['collateral_pooled']['b_minus_a']['completion_tokens'])}")
    print(f"  noise floor       {fmt(analysis['collateral_noise_floor']['b_minus_a']['completion_tokens'])}")
    print(f"  in-scope ABSTAIN cases to triage: {analysis['triage']['n_in_scope_abstain']} "
          f"-> {analysis['triage']['path']}")
    print(f"     {', '.join(analysis['triage']['case_ids']) or '(none)'}")

    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
