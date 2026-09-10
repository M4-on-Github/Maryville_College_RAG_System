"""One run directory captures one result with its provenance.

Layout, per PLAN and tasks/plan.md Task 1::

    runs/<timestamp>_<confighash>/
        config.yaml       the exact config, re-loadable
        metrics.json      the headline numbers
        per_query.jsonl   one record per question, appended as it completes
        corpus.lock       which corpus snapshot this ran against
        model.lock        which model weights answered
        split.lock        which train/dev/test partition was in force
        notes.md          free text

The three locks are what separate a reproducible claim from a remembered one.
A metric without them is a number someone once saw.

``per_query.jsonl`` is appended and flushed per record, so a killed run leaves a
file that parses line by line and can be resumed from. That is not a nicety:
generation runs are quota-metered, and a crash that costs the whole pass costs
real budget.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcrag.config import Config

LOCK_NAMES = ("corpus.lock", "model.lock", "split.lock")


@dataclass(frozen=True, slots=True)
class Lock:
    """A provenance stamp. ``digest`` is what changed-or-not is decided on."""

    kind: str
    digest: str
    detail: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {"kind": self.kind, "digest": self.digest, "detail": self.detail},
            sort_keys=True,
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> Lock:
        raw = json.loads(text)
        return cls(kind=raw["kind"], digest=raw["digest"], detail=raw.get("detail", {}))


class RunDir:
    """A single run's on-disk home.

    Open it, append per-query records as they complete, write metrics at the end.
    Re-opening an existing run directory resumes rather than truncates.
    """

    def __init__(self, path: Path, config: Config) -> None:
        self.path = Path(path)
        self.config = config
        self._per_query = self.path / "per_query.jsonl"
        self._handle = None

    # ---- construction --------------------------------------------------

    @classmethod
    def create(
        cls,
        config: Config,
        root: str | Path = "runs",
        timestamp: datetime | None = None,
    ) -> RunDir:
        ts = (timestamp or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
        path = Path(root) / f"{ts}_{config.config_hash}"
        path.mkdir(parents=True, exist_ok=True)
        run = cls(path, config)
        (path / "config.yaml").write_text(config.to_yaml(), encoding="utf-8")
        notes = path / "notes.md"
        if not notes.exists():
            notes.write_text(
                f"# {config.name} / arm: {config.arm}\n\n{config.notes}\n", encoding="utf-8"
            )
        run._per_query.touch()
        return run

    @classmethod
    def open(cls, path: str | Path) -> RunDir:
        """Reopen an existing run to resume it."""
        path = Path(path)
        config = Config.from_yaml(path / "config.yaml")
        return cls(path, config)

    # ---- provenance ----------------------------------------------------

    def write_lock(self, lock: Lock) -> None:
        name = f"{lock.kind}.lock"
        if name not in LOCK_NAMES:
            raise ValueError(f"unknown lock kind {lock.kind!r}; expected one of {LOCK_NAMES}")
        (self.path / name).write_text(lock.to_json(), encoding="utf-8")

    def read_lock(self, kind: str) -> Lock | None:
        p = self.path / f"{kind}.lock"
        return Lock.from_json(p.read_text(encoding="utf-8")) if p.exists() else None

    @property
    def missing_locks(self) -> list[str]:
        """Locks not yet written. A complete run has none."""
        return [n for n in LOCK_NAMES if not (self.path / n).exists()]

    # ---- per-query stream ----------------------------------------------

    def append(self, record: dict[str, Any]) -> None:
        """Append one completed question. Flushed and fsynced before returning.

        The fsync is deliberate. Buffered writes are exactly how a killed run
        loses the last several results it actually paid for.
        """
        if "query_id" not in record:
            raise ValueError("per-query record must carry a 'query_id' to be resumable")
        if self._handle is None:
            self._handle = self._per_query.open("a", encoding="utf-8", buffering=1)
        self._handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> RunDir:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def records(self) -> Iterator[dict[str, Any]]:
        """Parse the per-query file line by line, tolerating a torn last line.

        A truncated final line means the process died mid-write. That record is
        dropped and the rest stand; the alternative -- refusing to parse the
        file -- throws away results that were correctly written and paid for.
        """
        if not self._per_query.exists():
            return
        with self._per_query.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def completed_ids(self) -> set[str]:
        """Query ids already done. Subtract from the work queue to resume."""
        return {r["query_id"] for r in self.records() if "query_id" in r}

    # ---- results -------------------------------------------------------

    def write_metrics(self, metrics: dict[str, Any]) -> None:
        """Write the headline numbers.

        Guarded, not merely documented: every metric must arrive as a
        ``(value, ci_low, ci_high, n)`` shape. PLAN 4f forbids a bare float
        anywhere in the harness, because a point estimate with no n is what
        turns a 28-question slice into a confident claim.
        """
        _check_interval_shape(metrics)
        (self.path / "metrics.json").write_text(
            json.dumps(metrics, sort_keys=True, indent=2, default=str), encoding="utf-8"
        )

    def read_metrics(self) -> dict[str, Any]:
        p = self.path / "metrics.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class MetricShapeError(ValueError):
    """Raised when a metric is reported without its n and interval."""


_REQUIRED_METRIC_KEYS = {"value", "ci_low", "ci_high", "n"}


def _check_interval_shape(metrics: dict[str, Any], where: str = "metrics") -> None:
    for key, value in metrics.items():
        path = f"{where}.{key}"
        if isinstance(value, dict):
            if _REQUIRED_METRIC_KEYS & set(value):
                missing = _REQUIRED_METRIC_KEYS - set(value)
                if missing:
                    raise MetricShapeError(
                        f"{path}: metric is missing {sorted(missing)}; "
                        "every reported number carries n and a 95% interval"
                    )
            else:
                _check_interval_shape(value, where=path)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            raise MetricShapeError(
                f"{path}: bare number {value!r} is not a reportable metric; "
                "use {'value','ci_low','ci_high','n'}"
            )
