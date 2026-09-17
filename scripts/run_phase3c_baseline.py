"""Task 20: Phase 3c generation baseline -- the naive prompt (no forced
citations, no abstention threshold) run over the *full* dev split, against
the retrieval config Task 18 froze (`decisions/0007`: boilerplate off,
FixedSizeChunker(512), RRF fusion on, reranker off, silo boost off).

This is the control condition ablations #6, #8, #9 and #10 (Tasks 21-22)
all get compared against, and the first task since Task 16 to spend real
generation quota (dev = 60 questions, ~2 min wall-clock, trivial against the
budget in docs/quota-calibration.md).

    python scripts/run_phase3c_baseline.py

Runs the baseline once (the canonical, committed control run), then a
second, throwaway pass into `runs/phase3c_repro_check/` to satisfy this
task's verification step -- "reproducible across two runs at temperature
0" -- and reports the exact-match rate between the two rather than assuming
determinism, since a hosted model's determinism at temp 0 is a claim to
check, not a guarantee.

Retrieved passages go into the prompt whole, and multi-turn questions get
their prior user turns answered live and passed as chat history; retrieval
sees only the current turn (decisions/0008).

Scored with Task 19's ladder: Tier 0 (free, always) and Tier 1 NLI
faithfulness (free, local, always; interpreted only as paired arm
differences -- it is not validated against human scores, decisions/0008). Tier 3 is deliberately NOT run here --
per decisions/0006, that calibration is spent once this baseline exists to
calibrate against, as a separate, explicit step, not bundled silently into
every baseline run.
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
from mcrag.eval.nli_faithfulness import SCORER_VERSION, NLIFaithfulnessScorer  # noqa: E402
from mcrag.eval.retrieval_metrics import all_golds_retrieved_at_k, mrr, ndcg_at_k, recall_at_k  # noqa: E402
from mcrag.eval.significance import assert_reportable, paired_bootstrap_comparison  # noqa: E402
from mcrag.eval.stats import bootstrap_ci  # noqa: E402
from mcrag.eval.tier0_scoring import score_tier0  # noqa: E402
from mcrag.generate.ollama_cloud import ContextOverflow, GenerationError, OllamaCloudGenerator  # noqa: E402
from mcrag.generate.prompting import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.bm25 import BM25Index  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.retrieval.fusion import RRFFuser  # noqa: E402
from mcrag.retrieval.literal import LiteralIndex  # noqa: E402
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
REPRO_REPORT_PATH = Path("runs/phase3c_reproducibility.json")


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


def build_search(dense, bm25, literal, chunk_lookup: dict[str, Chunk]):
    fuser = RRFFuser()

    def search(query: str) -> list[Hit]:
        leg_results = [
            dense.search(query, CANDIDATE_K),
            bm25.search(query, CANDIDATE_K),
            literal.search(query, CANDIDATE_K),
        ]
        hits = fuser.fuse(leg_results, CANDIDATE_K)
        return [replace(h, chunk=chunk_lookup.get(h.chunk_id)) if h.chunk is None else h for h in hits]

    return search


def tier1_fields(faithfulness: NLIFaithfulnessScorer, answer: str, context: list[str]) -> dict[str, Any]:
    result = faithfulness.score_answer(answer, context)
    return {
        "tier1_faithfulness": result.value,
        "tier1_n_claims": result.n_claims,
        "tier1_n_pairs": result.n_pairs,
        "tier1_n_truncated_pairs": result.n_truncated_pairs,
        "tier1_scorer_version": SCORER_VERSION,
    }


def _as_user_turn(text: str) -> str:
    # Prior user turns keep the <question> delimiters the system prompt names
    # as the only instruction span -- the model saw them that way when it
    # answered them, and nothing else in the history is an instruction.
    return f"<question>\n{text}\n</question>"


def run_prior_turns(search, generator, user_turns: tuple[str, ...]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Answer each earlier user turn live, in order, the way a chat session would.

    `GoldQuestion.history` scripts only the user's side: assistant turns are the
    pipeline's own answers, so the final turn is evaluated against the history
    this pipeline would actually have produced. Each prior turn retrieves on its
    own text only, same policy as the final turn.
    """
    messages: list[dict[str, str]] = []
    transcript: list[dict[str, str]] = []
    for turn in user_turns:
        found = [h for h in search(turn)[:K] if h.chunk is not None]
        prompt = build_user_prompt(turn, [h.chunk for h in found], passage_chars=None)
        completion = generator.complete(prompt, system=SYSTEM_PROMPT, history=messages)
        messages += [
            {"role": "user", "content": _as_user_turn(turn)},
            {"role": "assistant", "content": completion.text},
        ]
        transcript.append({"user": turn, "assistant": completion.text})
    return messages, transcript


def evaluate_fn_for(search, generator, faithfulness, gold_lookup, retrieved_lookup):
    def evaluate(question: GoldQuestion) -> dict[str, Any]:
        # decisions/0008, decision 3: prior turns go to the prompt, never to
        # retrieval -- rewriting a follow-up into a standalone query is
        # ablation #6's job, so the control must not do it.
        history, transcript = run_prior_turns(search, generator, question.history)
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
            retrieved_ids = [h.chunk_id for h in hits]
            canon = canonicalize_retrieved(retrieved_ids, retrieved_lookup, question.gold, gold_lookup)
            record["retrieval"] = {
                "recall@k": recall_at_k(question.gold, canon, K),
                "mrr": mrr(question.gold, canon, K),
                "ndcg@k": ndcg_at_k(question.gold, canon, K),
                "all_golds_retrieved@k": all_golds_retrieved_at_k(question.gold, canon, K),
            }

        prompt = build_user_prompt(question.question, [h.chunk for h in found], passage_chars=None)
        prompt_tokens = generator.estimator.estimate(
            "\n".join([SYSTEM_PROMPT, *(m["content"] for m in history), prompt])
        )
        completion = generator.complete(prompt, system=SYSTEM_PROMPT, history=history)
        record.update(
            {
                "history_transcript": transcript,
                "answer": completion.text,
                "finish_reason": completion.finish_reason,
                "prompt_tokens_estimated": prompt_tokens,
                "prompt_tokens_server": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
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


def _mean_ci(values: list[float]) -> dict[str, Any]:
    return bootstrap_ci(values, statistics.mean, seed=42, name="mean").to_dict()


def answered_faithfulness(record: dict[str, Any]) -> float | None:
    """Faithfulness counts answers only. PLAN Sec 4 scores a refusal as R,
    separately, and "the passages don't mention X" is never entailed by the
    passages -- averaged in, every refusal would count as a fully unfaithful
    answer, and an arm that refuses more would look less grounded for it."""
    if record["tier0"]["refused"]:
        return None
    return record.get("tier1_faithfulness")


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "run": {
            "n_total": str(len(records)),
            # Stringified: the metric-shape guard rejects bare numbers, and this
            # is a diagnostic count, not a reportable metric. Must be "0".
            "tier1_truncated_pairs": str(sum(r.get("tier1_n_truncated_pairs", 0) for r in records)),
            "tier1_scorer_versions": ",".join(
                sorted({str(r.get("tier1_scorer_version", "unversioned")) for r in records})
            ),
        }
    }

    # Per slice: the adversarial slice's `refusal_correct` is known-coarse
    # (gold refs exist, yet refusing a false premise is often the right call),
    # so a pooled number alone would hide exactly where the heuristic is weakest.
    by_slice: dict[str, Any] = {}
    for slice_name in sorted({r["slice"] for r in records}):
        group = [r for r in records if r["slice"] == slice_name]
        entry = {"refusal_correct": _mean_ci([1.0 if r["tier0"]["refusal_correct"] else 0.0 for r in group])}
        faith = [f for f in map(answered_faithfulness, group) if f is not None]
        if faith:
            entry["faithfulness"] = _mean_ci(faith)
        by_slice[slice_name] = entry
    summary["by_slice"] = by_slice

    refusal_correct = [1.0 if r["tier0"]["refusal_correct"] else 0.0 for r in records]
    summary["refusal_correct"] = bootstrap_ci(refusal_correct, statistics.mean, seed=42, name="mean").to_dict()

    for field in ("citation_accuracy", "citation_validity", "exact_match_presence"):
        values = [r["tier0"][field] for r in records if r["tier0"][field] is not None]
        if values:
            summary[field] = bootstrap_ci(values, statistics.mean, seed=42, name="mean").to_dict()

    faith_values = [f for f in map(answered_faithfulness, records) if f is not None]
    if faith_values:
        summary["faithfulness"] = _mean_ci(faith_values)
    summary["refusal_rate"] = _mean_ci([1.0 if r["tier0"]["refused"] else 0.0 for r in records])

    answerable = [r for r in records if r["expects_answer"]]
    for metric in ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k"):
        values = [r["retrieval"][metric] for r in answerable if "retrieval" in r]
        if values:
            summary[metric] = bootstrap_ci(values, statistics.mean, seed=42, name="mean").to_dict()

    return summary


def run_baseline(arm: str, root: str | Path, questions, gold_lookup, retrieved_lookup) -> RunDir:
    chunks = load_chunks(CHUNKS_PATH)
    chunk_lookup = {c.chunk_id: c for c in chunks}
    embedder = BgeEmbedder()
    dense = DenseIndex(
        db_path=INDEX_DIR, embedder=embedder,
        cache=EmbeddingCache(INDEX_DIR.parent / f"{INDEX_DIR.name}_cache.jsonl"), model_name=MODEL_NAME,
    )
    bm25 = BM25Index(); bm25.build(chunks)
    literal = LiteralIndex(); literal.build(chunks)
    search = build_search(dense, bm25, literal, chunk_lookup)

    generator = OllamaCloudGenerator(temperature=0.0)
    faithfulness = NLIFaithfulnessScorer()

    config = Config.from_dict(
        {
            "name": "phase3c-generation-baseline",
            "arm": arm,
            "chunk": {"max_tokens": 512},
            "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
            "generation": {"model": generator.model, "temperature": 0.0},
            "eval": {"gold_path": str(GOLD_PATH), "split": "dev"},
            "notes": (
                "Task 20 Phase 3c control: naive prompt, no forced citations, "
                "no abstention threshold, frozen retrieval config (decisions/0007), "
                "full dev split, scored with the Task 19 ladder (Tier 0 + Tier 1). "
                "Retrieved passages sent whole (no per-passage character cut). "
                "Multi-turn: prior user turns answered live and passed to the prompt "
                "as chat history; retrieval sees only the current turn (decisions/0008)."
            ),
        }
    )
    run_dir = run_arm(
        config, questions,
        evaluate_fn_for(search, generator, faithfulness, gold_lookup, retrieved_lookup),
        summarize, root=root, quota_errors=(GenerationError, ContextOverflow),
    )
    run_dir.write_lock(Lock(kind="corpus", digest="bp_off+fixed512", detail={"chunks_path": str(CHUNKS_PATH)}))
    run_dir.write_lock(Lock(kind="model", digest=f"{MODEL_NAME}+{generator.model}", detail={"generator": generator.model}))
    split_lock = load_split_lock(SPLIT_LOCK_PATH)
    run_dir.write_lock(Lock(kind="split", digest=split_lock["split_hash"], detail={"split": "dev"}))
    return run_dir


def compare_reproducibility(canonical: RunDir, repro: RunDir) -> dict[str, Any]:
    """Two runs of one config: a null arm. Their difference is the noise floor.

    Exact text identity is reported, but it isn't the bar a control condition
    has to clear -- metric agreement is. Dev split, so paired intervals only,
    never a p-value (decisions/0006).
    """
    a = {r["query_id"]: r for r in canonical.records()}
    b = {r["query_id"]: r for r in repro.records()}
    qids = sorted(set(a) & set(b))

    def agree(field_fn) -> dict[str, Any]:
        return _mean_ci([1.0 if field_fn(a[q]) == field_fn(b[q]) else 0.0 for q in qids])

    def paired(value_fn, metric: str) -> dict[str, Any]:
        both = [q for q in qids if value_fn(a[q]) is not None and value_fn(b[q]) is not None]
        result = assert_reportable(
            paired_bootstrap_comparison(
                [float(value_fn(a[q])) for q in both], [float(value_fn(b[q])) for q in both],
                split="dev", metric=metric,
            )
        )
        return result.interval.to_dict()

    return {
        "n_questions": str(len(qids)),
        "exact_text_match": _mean_ci([1.0 if a[q]["answer"] == b[q]["answer"] else 0.0 for q in qids]),
        "agreement": {
            "refused": agree(lambda r: r["tier0"]["refused"]),
            "refusal_correct": agree(lambda r: r["tier0"]["refusal_correct"]),
            "cites_a_url": agree(lambda r: r["tier0"]["citation_accuracy"] is not None),
        },
        "run2_minus_run1": {
            "refusal_correct": paired(lambda r: 1.0 if r["tier0"]["refusal_correct"] else 0.0, "refusal_correct"),
            "faithfulness": paired(answered_faithfulness, "faithfulness"),
        },
    }


def main() -> int:
    dev_questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "dev"]
    gold_lookup = {c.chunk_id: c for c in load_chunks(GOLD_CHUNKS_PATH)}
    retrieved_lookup = {c.chunk_id: c for c in load_chunks(CHUNKS_PATH)}
    print(f"{len(dev_questions)} dev questions ({sum(1 for q in dev_questions if q.gold)} answerable)")

    print("\n== canonical baseline run ==")
    canonical = run_baseline("phase3c-baseline", "runs", dev_questions, gold_lookup, retrieved_lookup)
    print(f"run dir: {canonical.path}")
    for k, v in canonical.read_metrics().items():
        if isinstance(v, dict) and "value" in v:
            print(f"  {k}: {v['value']:.3f} [{v['ci_low']:.3f}, {v['ci_high']:.3f}] (n={v['n']})")

    print("\n== reproducibility check: second run at temperature 0 ==")
    repro = run_baseline(
        "phase3c-baseline-repro-check", "runs/phase3c_repro_check", dev_questions, gold_lookup, retrieved_lookup
    )
    report = compare_reproducibility(canonical, repro)
    REPRO_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {REPRO_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
