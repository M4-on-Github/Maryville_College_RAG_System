"""Alert checks for data decay detection.

Four independent pure functions of a MaintenanceContext, one per decay mode.
Each check always returns an Alert, with `fired=False` when nothing is wrong.
A check never performs I/O: all data is assembled by run.py before checking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from mcrag.crawl.manifest import ManifestRecord, Status
from mcrag.types import GoldQuestion

# Thresholds — the reasoning lives in each check's docstring.

# Extraction regression: text volume must not move more than this fraction.
# The college edits copy constantly; exact-match would fire on every typo fix.
# "Changes shape" means volume moved >50%, which catches real problems while
# tolerating routine maintenance.
EXTRACTION_SHAPE_FRACTION = 0.5

# Corpus shape drift: the "other" silo rate must stay under this ceiling.
# This is set by the plan (Task 34 acceptance criteria).
OTHER_SILO_RATE_CEILING = 0.10

# Volume anomaly: fetched-page count must not change by more than this fraction.
# 10% is the standing threshold for silo taxonomy review (PLAN, §1).
VOLUME_DRIFT_FRACTION = 0.10


@dataclass(frozen=True, slots=True)
class Alert:
    """One decay condition's verdict.

    `fired` is the condition's outcome. `urls` must be non-empty whenever
    `fired=True` and empty when `fired=False`. `detail` carries supporting
    numbers and sub-results for the human reader.
    """

    name: str  # "extraction_regression" | "corpus_shape_drift" | "volume_anomaly" | "stale_gold"
    fired: bool
    summary: str  # one human sentence, safe to read in a log
    urls: tuple[str, ...] = ()  # offending URLs, always populated when fired=True
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MaintenanceContext:
    """Immutable data assembled once per maintenance run for the alert checks.

    All data is pre-fetched and loaded by run.py; checks read only from here.
    This design makes verification possible: a test builds a context in memory,
    forces one condition, and asserts exactly one alert fires.
    """

    previous_manifest: list[ManifestRecord]
    current_manifest: list[ManifestRecord]
    pinned_extractions: dict[str, str]  # URL -> re-extracted text
    expected_extractions: dict[str, str]  # URL -> text from T6 pinned fixture
    pinned_http_status: dict[str, int]  # URL -> HTTP status this run
    gold_questions: list[GoldQuestion]
    chunks: dict[str, Any]  # chunk_id -> chunk dict, for staleness check


class AlertCheck(ABC):
    """One decay mode. Pure: reads a MaintenanceContext, returns an Alert.

    Deliberately here and not in `mcrag/interfaces.py`. That module holds the
    seams an *ablation* varies -- a config names the class and the runner
    instantiates it -- and no config names an alert check; the maintenance run
    instantiates all four, always. Declaring it there also costs the types:
    `MaintenanceContext` and `Alert` live in this module, so the base over
    there had to be written `check(ctx: object) -> object`, which is a weaker
    contract than no base at all.
    """

    name: str

    @abstractmethod
    def check(self, ctx: MaintenanceContext) -> Alert: ...


class ExtractionRegressionCheck(AlertCheck):
    """Alert 1: pinned snapshot pages (T6) have changed shape or gone empty.

    Fires when any T6 URL with HTTP 200 has:
    - empty or missing re-extracted text, OR
    - text volume changed by >50% (EXTRACTION_SHAPE_FRACTION)

    A URL not fetched this run, or fetched with a non-200, is not compared.
    `detail` counts the three populations separately -- `compared`,
    `not_fetched`, `not_ok` -- and the summary says so when nothing was
    compared at all, because "stable on all pinned pages" and "no pinned page
    was looked at" are different claims and only one of them is reassuring.
    This is the same rule the eval harness applies to the stale count: a thing
    nobody measured is `unchecked`, never a clean zero.
    """

    name = "extraction_regression"

    def check(self, ctx: MaintenanceContext) -> Alert:
        fired_urls = []
        not_fetched = 0
        not_ok = 0
        compared = 0

        for url, expected_text in ctx.expected_extractions.items():
            # Not fetched this run: nothing to compare against.
            if url not in ctx.pinned_http_status:
                not_fetched += 1
                continue

            http_status = ctx.pinned_http_status[url]
            # Only fire on HTTP 200; other statuses have their own alerts.
            if http_status != 200:
                not_ok += 1
                continue

            compared += 1
            extracted_text = ctx.pinned_extractions.get(url, "")

            # Check 1: empty extraction on 200
            if not extracted_text:
                fired_urls.append(url)
                continue

            # Check 2: shape drift (volume changed >50%)
            expected_len = len(expected_text)
            if expected_len > 0:
                actual_len = len(extracted_text)
                change = abs(actual_len - expected_len) / expected_len
                if change > EXTRACTION_SHAPE_FRACTION:
                    fired_urls.append(url)

        if fired_urls:
            summary = f"extraction changed shape on {len(fired_urls)} pinned page(s)"
        elif compared:
            summary = f"extraction stable on all {compared} pinned page(s) compared"
        else:
            summary = (
                f"no pinned page was compared: {not_fetched} not fetched, "
                f"{not_ok} fetched with a non-200"
            )

        return Alert(
            name=self.name,
            fired=bool(fired_urls),
            summary=summary,
            urls=tuple(fired_urls),
            detail={
                "pinned": len(ctx.expected_extractions),
                "compared": compared,
                "not_fetched": not_fetched,
                "not_ok": not_ok,
            },
        )


class CorpusShapeDriftCheck(AlertCheck):
    """Alert 2: corpus integrity: new 404s or excessive 'other'-silo rate.

    Fires when either:
    - a URL marked FETCHED in the previous manifest now has HTTP 404, OR
    - the "other"-silo rate in current manifest exceeds OTHER_SILO_RATE_CEILING

    (Empty silo tuple or ("other",) counts toward the "other" rate.)
    """

    name = "corpus_shape_drift"

    def check(self, ctx: MaintenanceContext) -> Alert:
        fired_urls = []
        detail: dict[str, Any] = {}

        # Sub-check 1: new 404s
        previous_fetched = {r.url for r in ctx.previous_manifest if r.status == Status.FETCHED}
        new_404s = []
        for record in ctx.current_manifest:
            if record.url in previous_fetched and record.http == 404:
                new_404s.append(record.url)
        detail["new_404s"] = len(new_404s)
        fired_urls.extend(new_404s)

        # Sub-check 2: "other" silo rate. With nothing fetched the rate is not
        # zero, it is undefined -- recorded as None, and it cannot fire.
        fetched_records = [r for r in ctx.current_manifest if r.status == Status.FETCHED]
        other_rate: float | None = None
        if fetched_records:
            other_count = sum(1 for r in fetched_records if not r.silo or r.silo == ("other",))
            other_rate = other_count / len(fetched_records)
            detail["other_silo_count"] = other_count
            detail["fetched_count"] = len(fetched_records)
        detail["other_silo_rate"] = other_rate

        rate_fired = other_rate is not None and other_rate > OTHER_SILO_RATE_CEILING
        should_fire = bool(new_404s) or rate_fired

        if should_fire:
            summary_parts = []
            if new_404s:
                summary_parts.append(f"{len(new_404s)} new 404s")
            if rate_fired:
                assert other_rate is not None  # rate_fired implies it
                summary_parts.append(
                    f"'other' silo rate {other_rate:.1%} exceeds {OTHER_SILO_RATE_CEILING:.0%}"
                )
            summary = "; ".join(summary_parts)
        elif other_rate is None:
            summary = "corpus shape unchecked: nothing fetched this run"
        else:
            summary = "corpus shape stable"

        return Alert(
            name=self.name,
            fired=should_fire,
            summary=summary,
            urls=tuple(fired_urls),
            detail=detail,
        )


class VolumeAnomalyCheck(AlertCheck):
    """Alert 3: fetched-page count must not drift >10% in either direction.

    Fires when abs(current - previous) / previous > VOLUME_DRIFT_FRACTION.

    Does NOT fire on a first run (previous_manifest is empty); such a run is a
    baseline, not a drift. `detail` records `"baseline": True`, a
    `"drift_fraction": None` (there is no drift to compute, which is not the
    same as a drift of zero), and the `"current_count"` it did establish --
    the single number a baseline run exists to produce, and the one the next
    run's comparison will be read against.

    When volume drops, `urls` lists the pages that were FETCHED before but are
    not FETCHED now (capped at 50). When volume rises, `urls` lists newly
    FETCHED pages (capped at 50). The true count is in `detail`.
    """

    name = "volume_anomaly"

    def check(self, ctx: MaintenanceContext) -> Alert:
        previous_fetched = [r for r in ctx.previous_manifest if r.status == Status.FETCHED]
        current_fetched = [r for r in ctx.current_manifest if r.status == Status.FETCHED]

        previous_count = len(previous_fetched)
        current_count = len(current_fetched)

        detail: dict[str, Any] = {}
        fired_urls = []

        # First run: no previous baseline, cannot drift from nothing
        if previous_count == 0 or not ctx.previous_manifest:
            detail["baseline"] = True
            detail["previous_count"] = previous_count
            detail["current_count"] = current_count
            detail["drift_fraction"] = None
            return Alert(
                name=self.name,
                fired=False,
                summary=f"first run, no previous baseline ({current_count} fetched)",
                urls=tuple(),
                detail=detail,
            )

        # Compute drift
        drift = abs(current_count - previous_count) / previous_count
        detail["baseline"] = False
        detail["previous_count"] = previous_count
        detail["current_count"] = current_count
        detail["drift_fraction"] = drift

        should_fire = drift > VOLUME_DRIFT_FRACTION

        if should_fire:
            if current_count < previous_count:
                # Volume dropped: list URLs that were fetched before but not now
                previous_urls = {r.url for r in previous_fetched}
                current_urls = {r.url for r in current_fetched}
                removed_urls = sorted(previous_urls - current_urls)
                fired_urls = removed_urls[:50]
                detail["removed_count"] = len(removed_urls)
            else:
                # Volume rose: list newly fetched URLs
                previous_urls = {r.url for r in previous_fetched}
                current_urls = {r.url for r in current_fetched}
                added_urls = sorted(current_urls - previous_urls)
                fired_urls = added_urls[:50]
                detail["added_count"] = len(added_urls)

            summary = (
                f"fetched pages dropped {previous_count} → {current_count} "
                f"({drift:.1%} drift)"
                if current_count < previous_count
                else f"fetched pages rose {previous_count} → {current_count} "
                f"({drift:.1%} drift)"
            )
        else:
            summary = f"volume stable ({previous_count} → {current_count}, {drift:.1%} drift)"

        return Alert(
            name=self.name,
            fired=should_fire,
            summary=summary,
            urls=tuple(fired_urls),
            detail=detail,
        )


class StaleGoldCheck(AlertCheck):
    """Alert 4: gold questions whose source pages have changed (Task 35).

    Reuses Task 35's find_stale_questions() to detect content-hash mismatches.
    Fires when the stale list is non-empty. `urls` are the distinct source URLs;
    `detail` carries the qids of stale questions.
    """

    name = "stale_gold"

    def check(self, ctx: MaintenanceContext) -> Alert:
        # Import here to avoid circular dependency at module load
        from mcrag.eval.gold import find_stale_questions

        stale = find_stale_questions(ctx.gold_questions, ctx.chunks)

        if stale:
            urls = sorted(set(s.source_url for s in stale))
            qids = [s.qid for s in stale]
            summary = f"{len(stale)} gold ref(s) stale on {len(urls)} page(s)"
        else:
            urls = []
            qids = []
            summary = "all gold pins current"

        return Alert(
            name=self.name,
            fired=bool(stale),
            summary=summary,
            urls=tuple(urls),
            detail={"stale_qids": qids},
        )
