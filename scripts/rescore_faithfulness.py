"""Re-score Tier 1 faithfulness on existing Task 20 run dirs, offline.

The first Tier 1 scorer joined all retrieved chunks into one premise and the
NLI tokenizer silently truncated it to 512 tokens (see
`mcrag/eval/nli_faithfulness.py`'s module docstring). Every answer and every
retrieved chunk id is already on disk, so correcting that costs no generation
quota: this recomputes Tier 1 from `per_query.jsonl`, keeps the old value
under `tier1_faithfulness_v1_truncated` so the correction stays auditable,
rewrites `metrics.json`, and appends a note to `notes.md`.

    python scripts/rescore_faithfulness.py runs/<run_dir> [runs/<run_dir> ...]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_phase3c_baseline import CHUNKS_PATH, load_chunks, summarize, tier1_fields  # noqa: E402

from mcrag.eval.nli_faithfulness import SCORER_VERSION, NLIFaithfulnessScorer  # noqa: E402
from mcrag.runlog import RunDir  # noqa: E402


def rescore(run_path: Path, scorer: NLIFaithfulnessScorer, texts: dict[str, str]) -> dict:
    run = RunDir.open(run_path)
    records = list(run.records())
    changed = 0
    for record in records:
        old_version = record.get("tier1_scorer_version")
        if old_version == SCORER_VERSION:
            continue
        if old_version is None:
            record.setdefault("tier1_faithfulness_v1_truncated", record.get("tier1_faithfulness"))
        else:
            record.setdefault(f"tier1_faithfulness__{old_version}", record.get("tier1_faithfulness"))
        context = [texts[r["chunk_id"]] for r in record["retrieved"] if r["chunk_id"] in texts]
        record.update(tier1_fields(scorer, record["answer"], context))
        changed += 1

    per_query = run_path / "per_query.jsonl"
    tmp = per_query.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    tmp.replace(per_query)

    metrics = summarize(records)
    run.write_metrics(metrics)
    if changed:
        with (run_path / "notes.md").open("a", encoding="utf-8") as f:
            f.write(
                f"\n\n## Tier 1 re-scored ({SCORER_VERSION})\n\n"
                f"{changed} records re-scored offline, no generation quota spent. "
                "v1 joined all retrieved chunks into one premise and the NLI tokenizer "
                "silently truncated it to 512 tokens (~20% of the context seen). v2 "
                "windowed the context but still scored Unicode-punctuation variants and "
                "attribution wrappers (\"According to X, <verbatim quote>\") as "
                "unsupported. Every prior value is kept per record, under "
                "`tier1_faithfulness_v1_truncated` or `tier1_faithfulness__<version>`.\n"
            )
    return {"run": run_path.name, "rescored": changed, "metrics": metrics}


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print(__doc__)
        return 1
    texts = {c.chunk_id: c.text for c in load_chunks(CHUNKS_PATH)}
    scorer = NLIFaithfulnessScorer()
    for path in paths:
        result = rescore(path, scorer, texts)
        m = result["metrics"]
        faith = m.get("faithfulness", {})
        print(
            f"{result['run']}: re-scored {result['rescored']} | "
            f"faithfulness {faith.get('value', float('nan')):.3f} "
            f"[{faith.get('ci_low', float('nan')):.3f}, {faith.get('ci_high', float('nan')):.3f}] "
            f"(n={faith.get('n')}) | truncated pairs: {m['run']['tier1_truncated_pairs']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
