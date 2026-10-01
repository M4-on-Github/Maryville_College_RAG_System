"""Append-only maintenance log (JSONL).

Every maintenance run appends one row to `data/maintenance/maintenance_log.jsonl`.
Rows are never edited or deleted. This design ensures an audit trail: a query
over the log can see every decision ever made, in order.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from mcrag.maintain.alerts import Alert


@dataclass(frozen=True, slots=True)
class MaintenanceLogEntry:
    """One row in the maintenance log.

    Written as JSON; the timestamp fields are ISO-8601 UTC, matching the
    pattern used in ReverificationRecord (Task 35).

    `pages_fetched` is `None` when the run does not know -- a chain that raised
    partway through fetched some unknown number, and `0` would claim it fetched
    none. `error` is set only on an exit-1 row and names what broke.
    """

    run_id: str
    started_at: str  # ISO-8601 UTC
    finished_at: str  # ISO-8601 UTC
    exit_code: int
    pages_fetched: int | None
    alerts: list[dict]  # list of asdict(alert) for all four alerts
    error: str | None = None


def append_maintenance_log(
    log_path: Path,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    exit_code: int,
    pages_fetched: int | None,
    alerts: list[Alert],
    error: str | None = None,
) -> None:
    """Append a maintenance run record to the log.

    Args:
        log_path: path to data/maintenance/maintenance_log.jsonl
        run_id: unique identifier for this run (e.g., timestamp-based)
        started_at: when the run started (datetime, UTC, timezone-aware)
        finished_at: when the run ended (datetime, UTC, timezone-aware)
        exit_code: the process exit code (0, 1, or 2)
        pages_fetched: pages fetched this run, or None when the run cannot say
        alerts: list of all four Alert records (some may have fired=False)
        error: what broke, on an exit-1 row
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Rejected rather than coerced: a naive datetime renders without an offset,
    # so a row written on a machine in another timezone would read as UTC and
    # silently misdate itself. The caller knows which clock it read.
    for label, value in (("started_at", started_at), ("finished_at", finished_at)):
        if value.tzinfo is None:
            raise ValueError(f"{label} must be timezone-aware; got a naive datetime")

    # Convert datetimes to ISO-8601 strings
    started_str = started_at.isoformat()
    finished_str = finished_at.isoformat()

    # Convert alerts to dicts
    alerts_dicts = [asdict(a) for a in alerts]

    entry = MaintenanceLogEntry(
        run_id=run_id,
        started_at=started_str,
        finished_at=finished_str,
        exit_code=exit_code,
        pages_fetched=pages_fetched,
        alerts=alerts_dicts,
        error=error,
    )

    # Append to the log (mode "a" only, never "w")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry)) + "\n")
