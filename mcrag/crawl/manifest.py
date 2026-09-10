"""The crawl manifest: one record per URL **considered**, not per URL fetched.

A corpus that records only its successes cannot tell you what is missing from
it. When a gold question has no supporting chunk, the manifest is what separates
"never fetched", "fetched but empty", "excluded by policy" and "blocked by
robots" -- four different problems with four different fixes that look identical
from the index.

Every non-``fetched`` record carries a **class-prefixed** reason. A bare
"excluded" fails review, because it cannot be counted.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class Status(StrEnum):
    FETCHED = "fetched"
    EXCLUDED = "excluded"  # we chose not to, or robots refused
    FAILED = "failed"  # we tried and could not
    SKIPPED = "skipped"  # unchanged since last crawl


class ReasonClass(StrEnum):
    """The prefix before the colon. Counting these is the coverage report."""

    ROBOTS_DISALLOW = "robots_disallow"
    POLICY = "policy"
    HTTP_ERROR = "http_error"
    EXTRACTION_EMPTY = "extraction_empty"
    UNCHANGED_HASH = "unchanged_hash"


_VALID_PREFIXES = {str(r) for r in ReasonClass}


class ManifestError(ValueError):
    """Raised on a record that could not be audited later."""


@dataclass(frozen=True, slots=True)
class ManifestRecord:
    """One URL's fate.

    ``final_url`` differs from ``url`` when the site redirected. Both are kept:
    deduplication happens on the final URL, but the requested one is what the
    sitemap claimed, and a drift between them is itself a signal.
    """

    url: str
    source: str
    status: Status
    reason: str | None = None
    final_url: str | None = None
    http: int | None = None
    content_hash: str | None = None
    fetched_at: datetime | None = None
    bytes: int | None = None
    extracted_chars: int | None = None
    silo: tuple[str, ...] = ()
    chunks: int | None = None
    lastmod: str | None = None  # recorded, never trusted -- see below
    attempts: int = 0

    def __post_init__(self) -> None:
        if self.status != Status.FETCHED and not self.reason:
            raise ManifestError(
                f"{self.url}: status {self.status!r} needs a reason -- "
                "an unexplained omission cannot be diagnosed later"
            )
        if self.reason:
            prefix = self.reason.split(":", 1)[0]
            if prefix not in _VALID_PREFIXES:
                raise ManifestError(
                    f"{self.url}: reason {self.reason!r} has no known class prefix; "
                    f"expected one of {sorted(_VALID_PREFIXES)}"
                )

    @property
    def reason_class(self) -> str | None:
        return self.reason.split(":", 1)[0] if self.reason else None

    @property
    def canonical_url(self) -> str:
        """What this page is called in the corpus. Redirects collapse here."""
        return self.final_url or self.url

    def to_json(self) -> str:
        data = {k: v for k, v in asdict(self).items() if v not in (None, (), 0)}
        data["url"] = self.url
        data["source"] = self.source
        data["status"] = str(self.status)
        if self.fetched_at:
            data["fetched_at"] = self.fetched_at.isoformat()
        if self.silo:
            data["silo"] = list(self.silo)
        return json.dumps(data, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> ManifestRecord:
        raw: dict[str, Any] = json.loads(line)
        if raw.get("fetched_at"):
            raw["fetched_at"] = datetime.fromisoformat(raw["fetched_at"])
        if raw.get("silo"):
            raw["silo"] = tuple(raw["silo"])
        raw["status"] = Status(raw["status"])
        known = {f for f in cls.__slots__}
        return cls(**{k: v for k, v in raw.items() if k in known})


# ---------------------------------------------------------------------------


@dataclass
class Manifest:
    """The whole accounting record, backed by ``corpus/manifest.jsonl``.

    Kept in memory keyed by requested URL so a re-crawl can update a record in
    place, then rewritten wholesale. At a few thousand URLs this is measured in
    megabytes; streaming would buy nothing and cost the ability to reconcile.
    """

    path: Path
    records: dict[str, ManifestRecord] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> Manifest:
        path = Path(path)
        manifest = cls(path=path)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                record = ManifestRecord.from_json(line)
                manifest.records[record.url] = record
        return manifest

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(r.to_json() for r in sorted(self.records.values(), key=lambda r: r.url))
        self.path.write_text(body + "\n" if body else "", encoding="utf-8")

    # ---- writing -------------------------------------------------------

    def consider(self, url: str, source: str, lastmod: str | None = None) -> ManifestRecord:
        """Register a URL as seen. Status starts as excluded-pending-decision.

        Calling this before any policy check is deliberate: it means a URL
        cannot be dropped by falling through a branch, because it is already in
        the manifest and something has to explain it.
        """
        existing = self.records.get(url)
        if existing is not None:
            return existing
        record = ManifestRecord(
            url=url,
            source=source,
            status=Status.EXCLUDED,
            reason="policy:undecided",
            lastmod=lastmod,
        )
        self.records[url] = record
        return record

    def update(self, url: str, **changes: Any) -> ManifestRecord:
        record = replace(self.records[url], **changes)
        self.records[url] = record
        return record

    def mark_excluded(self, url: str, reason: str) -> ManifestRecord:
        return self.update(url, status=Status.EXCLUDED, reason=reason)

    def mark_fetched(
        self,
        url: str,
        *,
        http: int,
        content_hash: str,
        bytes_len: int,
        final_url: str | None = None,
        fetched_at: datetime | None = None,
    ) -> ManifestRecord:
        return self.update(
            url,
            status=Status.FETCHED,
            reason=None,
            http=http,
            content_hash=content_hash,
            bytes=bytes_len,
            final_url=final_url,
            fetched_at=fetched_at or datetime.now(timezone.utc),
        )

    def mark_failed(self, url: str, *, http: int | None, attempts: int) -> ManifestRecord:
        return self.update(
            url, status=Status.FAILED, reason="http_error", http=http, attempts=attempts
        )

    def mark_skipped(self, url: str, content_hash: str) -> ManifestRecord:
        return self.update(
            url, status=Status.SKIPPED, reason="unchanged_hash", content_hash=content_hash
        )

    def mark_extraction_empty(self, url: str) -> ManifestRecord:
        """HTTP 200 with no usable text.

        This gets its own status rather than folding into ``failed`` because it
        is the extraction-regression signature: a site reskin turns a whole
        silo's pages into empty strings while every fetch still returns 200.
        """
        return self.update(
            url, status=Status.EXCLUDED, reason="extraction_empty", extracted_chars=0
        )

    # ---- reading -------------------------------------------------------

    def __len__(self) -> int:
        return len(self.records)

    def by_status(self) -> Counter[str]:
        return Counter(str(r.status) for r in self.records.values())

    def by_reason_class(self) -> Counter[str]:
        return Counter(r.reason_class for r in self.records.values() if r.reason_class)

    def by_source(self) -> Counter[str]:
        return Counter(r.source for r in self.records.values())

    def fetched(self) -> list[ManifestRecord]:
        return [r for r in self.records.values() if r.status == Status.FETCHED]

    def undecided(self) -> list[ManifestRecord]:
        """Records still carrying ``policy:undecided``.

        A crawl that finishes with any of these has a hole in its decision
        logic: some URL reached the end without anything choosing its fate.
        """
        return [r for r in self.records.values() if r.reason == "policy:undecided"]

    def reconcile(self, expected_total: int) -> dict[str, Any]:
        """Check the manifest accounts for every URL that was enumerated.

        Coverage claims rest on this. If the numbers do not add up, the honest
        report is that we do not know what we have.
        """
        counts = self.by_status()
        total = sum(counts.values())
        return {
            "expected": expected_total,
            "recorded": total,
            "balanced": total == expected_total,
            "undecided": len(self.undecided()),
            "by_status": dict(counts),
            "by_reason_class": dict(self.by_reason_class()),
        }
