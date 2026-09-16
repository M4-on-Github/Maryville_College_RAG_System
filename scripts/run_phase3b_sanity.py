"""Task 16: Phase 3b end-to-end sanity check -- the risk gate before Phase 4.

Attaches the naive Ollama Cloud generator to the Phase 3a retrieval baseline
over a ~25-question stratified sample of dev, and writes a hand-scoring sheet.
This is NOT the Phase 3c generation control condition (that's the full dev
split with a settled prompt) -- it exists to answer one question before twenty
ablations get tuned against a retrieval proxy: does recall@k (or any of the
other three) actually track answer quality on this corpus?

Trivial quota (docs/quota-calibration.md: 25 full gold-set passes fit in one
five-hour session window; this spends one twenty-fifth of that).

    python scripts/run_phase3b_sanity.py

Writes a run dir under `runs/` (config/model/corpus/split locks, resumable
per_query.jsonl, metrics.json) and `docs/phase3b-sanity-review.md` -- the
blank-score sheet a human fills in by hand before the quadrant analysis
(a follow-up step, once scores exist) can run.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.eval.gold import load_gold_questions, load_split_lock  # noqa: E402
from mcrag.eval.retrieval_harness import evaluate_question  # noqa: E402
from mcrag.generate.ollama_cloud import (  # noqa: E402
    ContextOverflow,
    GenerationError,
    OllamaCloudGenerator,
)
from mcrag.generate.prompting import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from mcrag.retrieval.bge_embedder import MODEL_NAME, BgeEmbedder  # noqa: E402
from mcrag.retrieval.dense import DenseIndex  # noqa: E402
from mcrag.retrieval.embedding_cache import EmbeddingCache  # noqa: E402
from mcrag.runlog import Lock, RunDir  # noqa: E402
from mcrag.types import Chunk, GoldQuestion  # noqa: E402

K = 5
SAMPLE_N = 25
SAMPLE_SEED = 42
CORPUS_PATH = Path("corpus/extracted/documents.jsonl")
GOLD_PATH = Path("data/gold/gold_v1.jsonl")
SPLIT_LOCK_PATH = Path("data/gold/split.lock")
GOLD_CHUNKS_PATH = Path("corpus/chunks.jsonl")
BASELINE_CHUNKS_PATH = Path("corpus/baseline_chunks.jsonl")
REVIEW_PATH = Path("docs/phase3b-sanity-review.md")


def _corpus_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "absent"


def load_chunk_lookup(path: Path) -> dict[str, Chunk]:
    lookup: dict[str, Chunk] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line)
            lookup[raw["chunk_id"]] = Chunk(
                chunk_id=raw["chunk_id"],
                source_url=raw["source_url"],
                title=raw["title"],
                text=raw["text"],
                heading_path=tuple(raw["heading_path"]),
                breadcrumb=tuple(raw["breadcrumb"]),
                silo=tuple(raw["silo"]),
                content_hash=raw["content_hash"],
                crawled_at=datetime.fromisoformat(raw["crawled_at"]),
                token_count=raw["token_count"],
                catalog_year=raw.get("catalog_year"),
            )
    return lookup


def stratified_sample(
    questions: list[GoldQuestion], n: int, seed: int
) -> list[GoldQuestion]:
    """~n questions, proportional to each slice's share of `questions`.

    Largest-remainder rounding so slice quotas sum to exactly n instead of
    drifting from independent per-slice rounding; a seeded shuffle within each
    slice keeps the pick reproducible.
    """
    by_slice: dict[str, list[GoldQuestion]] = {}
    for q in questions:
        by_slice.setdefault(q.slice, []).append(q)

    total = len(questions)
    quotas: dict[str, int] = {}
    remainders: list[tuple[float, str]] = []
    for slice_name, group in by_slice.items():
        exact = n * len(group) / total
        quotas[slice_name] = int(exact)
        remainders.append((exact - int(exact), slice_name))

    shortfall = n - sum(quotas.values())
    for _, slice_name in sorted(remainders, reverse=True)[:shortfall]:
        quotas[slice_name] += 1

    picked: list[GoldQuestion] = []
    for slice_name in sorted(by_slice):
        group = sorted(by_slice[slice_name], key=lambda q: q.qid)
        rng = random.Random(f"{seed}:phase3b:{slice_name}")
        rng.shuffle(group)
        quota = min(quotas.get(slice_name, 0), len(group))
        picked.extend(group[:quota])
    return picked


def main() -> int:
    index_dir = Path("indexes")
    dense = DenseIndex(
        db_path=index_dir / "baseline_dense",
        embedder=BgeEmbedder(),
        cache=EmbeddingCache(index_dir / "baseline_embedding_cache.jsonl"),
        model_name=MODEL_NAME,
    )

    dev_questions = [q for q in load_gold_questions(GOLD_PATH) if q.split == "dev" and q.gold]
    sample = stratified_sample(dev_questions, SAMPLE_N, SAMPLE_SEED)
    print(f"{len(dev_questions)} answerable dev questions -> {len(sample)}-question stratified sample")

    gold_lookup = load_chunk_lookup(GOLD_CHUNKS_PATH)
    retrieved_lookup = load_chunk_lookup(BASELINE_CHUNKS_PATH)

    from mcrag.config import Config

    config = Config.from_dict(
        {
            "name": "phase3b-sanity-check",
            "arm": "3b-naive-generator-over-3a-retrieval",
            "chunk": {"max_tokens": 512, "overlap_ratio": 0.0},
            "retrieval": {"k": K, "legs": [{"class": "mcrag.retrieval.dense:DenseIndex"}]},
            "generation": {},
            "eval": {"gold_path": "data/gold/gold_v1.jsonl", "split": "dev"},
            "notes": (
                "Phase 3b risk gate: does a retrieval metric track answer "
                f"quality? {SAMPLE_N}-question stratified sample of dev, "
                "naive generator (no forced citations, no abstention "
                "threshold) over the Phase 3a retrieval config. Hand-scored "
                "0/1/2 in docs/phase3b-sanity-review.md, not by an LLM judge."
            ),
        }
    )

    run_dir = RunDir.create(config)
    print(f"run dir: {run_dir.path}")

    generator = OllamaCloudGenerator(
        model=config.generation.model,
        base_url=config.generation.base_url,
        num_ctx=config.generation.num_ctx,
        temperature=config.generation.temperature,
        max_tokens=config.generation.max_tokens,
    )

    run_dir.write_lock(
        Lock(
            kind="model",
            digest=f"{MODEL_NAME}+{generator.model}@{generator.base_url}",
            detail={
                "embedder": MODEL_NAME,
                "generator": generator.model,
                "base_url": generator.base_url,
                "num_ctx": generator.num_ctx,
                "temperature": generator.temperature,
            },
        )
    )
    run_dir.write_lock(
        Lock(
            kind="corpus",
            digest=_corpus_digest(CORPUS_PATH),
            detail={"corpus": CORPUS_PATH.as_posix(), "chunker": "FixedSizeChunker(512)"},
        )
    )
    split_lock = load_split_lock(SPLIT_LOCK_PATH)
    run_dir.write_lock(
        Lock(
            kind="split",
            digest=split_lock["split_hash"],
            detail={
                "split_lock": SPLIT_LOCK_PATH.as_posix(),
                "split": "dev",
                "sample_seed": SAMPLE_SEED,
                "sample_n": len(sample),
            },
        )
    )

    done = run_dir.completed_ids()
    todo = [q for q in sample if q.qid not in done]
    if done:
        print(f"resuming: {len(done)} already answered, {len(todo)} to go")

    with run_dir:
        for question in todo:
            hits = dense.search(question.question, K)
            found = [(h, retrieved_lookup[h.chunk_id]) for h in hits if h.chunk_id in retrieved_lookup]
            passages = [chunk for _, chunk in found]
            retrieval = evaluate_question(
                dense, question, K, retrieved_lookup=retrieved_lookup, gold_lookup=gold_lookup
            )
            prompt = build_user_prompt(question.question, passages)

            record: dict = {
                "query_id": question.qid,
                "slice": question.slice,
                "question": question.question,
                "retrieved": [
                    {"chunk_id": h.chunk_id, "url": p.source_url, "title": p.title}
                    for h, p in found
                ],
                "recall@k": retrieval.get("recall@k"),
                "mrr": retrieval.get("mrr"),
                "ndcg@k": retrieval.get("ndcg@k"),
                "all_golds_retrieved@k": retrieval.get("all_golds_retrieved@k"),
                "hand_score": None,
            }
            try:
                prompt_tokens = generator.estimator.estimate(prompt + SYSTEM_PROMPT)
                completion = generator.complete(prompt, system=SYSTEM_PROMPT)
                record.update(
                    {
                        "ok": True,
                        "answer": completion.text,
                        "reasoning_chars": len(completion.reasoning),
                        "finish_reason": completion.finish_reason,
                        "prompt_tokens_estimated": prompt_tokens,
                        "prompt_tokens_server": completion.usage.prompt_tokens,
                        "prompt_budget": generator.prompt_budget,
                        "num_ctx": generator.num_ctx,
                        "truncation_risk": prompt_tokens > generator.prompt_budget,
                    }
                )
            except (GenerationError, ContextOverflow) as exc:
                record.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

            run_dir.append(record)
            print(f"  {question.qid} ({question.slice}) -- {'ok' if record.get('ok') else 'FAILED'}")

    records = list(run_dir.records())
    n_truncation_risk = sum(1 for r in records if r.get("truncation_risk"))
    n_failed = sum(1 for r in records if not r.get("ok", False))
    print(f"{len(records)} answered, {n_failed} failed, {n_truncation_risk} at truncation risk")

    write_review_sheet(records)
    print(f"review sheet -> {REVIEW_PATH}")
    return 0


def write_review_sheet(records: list[dict]) -> None:
    lines = [
        "# Phase 3b sanity-check review sheet",
        "",
        f"{len(records)} questions, naive generator over the Phase 3a retrieval baseline. "
        "Hand-score each answer 0/1/2 (0 = wrong/ungrounded, 1 = partial, 2 = correct and "
        "grounded in the cited passages) -- fill in the blank after `Score:` on each entry. "
        "No LLM judge at this n (PLAN Phase 3b).",
        "",
    ]
    for r in records:
        lines.append(f"## {r['query_id']} ({r['slice']})")
        lines.append("")
        lines.append(f"**Q:** {r['question']}")
        lines.append("")
        if not r.get("ok"):
            lines.append(f"**GENERATION FAILED:** {r.get('error')}")
            lines.append("")
            continue
        lines.append(f"**A:** {r['answer']}")
        lines.append("")
        lines.append(
            f"retrieval: recall@k={r['recall@k']:.2f} mrr={r['mrr']:.2f} "
            f"ndcg@k={r['ndcg@k']:.2f} all_golds_retrieved@k={r['all_golds_retrieved@k']:.2f} "
            f"| prompt {r['prompt_tokens_server']} tok / budget {r['prompt_budget']} tok "
            f"(truncation risk: {r['truncation_risk']})"
        )
        lines.append("")
        lines.append("Retrieved:")
        for c in r["retrieved"]:
            lines.append(f"- `{c['chunk_id']}` -- {c['title']} -- <{c['url']}>")
        lines.append("")
        lines.append("Score: ___")
        lines.append("")
    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
