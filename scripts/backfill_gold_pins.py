"""Backfill content-hash pins for all gold questions (Task 35).

Run this once to initialize pins on the gold set from the current corpus:

    python scripts/backfill_gold_pins.py

This is idempotent: running it twice changes nothing (existing pins are not
overwritten). Reports any refs that could not be resolved.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.eval.gold import (
    backfill_pins,
    load_chunks,
    load_gold_questions,
    write_gold_questions,
)


def main() -> int:
    gold_path = Path("data/gold/gold_v1.jsonl")
    chunks_path = Path("corpus/chunks.jsonl")

    if not gold_path.exists():
        print(f"Error: {gold_path} not found", file=sys.stderr)
        return 1
    if not chunks_path.exists():
        print(f"Error: {chunks_path} not found", file=sys.stderr)
        return 1

    print("Loading gold questions...", file=sys.stderr)
    questions = load_gold_questions(gold_path)
    print(f"  Loaded {len(questions)} questions", file=sys.stderr)

    print("Loading chunks...", file=sys.stderr)
    chunks = load_chunks(chunks_path)
    print(f"  Loaded {len(chunks)} chunks", file=sys.stderr)

    print("Backfilling pins...", file=sys.stderr)
    updated, unresolved_qids = backfill_pins(questions, chunks)

    if unresolved_qids:
        print(
            f"Warning: {len(unresolved_qids)} questions have unresolved refs:",
            file=sys.stderr,
        )
        for qid in unresolved_qids:
            print(f"  {qid}", file=sys.stderr)

    print("Writing updated gold set...", file=sys.stderr)
    write_gold_questions(gold_path, updated)
    print(f"  Wrote {len(updated)} questions", file=sys.stderr)
    print("Done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
