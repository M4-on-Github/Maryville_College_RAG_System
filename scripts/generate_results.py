"""Regenerate `RESULTS.md` from `runs/`. Never hand-edit the output.

    python scripts/generate_results.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.eval.results_table import write_results_md  # noqa: E402


def main() -> int:
    markdown = write_results_md()
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
