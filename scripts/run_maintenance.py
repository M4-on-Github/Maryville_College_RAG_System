"""One scheduled job that re-runs crawl → extract → manifest → incremental reindex,
and shouts when any of the four decay modes fires. Silence is the success condition.

Exit codes:
- 0: ingest chain completed and no alert fired (silence)
- 1: ingest chain failed (exception or non-zero return from a stage)
- 2: ingest chain completed but one or more alerts fired

An alert is a written record plus a non-zero exit, not a notification service.
Every run appends a dated row to the maintenance log; no row is ever deleted
or edited.

    python scripts/run_maintenance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.maintain.run import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
