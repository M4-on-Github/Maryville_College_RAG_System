"""Task 36: deciding when the published numbers stop being true.

Two conditions retire a published result: the corpus moved more than
`CHANGE_RATIO_CEILING` since the snapshot `RESULTS.md` was generated against,
or a T34 alert is open. This module measures both and returns a
`TriggerDecision`; `scripts/run_rerun_trigger.py` turns that into an exit code
and, when it fired, a re-run of the frozen Checkpoint-E config.

The one rule that shapes everything here: a condition nobody could measure is
`undetermined`, never a quiet pass. `decisions/0020` and `decisions/0021`
record what went wrong the two times that rule was broken -- a stale count and
three alerts that each reported "nothing wrong" when the truth was "nobody
looked". A trigger is the same shape of thing: its normal output is silence,
so silence has to be earned rather than defaulted to.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# A published result survives a corpus change of up to this fraction. Fires on
# strictly greater, matching VOLUME_DRIFT_FRACTION in alerts.py.
CHANGE_RATIO_CEILING = 0.10

# changed_urls is a sample for a human reading the log; detail carries the
# count. The cap exists so one bad crawl cannot write a 4000-URL JSONL row.
CHANGED_URL_SAMPLE_CAP = 50


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    """Why the published numbers do or do not still stand.

    `fires` is True only when a condition was *measured* and met. Firing
    spends generation quota, and the standing rule is that quota is spent on
    measured effects, so an unmeasurable condition never fires on suspicion.

    `undetermined` is the other half of that rule: one sentence per condition
    that could not be established. It does not set `fires`, and it does not
    pass silently either -- the script exits 3 on it, which is neither "the
    numbers stand" nor "re-run them" but "a human has to look". A decision can
    carry both: an open alert fires while a missing published lock stays
    undetermined, and that case exits 2 and reports both.
    """

    fires: bool
    undetermined: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    change_ratio: float | None = None
    changed_urls: tuple[str, ...] = ()
    alerts_open: bool | None = None
    published_snapshot_hash: str | None = None
    live_snapshot_hash: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _read_lock(path: Path, label: str) -> tuple[dict[str, str] | None, str | None, str | None]:
    """Read one corpus.lock once. Returns (urls, snapshot_hash, problem).

    `problem` is a human sentence and is non-None exactly when `urls` is None.
    A missing file and an unparseable one are reported as different problems:
    both leave the ratio undetermined, but only one of them means nothing was
    ever published, and the log row is the only thing a reader gets.
    """
    if not path.exists():
        return None, None, f"The {label} corpus.lock ({path}) does not exist."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, f"The {label} corpus.lock ({path}) could not be read: {exc}."
    if not isinstance(data, dict) or "urls" not in data:
        return None, None, f"The {label} corpus.lock ({path}) carries no url map."
    urls = data["urls"]
    if not isinstance(urls, dict):
        return None, None, f"The {label} corpus.lock ({path}) has a non-mapping url map."
    return urls, data.get("snapshot_hash"), None


def _compare_locks(
    published_urls: dict[str, str], live_urls: dict[str, str]
) -> tuple[float | None, dict[str, Any], tuple[str, ...], str | None]:
    """Compare two url->content_hash maps.

    Changed = modified (hash differs) + removed (published, now absent) +
    added (present now, not published). Added pages belong in the numerator
    because new content changes what retrieval returns. The denominator is the
    *published* url count: the question is how much of what the numbers were
    measured on has moved.
    """
    published_set = set(published_urls)
    live_set = set(live_urls)

    added = live_set - published_set
    removed = published_set - live_set
    modified = {url for url in published_set & live_set if published_urls[url] != live_urls[url]}

    changed = added | removed | modified
    detail: dict[str, Any] = {
        # The true count, not len(sample): the sample is capped at 50 and a
        # capped count would under-report exactly when the news is worst.
        "changed_count": len(changed),
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_count": len(modified),
        "published_url_count": len(published_urls),
        "live_url_count": len(live_urls),
    }
    sample = tuple(sorted(changed)[:CHANGED_URL_SAMPLE_CAP])

    if not published_urls:
        # Zero published urls is not a zero change rate, it is no denominator.
        return (
            None,
            detail,
            sample,
            "The published corpus.lock has no urls; the change ratio is undefined.",
        )

    return len(changed) / len(published_urls), detail, sample, None


def _read_last_maintenance_log(log_path: Path) -> dict[str, Any] | None:
    """The last row of the T34 maintenance log, or None if there is not one."""
    if not log_path.exists():
        return None
    rows = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return None
    try:
        row = json.loads(rows[-1])
    except json.JSONDecodeError:
        return None
    return row if isinstance(row, dict) else None


def _alerts_open(log_path: Path) -> tuple[bool | None, str | None]:
    """Is a T34 alert open? Three-valued; returns (answer, problem).

    `None` is the answer whenever the alerts did not run or the row does not
    say. Specifically: no log, an empty log, an exit-1 row (the ingest chain
    died, so the four checks never ran), or a row whose exit code is missing
    or is not one T34 writes. "No alert is open" is a claim about four checks
    having run and found nothing, and none of those cases support it.
    """
    row = _read_last_maintenance_log(log_path)
    if row is None:
        return None, (
            f"The maintenance log ({log_path}) is missing, empty, or unreadable; "
            "alert status is unknown."
        )

    exit_code = row.get("exit_code")
    run_id = row.get("run_id", "?")

    if exit_code == 1:
        return None, (
            f"The last maintenance run ({run_id}) exited 1: the ingest chain failed, "
            "so the four alert checks never ran and no alert status was established."
        )
    if exit_code not in (0, 2):
        return None, (
            f"The last maintenance run ({run_id}) has exit code {exit_code!r}, which is "
            "not one this job writes; alert status is unknown."
        )

    alerts = row.get("alerts")
    if not isinstance(alerts, list):
        return None, (
            f"The last maintenance run ({run_id}) carries no alert list; "
            "alert status is unknown."
        )

    fired = [a.get("name", "?") for a in alerts if isinstance(a, dict) and a.get("fired")]
    if exit_code == 2 and not fired:
        # T34 exits 2 only when something fired. Disagreement means the row is
        # not trustworthy, which is not the same as nothing being wrong.
        return None, (
            f"The last maintenance run ({run_id}) exited 2 but lists no fired alert; "
            "the row disagrees with itself."
        )
    return bool(fired), None


def compute_trigger_decision(
    published_lock_path: Path,
    live_lock_path: Path,
    maintenance_log_path: Path,
) -> TriggerDecision:
    """Measure both conditions and say what follows.

    Both conditions are evaluated whatever the other one does: an undetermined
    corpus ratio must not stop the alert check from firing, and a firing alert
    must not hide the fact that the ratio could not be measured.
    """
    undetermined: list[str] = []
    reasons: list[str] = []
    fires = False

    published_urls, published_hash, published_problem = _read_lock(
        published_lock_path, "published"
    )
    live_urls, live_hash, live_problem = _read_lock(live_lock_path, "live")

    change_ratio: float | None = None
    changed_urls: tuple[str, ...] = ()
    # None, not 0: a lock nobody could read has an unknown url count, and a
    # `0` here would read as an empty corpus to anyone scanning the log.
    detail: dict[str, Any] = {
        "changed_count": None,
        "added_count": None,
        "removed_count": None,
        "modified_count": None,
        "published_url_count": None if published_urls is None else len(published_urls),
        "live_url_count": None if live_urls is None else len(live_urls),
    }

    if published_problem is not None:
        undetermined.append(published_problem)
    if live_problem is not None:
        undetermined.append(live_problem)

    if published_urls is not None and live_urls is not None:
        change_ratio, detail, changed_urls, ratio_problem = _compare_locks(
            published_urls, live_urls
        )
        if ratio_problem is not None:
            undetermined.append(ratio_problem)
        elif change_ratio is not None and change_ratio > CHANGE_RATIO_CEILING:
            fires = True
            reasons.append(
                f"The corpus has changed by {change_ratio:.1%} of the "
                f"{detail['published_url_count']} published pages "
                f"({detail['modified_count']} modified, {detail['added_count']} added, "
                f"{detail['removed_count']} removed), over the "
                f"{CHANGE_RATIO_CEILING:.0%} ceiling."
            )

    alerts_open, alerts_problem = _alerts_open(maintenance_log_path)
    if alerts_problem is not None:
        undetermined.append(alerts_problem)
    elif alerts_open:
        fires = True
        reasons.append("A T34 maintenance alert is open on the last run.")

    return TriggerDecision(
        fires=fires,
        undetermined=tuple(undetermined),
        reasons=tuple(reasons),
        change_ratio=change_ratio,
        changed_urls=changed_urls,
        alerts_open=alerts_open,
        published_snapshot_hash=published_hash,
        live_snapshot_hash=live_hash,
        detail=detail,
    )


def append_trigger_log(
    log_path: Path,
    evaluated_at: datetime,
    exit_code: int,
    decision: TriggerDecision,
) -> None:
    """Append one evaluation to the trigger log. Opened "a", never "w".

    Separate from `append_maintenance_log`: that row is T34's schema, and a
    reader of either file should not have to ask which kind of row this is.
    """
    # Checked before the mkdir so a rejected call leaves nothing behind.
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware; got a naive datetime")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "evaluated_at": evaluated_at.isoformat(),
        "exit_code": exit_code,
        "decision": asdict(decision),
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
