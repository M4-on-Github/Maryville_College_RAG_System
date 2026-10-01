"""Regenerate `RESULTS.md` from `runs/`. Never hand-edit the output.

Task 36: also publishes the live corpus.lock as data/maintenance/published_corpus.lock
so the trigger can later compare it against the current state.

    python scripts/generate_results.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.eval.results_table import write_results_md  # noqa: E402


def main() -> int:
    markdown = write_results_md(
        factorial_summary_path="runs/phase4_free_factorial_summary.json"
    )
    print(markdown)

    # Task 36: Publish the corpus.lock (D3)
    live_lock = Path("indexes/corpus.lock")
    published_lock = Path("data/maintenance/published_corpus.lock")

    if live_lock.exists():
        published_lock.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live_lock, published_lock)
        print(f"Published corpus.lock to {published_lock}")
    else:
        print(f"Warning: {live_lock} does not exist; did not publish a lock.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
