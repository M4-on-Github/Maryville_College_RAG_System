"""Build the blind, human-scored calibration set for the Tier 3 judge.

Dev answers only (both T22b arms' generators: gemma4:31b and gpt-oss:20b, from
decisions/0010's dev runs), so this never touches the test split. Writes
`data/calibration/{scoring_sheet.md, labels.csv, key.json, items.json}`.

    python scripts/build_judge_calibration_set.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.eval.calibration_set import sample_calibration_items, write_calibration_files  # noqa: E402

CHUNKS_PATH = Path("corpus/baseline_chunks_no_boilerplate.jsonl")
OUT_DIR = Path("data/calibration")
N_ITEMS = 50
SEED = 42
SOURCE_RUNS = {
    "gemma4:31b": Path("runs/20260917T193056Z_4bb32ea47677"),   # free_form_gemma4_31b, dev
    "gpt-oss:20b": Path("runs/20260917T193056Z_6952a305644b"),  # free_form_20b_a, dev
}


def main() -> int:
    chunks = {}
    for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        chunks[c["chunk_id"]] = c
    records = {
        model: [json.loads(l) for l in (run / "per_query.jsonl").read_text(encoding="utf-8").splitlines()]
        for model, run in SOURCE_RUNS.items()
    }
    items = sample_calibration_items(records, chunks, n=N_ITEMS, seed=SEED)
    write_calibration_files(items, OUT_DIR)
    from collections import Counter
    print(f"wrote {len(items)} items to {OUT_DIR}")
    print("by slice:", dict(Counter(i.slice for i in items)))
    print("by model:", dict(Counter(i.model for i in items)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
