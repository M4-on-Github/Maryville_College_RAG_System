"""Task 34: Verification of the four alert checks for data decay detection.

Each check is a pure function of a MaintenanceContext. Tests force one condition
at a time and verify that only the target check fires, while the other three
remain silent. Exit codes, log structure, and edge cases are covered.
"""

from __future__ import annotations

import inspect
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcrag.crawl.manifest import ManifestRecord, Status
from mcrag.eval.gold import load_gold_questions
from mcrag.maintain.alerts import (
    Alert,
    AlertCheck,
    CorpusShapeDriftCheck,
    ExtractionRegressionCheck,
    MaintenanceContext,
    StaleGoldCheck,
    VolumeAnomalyCheck,
)
from mcrag.maintain.log import append_maintenance_log
import mcrag.maintain.run as run_module
from mcrag.maintain.run import (
    _fixture_url,
    _load_pinned_extractions,
    main as maintenance_main,
)
from mcrag.types import GoldQuestion, Pin


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def empty_context() -> MaintenanceContext:
    """A minimal, clean context where no checks fire."""
    return MaintenanceContext(
        previous_manifest=[],
        current_manifest=[],
        pinned_extractions={},
        expected_extractions={},
        pinned_http_status={},
        gold_questions=[],
        chunks={},
    )


@pytest.fixture
def minimal_previous_manifest() -> list[ManifestRecord]:
    """A minimal previous manifest with one fetched page."""
    return [
        ManifestRecord(
            url="https://example.com/page1",
            source="sitemap",
            status=Status.FETCHED,
            final_url="https://example.com/page1",
            http=200,
            content_hash="hash1",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        ),
    ]


@pytest.fixture
def minimal_current_manifest() -> list[ManifestRecord]:
    """A minimal current manifest matching the previous one."""
    return [
        ManifestRecord(
            url="https://example.com/page1",
            source="sitemap",
            status=Status.FETCHED,
            final_url="https://example.com/page1",
            http=200,
            content_hash="hash1",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        ),
    ]


# ============================================================================
# Alert 1: Extraction Regression
# ============================================================================


def test_alert1_empty_extraction_fires(empty_context: MaintenanceContext) -> None:
    """Alert 1 fires when HTTP 200 extraction is empty."""
    url = "https://example.com/test"
    context = MaintenanceContext(
        previous_manifest=empty_context.previous_manifest,
        current_manifest=empty_context.current_manifest,
        pinned_extractions={url: ""},  # Empty!
        expected_extractions={url: "some expected text"},
        pinned_http_status={url: 200},
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = ExtractionRegressionCheck()
    alert = check.check(context)

    assert alert.fired
    assert alert.name == "extraction_regression"
    assert url in alert.urls
    assert len(alert.urls) > 0


def test_alert1_shape_drift_fires(empty_context: MaintenanceContext) -> None:
    """Alert 1 fires when extracted text volume drifts >50%."""
    url = "https://example.com/test"
    expected = "x" * 1000
    # Text went from 1000 chars to 400 chars = 60% reduction, exceeds 50%
    extracted = "y" * 400

    context = MaintenanceContext(
        previous_manifest=empty_context.previous_manifest,
        current_manifest=empty_context.current_manifest,
        pinned_extractions={url: extracted},
        expected_extractions={url: expected},
        pinned_http_status={url: 200},
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = ExtractionRegressionCheck()
    alert = check.check(context)

    assert alert.fired
    assert url in alert.urls


def test_alert1_small_change_does_not_fire(empty_context: MaintenanceContext) -> None:
    """Alert 1 does not fire for text volume changes <50%."""
    url = "https://example.com/test"
    expected = "x" * 1000
    # Text went from 1000 to 600 chars = 40% reduction, under 50%
    extracted = "y" * 600

    context = MaintenanceContext(
        previous_manifest=empty_context.previous_manifest,
        current_manifest=empty_context.current_manifest,
        pinned_extractions={url: extracted},
        expected_extractions={url: expected},
        pinned_http_status={url: 200},
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = ExtractionRegressionCheck()
    alert = check.check(context)

    assert not alert.fired
    assert len(alert.urls) == 0


def test_alert1_skips_unfetched_urls(empty_context: MaintenanceContext) -> None:
    """Alert 1 does not compare an unfetched URL, and says it compared nothing.

    The silent-success trap this guards: `fired=False` on a run where no pinned
    page was fetched looks exactly like `fired=False` on a run where all of
    them were fetched and all were fine. The counts and the summary have to
    separate the two.
    """
    url = "https://example.com/test"

    context = MaintenanceContext(
        previous_manifest=empty_context.previous_manifest,
        current_manifest=empty_context.current_manifest,
        pinned_extractions={},  # URL not fetched
        expected_extractions={url: "expected text"},
        pinned_http_status={},  # URL not in status dict
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = ExtractionRegressionCheck()
    alert = check.check(context)

    assert not alert.fired
    assert alert.detail["not_fetched"] == 1
    assert alert.detail["compared"] == 0
    assert len(alert.urls) == 0
    assert "no pinned page was compared" in alert.summary
    assert "stable" not in alert.summary


def test_alert1_counts_a_non_200_separately_from_an_unfetched_page(
    empty_context: MaintenanceContext,
) -> None:
    """A pinned page fetched with a 500 is neither compared nor missing.

    The first implementation `continue`d past it without counting it anywhere,
    so `checked` claimed it among the compared pages while nothing had been
    compared.
    """
    context = MaintenanceContext(
        previous_manifest=[],
        current_manifest=[],
        pinned_extractions={},
        expected_extractions={"https://example.com/a": "x", "https://example.com/b": "y"},
        pinned_http_status={"https://example.com/a": 500},
        gold_questions=[],
        chunks={},
    )

    alert = ExtractionRegressionCheck().check(context)

    assert not alert.fired
    assert alert.detail == {"pinned": 2, "compared": 0, "not_fetched": 1, "not_ok": 1}


def test_alert1_clear_returns_false_with_empty_urls(empty_context: MaintenanceContext) -> None:
    """Alert 1 clear case returns fired=False with empty urls."""
    url = "https://example.com/test"
    expected = "x" * 1000
    extracted = "x" * 1000  # Identical

    context = MaintenanceContext(
        previous_manifest=empty_context.previous_manifest,
        current_manifest=empty_context.current_manifest,
        pinned_extractions={url: extracted},
        expected_extractions={url: expected},
        pinned_http_status={url: 200},
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = ExtractionRegressionCheck()
    alert = check.check(context)

    assert not alert.fired
    assert len(alert.urls) == 0


# ============================================================================
# Alert 2: Corpus Shape Drift
# ============================================================================


def test_alert2_new_404_fires(empty_context: MaintenanceContext) -> None:
    """Alert 2 fires when a previously-fetched URL now has HTTP 404."""
    url = "https://example.com/deleted"
    previous = [
        ManifestRecord(
            url=url,
            source="sitemap",
            status=Status.FETCHED,
            final_url=url,
            http=200,
            content_hash="hash1",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        ),
    ]
    current = [
        ManifestRecord(
            url=url,
            source="sitemap",
            status=Status.FAILED,
            final_url=url,
            http=404,
            content_hash=None,
            fetched_at=None,
            bytes=None,
            extracted_chars=None,
            silo=(),
            chunks=None,
            reason="http_error: 404",
        ),
    ]

    context = MaintenanceContext(
        previous_manifest=previous,
        current_manifest=current,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = CorpusShapeDriftCheck()
    alert = check.check(context)

    assert alert.fired
    assert url in alert.urls
    assert alert.detail["new_404s"] == 1


def test_alert2_high_other_rate_fires(empty_context: MaintenanceContext) -> None:
    """Alert 2 fires when 'other' silo rate exceeds 10%."""
    # Create 10 fetched records, 2 with empty silo
    current = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",) if i < 8 else (),  # 8 with silo, 2 with empty silo
            chunks=5,
        )
        for i in range(10)
    ]

    context = MaintenanceContext(
        previous_manifest=[],
        current_manifest=current,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = CorpusShapeDriftCheck()
    alert = check.check(context)

    assert alert.fired
    assert alert.detail["other_silo_rate"] == 0.2  # 2 out of 10
    assert alert.detail["other_silo_count"] == 2


def test_alert2_low_other_rate_does_not_fire(empty_context: MaintenanceContext) -> None:
    """Alert 2 does not fire when 'other' rate is under 10%."""
    # Create 20 fetched records, 1 with empty silo = 5%
    current = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",) if i < 19 else (),
            chunks=5,
        )
        for i in range(20)
    ]

    context = MaintenanceContext(
        previous_manifest=[],
        current_manifest=current,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = CorpusShapeDriftCheck()
    alert = check.check(context)

    assert not alert.fired
    assert len(alert.urls) == 0


def test_alert2_clear_returns_false_with_empty_urls(empty_context: MaintenanceContext) -> None:
    """Alert 2 clear case returns fired=False with empty urls."""
    previous = [
        ManifestRecord(
            url="https://example.com/page1",
            source="sitemap",
            status=Status.FETCHED,
            final_url="https://example.com/page1",
            http=200,
            content_hash="hash1",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        ),
    ]
    current = [
        ManifestRecord(
            url="https://example.com/page1",
            source="sitemap",
            status=Status.FETCHED,
            final_url="https://example.com/page1",
            http=200,
            content_hash="hash1",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        ),
    ]

    context = MaintenanceContext(
        previous_manifest=previous,
        current_manifest=current,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = CorpusShapeDriftCheck()
    alert = check.check(context)

    assert not alert.fired
    assert len(alert.urls) == 0


# ============================================================================
# Alert 3: Volume Anomaly
# ============================================================================


def test_alert3_volume_increase_fires(empty_context: MaintenanceContext) -> None:
    """Alert 3 fires when fetched pages increase by >10%."""
    # 100 pages -> 115 pages = 15% increase
    previous = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(100)
    ]
    current = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(115)
    ]

    context = MaintenanceContext(
        previous_manifest=previous,
        current_manifest=current,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = VolumeAnomalyCheck()
    alert = check.check(context)

    assert alert.fired
    assert alert.detail["drift_fraction"] > 0.1


def test_alert3_volume_decrease_fires(empty_context: MaintenanceContext) -> None:
    """Alert 3 fires when fetched pages decrease by >10%."""
    # 100 pages -> 80 pages = 20% decrease
    previous = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(100)
    ]
    current = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(80)
    ]

    context = MaintenanceContext(
        previous_manifest=previous,
        current_manifest=current,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = VolumeAnomalyCheck()
    alert = check.check(context)

    assert alert.fired


def test_alert3_small_change_does_not_fire(empty_context: MaintenanceContext) -> None:
    """Alert 3 does not fire for volume changes <10%."""
    # 100 pages -> 105 pages = 5% increase
    previous = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(100)
    ]
    current = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(105)
    ]

    context = MaintenanceContext(
        previous_manifest=previous,
        current_manifest=current,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = VolumeAnomalyCheck()
    alert = check.check(context)

    assert not alert.fired
    assert len(alert.urls) == 0


def test_alert3_first_run_does_not_fire(empty_context: MaintenanceContext) -> None:
    """Alert 3 does not fire on a first run (no previous baseline)."""
    current = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(100)
    ]

    context = MaintenanceContext(
        previous_manifest=[],  # First run
        current_manifest=current,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = VolumeAnomalyCheck()
    alert = check.check(context)

    assert not alert.fired
    assert alert.detail.get("baseline") is True
    assert len(alert.urls) == 0


def test_alert3_clear_returns_false_with_empty_urls(
    minimal_previous_manifest: list[ManifestRecord],
    minimal_current_manifest: list[ManifestRecord],
    empty_context: MaintenanceContext,
) -> None:
    """Alert 3 clear case returns fired=False with empty urls."""
    context = MaintenanceContext(
        previous_manifest=minimal_previous_manifest,
        current_manifest=minimal_current_manifest,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=empty_context.gold_questions,
        chunks=empty_context.chunks,
    )

    check = VolumeAnomalyCheck()
    alert = check.check(context)

    assert not alert.fired
    assert len(alert.urls) == 0


# ============================================================================
# Alert 4: Stale Gold
# ============================================================================


def test_alert4_stale_gold_fires(empty_context: MaintenanceContext) -> None:
    """Alert 4 fires when a gold question's content hash has changed."""
    chunk_id = "abc123def456-5"
    old_hash = "oldhash"
    new_hash = "newhash"

    gold_q = GoldQuestion(
        qid="q1",
        slice="single_silo",
        question="What is this?",
        gold=(chunk_id,),
        conjunctive=False,
        pins=(Pin(gold_ref=chunk_id, content_hash=old_hash, origin="backfill"),),
    )

    chunks = {
        chunk_id: {
            "chunk_id": chunk_id,
            "source_url": "https://example.com/page1",
            "content_hash": new_hash,  # Changed!
        }
    }

    context = MaintenanceContext(
        previous_manifest=empty_context.previous_manifest,
        current_manifest=empty_context.current_manifest,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=[gold_q],
        chunks=chunks,
    )

    check = StaleGoldCheck()
    alert = check.check(context)

    assert alert.fired
    assert "https://example.com/page1" in alert.urls
    assert "q1" in alert.detail["stale_qids"]


def test_alert4_current_gold_does_not_fire(empty_context: MaintenanceContext) -> None:
    """Alert 4 does not fire when all gold hashes are current."""
    chunk_id = "abc123def456-5"
    hash_val = "currenthash"

    gold_q = GoldQuestion(
        qid="q1",
        slice="single_silo",
        question="What is this?",
        gold=(chunk_id,),
        conjunctive=False,
        pins=(Pin(gold_ref=chunk_id, content_hash=hash_val, origin="backfill"),),
    )

    chunks = {
        chunk_id: {
            "chunk_id": chunk_id,
            "source_url": "https://example.com/page1",
            "content_hash": hash_val,  # Same!
        }
    }

    context = MaintenanceContext(
        previous_manifest=empty_context.previous_manifest,
        current_manifest=empty_context.current_manifest,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=[gold_q],
        chunks=chunks,
    )

    check = StaleGoldCheck()
    alert = check.check(context)

    assert not alert.fired
    assert len(alert.urls) == 0


def test_alert4_clear_returns_false_with_empty_urls(empty_context: MaintenanceContext) -> None:
    """Alert 4 clear case returns fired=False with empty urls."""
    context = MaintenanceContext(
        previous_manifest=empty_context.previous_manifest,
        current_manifest=empty_context.current_manifest,
        pinned_extractions=empty_context.pinned_extractions,
        expected_extractions=empty_context.expected_extractions,
        pinned_http_status=empty_context.pinned_http_status,
        gold_questions=[],  # No gold questions
        chunks={},
    )

    check = StaleGoldCheck()
    alert = check.check(context)

    assert not alert.fired
    assert len(alert.urls) == 0


# ============================================================================
# Independence and exit codes
# ============================================================================


def _fetched(url: str, silo: tuple[str, ...] = ("academics",)) -> ManifestRecord:
    return ManifestRecord(
        url=url,
        source="sitemap",
        status=Status.FETCHED,
        final_url=url,
        http=200,
        content_hash="hash1",
        fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        bytes=1000,
        extracted_chars=500,
        silo=silo,
        chunks=5,
    )


def _gone(url: str) -> ManifestRecord:
    return ManifestRecord(
        url=url,
        source="sitemap",
        status=Status.FAILED,
        final_url=url,
        http=404,
        content_hash=None,
        fetched_at=None,
        bytes=None,
        extracted_chars=None,
        silo=(),
        chunks=None,
        reason="http_error: 404",
    )


ALL_CHECKS: tuple[AlertCheck, ...] = (
    ExtractionRegressionCheck(),
    CorpusShapeDriftCheck(),
    VolumeAnomalyCheck(),
    StaleGoldCheck(),
)


def _only_firing(ctx: MaintenanceContext) -> list[str]:
    """The names of the checks that fire on this context, in check order."""
    return [c.name for c in ALL_CHECKS if c.check(ctx).fired]


def _context(**overrides) -> MaintenanceContext:
    base = dict(
        previous_manifest=[],
        current_manifest=[],
        pinned_extractions={},
        expected_extractions={},
        pinned_http_status={},
        gold_questions=[],
        chunks={},
    )
    base.update(overrides)
    return MaintenanceContext(**base)  # type: ignore[arg-type]


def test_extraction_regression_fires_alone() -> None:
    """A pinned page that now extracts to nothing fires Alert 1 and only Alert 1."""
    url = "https://example.com/extract_test"
    ctx = _context(
        pinned_extractions={url: ""},
        expected_extractions={url: "expected"},
        pinned_http_status={url: 200},
    )
    assert _only_firing(ctx) == ["extraction_regression"]


def test_corpus_shape_drift_fires_alone() -> None:
    """A page that 404s fires Alert 2 and only Alert 2.

    The fetched count is deliberately held at one across the two manifests --
    one page died, one page appeared. The first draft of this test used a
    current manifest with nothing fetched in it, so the volume check fired too
    on a 100% drop; the response was to delete the volume assertion and leave
    a comment ("let's not include volume changes in this test"), which left
    Alert 3's independence untested rather than established. Holding the count
    steady is what actually isolates the condition.
    """
    dead = "https://example.com/old_page"
    ctx = _context(
        previous_manifest=[_fetched(dead)],
        current_manifest=[_gone(dead), _fetched("https://example.com/new_page")],
    )
    assert _only_firing(ctx) == ["corpus_shape_drift"]


def test_volume_anomaly_fires_alone() -> None:
    """Half the corpus going missing fires Alert 3 and only Alert 3.

    The pages are absent from the current manifest rather than 404 in it, so
    the corpus-shape check has nothing to find: a page that vanished from the
    crawl queue and a page the server denies are different failures, and this
    forces only the first.
    """
    previous = [_fetched(f"https://example.com/p{i}") for i in range(10)]
    ctx = _context(previous_manifest=previous, current_manifest=previous[:5])
    assert _only_firing(ctx) == ["volume_anomaly"]


def test_stale_gold_fires_alone() -> None:
    """A gold pin whose page changed fires Alert 4 and only Alert 4."""
    chunk_id = "abc123-5"
    ctx = _context(
        gold_questions=[
            GoldQuestion(
                qid="q1",
                slice="single_silo",
                question="What?",
                gold=(chunk_id,),
                conjunctive=False,
                pins=(Pin(gold_ref=chunk_id, content_hash="oldhash", origin="backfill"),),
            )
        ],
        chunks={
            chunk_id: {
                "chunk_id": chunk_id,
                "source_url": "https://example.com/page1",
                "content_hash": "newhash",
            }
        },
    )
    assert _only_firing(ctx) == ["stale_gold"]


def test_a_clean_context_fires_nothing() -> None:
    """Silence is the success condition, so the silent case gets its own test.

    Not a tautology against an empty context: every check has data to look at
    here, and all four have to come back quiet.
    """
    url = "https://example.com/ok"
    pages = [_fetched(f"https://example.com/p{i}") for i in range(10)]
    chunk_id = "abc123-5"
    ctx = _context(
        previous_manifest=pages,
        current_manifest=pages,
        pinned_extractions={url: "x" * 1000},
        expected_extractions={url: "x" * 1000},
        pinned_http_status={url: 200},
        gold_questions=[
            GoldQuestion(
                qid="q1",
                slice="single_silo",
                question="What?",
                gold=(chunk_id,),
                conjunctive=False,
                pins=(Pin(gold_ref=chunk_id, content_hash="samehash", origin="backfill"),),
            )
        ],
        chunks={
            chunk_id: {
                "chunk_id": chunk_id,
                "source_url": "https://example.com/page1",
                "content_hash": "samehash",
            }
        },
    )
    assert _only_firing(ctx) == []


def test_all_alerts_have_fired_true_and_non_empty_urls_when_fired() -> None:
    """When an alert fires, it always has fired=True and non-empty urls."""
    # Test Alert 1
    context1 = MaintenanceContext(
        previous_manifest=[],
        current_manifest=[],
        pinned_extractions={"https://example.com/test": ""},
        expected_extractions={"https://example.com/test": "expected"},
        pinned_http_status={"https://example.com/test": 200},
        gold_questions=[],
        chunks={},
    )
    alert1 = ExtractionRegressionCheck().check(context1)
    assert alert1.fired  # This should definitely fire
    assert len(alert1.urls) > 0
    assert alert1.urls[0] == "https://example.com/test"

    # Test Alert 2
    previous = [
        ManifestRecord(
            url="https://example.com/old",
            source="sitemap",
            status=Status.FETCHED,
            final_url="https://example.com/old",
            http=200,
            content_hash="hash1",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        ),
    ]
    current = [
        ManifestRecord(
            url="https://example.com/old",
            source="sitemap",
            status=Status.FAILED,
            final_url="https://example.com/old",
            http=404,
            content_hash=None,
            fetched_at=None,
            bytes=None,
            extracted_chars=None,
            silo=(),
            chunks=None,
            reason="http_error: 404",
        ),
    ]
    context2 = MaintenanceContext(
        previous_manifest=previous,
        current_manifest=current,
        pinned_extractions={},
        expected_extractions={},
        pinned_http_status={},
        gold_questions=[],
        chunks={},
    )
    alert2 = CorpusShapeDriftCheck().check(context2)
    assert alert2.fired  # This should definitely fire
    assert len(alert2.urls) > 0
    assert "https://example.com/old" in alert2.urls

    # Test Alert 3
    previous3 = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(100)
    ]
    current3 = [
        ManifestRecord(
            url=f"https://example.com/page{i}",
            source="sitemap",
            status=Status.FETCHED,
            final_url=f"https://example.com/page{i}",
            http=200,
            content_hash=f"hash{i}",
            fetched_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        )
        for i in range(120)  # 20% increase, should fire
    ]
    context3 = MaintenanceContext(
        previous_manifest=previous3,
        current_manifest=current3,
        pinned_extractions={},
        expected_extractions={},
        pinned_http_status={},
        gold_questions=[],
        chunks={},
    )
    alert3 = VolumeAnomalyCheck().check(context3)
    assert alert3.fired
    assert len(alert3.urls) > 0  # Should list newly added pages

    # Test Alert 4
    chunk_id = "abc123-5"
    gold_q = GoldQuestion(
        qid="q1",
        slice="single_silo",
        question="What?",
        gold=(chunk_id,),
        conjunctive=False,
        pins=(Pin(gold_ref=chunk_id, content_hash="oldhash", origin="backfill"),),
    )
    chunks = {
        chunk_id: {
            "chunk_id": chunk_id,
            "source_url": "https://example.com/page1",
            "content_hash": "newhash",
        }
    }
    context4 = MaintenanceContext(
        previous_manifest=[],
        current_manifest=[],
        pinned_extractions={},
        expected_extractions={},
        pinned_http_status={},
        gold_questions=[gold_q],
        chunks=chunks,
    )
    alert4 = StaleGoldCheck().check(context4)
    assert alert4.fired
    assert len(alert4.urls) > 0
    assert "https://example.com/page1" in alert4.urls


# ============================================================================
# Maintenance log behavior
# ============================================================================


def test_log_is_append_only(tmp_path: Path) -> None:
    """The maintenance log is append-only: rows are never edited or deleted."""
    log_path = tmp_path / "maintenance_log.jsonl"

    alert1 = Alert(
        name="extraction_regression",
        fired=False,
        summary="test",
        urls=(),
        detail={},
    )

    # Write first entry
    append_maintenance_log(
        log_path,
        run_id="run1",
        started_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc),
        exit_code=0,
        pages_fetched=100,
        alerts=[alert1],
    )

    first_content = log_path.read_text(encoding="utf-8")
    assert "run1" in first_content

    # Write second entry
    append_maintenance_log(
        log_path,
        run_id="run2",
        started_at=datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 2, 10, 5, 0, tzinfo=timezone.utc),
        exit_code=2,
        pages_fetched=105,
        alerts=[alert1],
    )

    final_content = log_path.read_text(encoding="utf-8")
    # Both runs should be present
    assert "run1" in final_content
    assert "run2" in final_content
    # The file should have two lines
    lines = [l for l in final_content.strip().split("\n") if l]
    assert len(lines) == 2


def test_log_handles_cleared_file(tmp_path: Path) -> None:
    """The maintenance log handles a cleared or missing file gracefully."""
    log_path = tmp_path / "maintenance_log.jsonl"

    alert = Alert(
        name="extraction_regression",
        fired=False,
        summary="test",
        urls=(),
        detail={},
    )

    # File doesn't exist yet
    append_maintenance_log(
        log_path,
        run_id="run1",
        started_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc),
        exit_code=0,
        pages_fetched=100,
        alerts=[alert],
    )

    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "run1" in content


def test_log_contains_all_four_alerts(tmp_path: Path) -> None:
    """The log contains all four alert records, even if some didn't fire."""
    log_path = tmp_path / "maintenance_log.jsonl"

    alerts = [
        Alert(name="extraction_regression", fired=False, summary="test", urls=(), detail={}),
        Alert(name="corpus_shape_drift", fired=True, summary="404s found", urls=("url1",), detail={}),
        Alert(name="volume_anomaly", fired=False, summary="test", urls=(), detail={}),
        Alert(name="stale_gold", fired=False, summary="test", urls=(), detail={}),
    ]

    append_maintenance_log(
        log_path,
        run_id="run1",
        started_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc),
        exit_code=2,
        pages_fetched=100,
        alerts=alerts,
    )

    content = log_path.read_text(encoding="utf-8")
    entry = json.loads(content.strip())

    assert len(entry["alerts"]) == 4
    assert entry["alerts"][0]["name"] == "extraction_regression"
    assert entry["alerts"][1]["name"] == "corpus_shape_drift"
    assert entry["alerts"][1]["fired"] is True
    assert entry["alerts"][2]["name"] == "volume_anomaly"
    assert entry["alerts"][3]["name"] == "stale_gold"


# ============================================================================
# Exit codes
# ============================================================================
#
# The exit code is the entire interface between this task and whatever runs it
# on a schedule: cron sends mail on non-zero and nothing on zero, so 0/1/2 are
# the three things a maintenance run can ever say out loud. The first drafts of
# these tests asserted `exit_code in (0, 2)` ("accept either since we're testing
# structure") and tested exit 2 by calling a check directly without going
# through `main` at all, so all three codes were unverified behind two tests
# named for them. They run `main` end to end now.


def _manifest_line(url: str) -> str:
    return (
        ManifestRecord(
            url=url,
            source="sitemap",
            status=Status.FETCHED,
            final_url=url,
            http=200,
            content_hash="hash1",
            fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            bytes=1000,
            extracted_chars=500,
            silo=("academics",),
            chunks=5,
        ).to_json()
        + "\n"
    )


def _maintenance_tree(tmp_path: Path) -> Path:
    """The minimum on-disk layout `main` reads, with nothing wrong in it."""
    for rel in ("data/gold/gold_v1.jsonl", "corpus/chunks.jsonl", "corpus/manifest.jsonl"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (tmp_path / "tests" / "fixtures" / "extraction").mkdir(parents=True, exist_ok=True)
    return tmp_path


@contextmanager
def _cwd(path: Path):
    """`main` resolves every path against the working directory."""
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _log_rows(tmp_path: Path) -> list[dict]:
    log = tmp_path / "data" / "maintenance" / "maintenance_log.jsonl"
    assert log.exists(), "every run must leave a row, including a failed one"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_exit_code_0_on_silence(tmp_path: Path) -> None:
    """A clean run returns 0 exactly, and logs the four silent alerts."""
    _maintenance_tree(tmp_path)

    with _cwd(tmp_path):
        exit_code = maintenance_main(lambda: {"pages_fetched": 10})

    assert exit_code == 0

    (row,) = _log_rows(tmp_path)
    assert row["exit_code"] == 0
    assert row["pages_fetched"] == 10
    assert row["error"] is None
    assert [a["name"] for a in row["alerts"]] == [
        "extraction_regression",
        "corpus_shape_drift",
        "volume_anomaly",
        "stale_gold",
    ]
    assert not any(a["fired"] for a in row["alerts"]), "nothing was wrong; nothing may fire"


def test_exit_code_2_when_an_alert_fires(tmp_path: Path) -> None:
    """A fired alert makes `main` return 2 and say which one in the log.

    Driven through the real `main`, not by calling a check: the thing under
    test is the wiring from a fired alert to a non-zero exit, and a test that
    asserts `check(ctx).fired` exercises none of it.
    """
    _maintenance_tree(tmp_path)

    # A gold question pinned to a hash the corpus no longer has: Alert 4.
    (tmp_path / "data" / "gold" / "gold_v1.jsonl").write_text(
        json.dumps(
            {
                "qid": "q1",
                "slice": "single_silo",
                "question": "What?",
                "gold": ["abc123-5"],
                "conjunctive": False,
                "pins": [
                    {"gold_ref": "abc123-5", "content_hash": "oldhash", "origin": "backfill"}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "corpus" / "chunks.jsonl").write_text(
        json.dumps(
            {
                "chunk_id": "abc123-5",
                "source_url": "https://www.maryvillecollege.edu/about/",
                "content_hash": "newhash",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with _cwd(tmp_path):
        exit_code = maintenance_main(lambda: {"pages_fetched": 10})

    assert exit_code == 2

    (row,) = _log_rows(tmp_path)
    assert row["exit_code"] == 2
    fired = [a for a in row["alerts"] if a["fired"]]
    assert [a["name"] for a in fired] == ["stale_gold"]
    assert fired[0]["detail"]["stale_qids"] == ["q1"]
    assert fired[0]["urls"] == ["https://www.maryvillecollege.edu/about/"]


def test_exit_code_1_when_the_ingest_chain_raises(tmp_path: Path) -> None:
    """A chain that dies returns 1, and the row says what killed it.

    `pages_fetched` is None rather than 0: the chain raised partway through, so
    the count is unknown, and 0 would be the log asserting it fetched nothing.
    Same rule as the eval harness's `unchecked` stale count.
    """
    _maintenance_tree(tmp_path)

    def exploding_chain() -> dict[str, int]:
        raise RuntimeError("robots.txt fetch timed out")

    with _cwd(tmp_path):
        exit_code = maintenance_main(exploding_chain)

    assert exit_code == 1

    (row,) = _log_rows(tmp_path)
    assert row["exit_code"] == 1
    assert row["pages_fetched"] is None
    assert row["error"] == "RuntimeError: robots.txt fetch timed out"
    assert row["alerts"] == [], "nothing was checked, so no alert may claim to be silent"


def test_a_failed_run_does_not_advance_the_drift_baseline(tmp_path: Path) -> None:
    """Exit 1 leaves `.previous_manifest.jsonl` alone.

    Rotating the baseline on a failed run would compare the next run against a
    corpus this run never finished building, and the drift between the last
    good crawl and the next one would be lost with no record that it was.
    """
    _maintenance_tree(tmp_path)
    previous = tmp_path / "corpus" / ".previous_manifest.jsonl"

    with _cwd(tmp_path):
        assert maintenance_main(lambda: {"pages_fetched": 1}) == 0
    assert previous.exists(), "a clean run must leave the next run a baseline"
    after_clean = previous.read_bytes()

    (tmp_path / "corpus" / "manifest.jsonl").write_text(
        _manifest_line("https://example.com/new"), encoding="utf-8"
    )
    with _cwd(tmp_path):
        assert maintenance_main(lambda: (_ for _ in ()).throw(RuntimeError("boom"))) == 1

    assert previous.read_bytes() == after_clean, "a failed run must not rotate the baseline"


def test_the_log_keeps_every_run(tmp_path: Path) -> None:
    """Three runs, three rows, in order -- the log is appended, never rewritten."""
    _maintenance_tree(tmp_path)

    with _cwd(tmp_path):
        assert maintenance_main(lambda: {"pages_fetched": 1}) == 0
        assert maintenance_main(lambda: (_ for _ in ()).throw(RuntimeError("boom"))) == 1
        assert maintenance_main(lambda: {"pages_fetched": 2}) == 0

    rows = _log_rows(tmp_path)
    assert [r["exit_code"] for r in rows] == [0, 1, 0]
    assert [r["pages_fetched"] for r in rows] == [1, None, 2]


def test_the_baseline_rotates_only_after_the_log_row_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A log write that fails must not leave the baseline advanced.

    The rotation and the log row are two writes with no transaction between
    them, so their order decides what a crash costs. Log first: the run is
    recorded and the baseline simply does not move, and the next run compares
    against the last known-good crawl. Rotate first -- which is what the
    original did -- and a crash in between silently advances the baseline to a
    corpus no row describes, so the next run measures this crawl against
    itself, finds no drift, and is right about the wrong question.
    """
    _maintenance_tree(tmp_path)
    previous = tmp_path / "corpus" / ".previous_manifest.jsonl"

    import mcrag.maintain.run as run_module

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(run_module, "append_maintenance_log", refuse)

    with _cwd(tmp_path):
        with pytest.raises(OSError, match="disk full"):
            maintenance_main(lambda: {"pages_fetched": 10})

    assert not previous.exists(), "the baseline moved before the run was recorded"


# ============================================================================
# The pinned-fixture URL, which decides whether Alert 1 looks at anything
# ============================================================================


def test_every_pinned_fixture_resolves_to_the_url_it_was_pinned_from() -> None:
    """The T6 fixtures must all resolve, and resolve to real URL paths.

    A hard assertion, not a skip: the fixtures are committed, and a checkout
    where they stop resolving is the regression this guards, not a missing
    dependency. What it guards against specifically: deriving the URL from the
    filename, which `slug()` built by flattening `/` to `__`. That derivation
    produced `/about__downtown-center__rentals/` for 12 of the 17 fixtures --
    URLs no snapshot has ever been stored under -- and because the same bad key
    was used on both sides of the comparison, the lookup missed, the page was
    booked as "not fetched", and Alert 1 reported stability over pages it had
    never compared. A `__` anywhere in a resolved URL means it is back.
    """
    fixtures_dir = Path("tests/fixtures/extraction")
    expected_files = sorted(fixtures_dir.glob("*.expected.txt"))
    assert expected_files, f"no pinned fixtures in {fixtures_dir}"

    unresolved = [f.name for f in expected_files if _fixture_url(f) is None]
    assert not unresolved, f"pinned fixtures with no resolvable url: {unresolved}"

    flattened = [f.name for f in expected_files if "__" in (_fixture_url(f) or "")]
    assert not flattened, f"url rebuilt from the filename, not read from meta: {flattened}"

    multi_segment = [f for f in expected_files if "__" in f.name]
    assert multi_segment, "the fixture set no longer covers a multi-segment path"
    for f in multi_segment:
        url = _fixture_url(f)
        assert url is not None
        path = url.removeprefix("https://www.maryvillecollege.edu")
        assert path.count("/") >= 3, f"{f.name} resolved to a flat path: {url}"


def test_the_two_sides_of_alert_1_are_keyed_the_same_way(tmp_path: Path) -> None:
    """Expected text and re-extracted text must be looked up under one key.

    They were derived independently by two functions that each rebuilt the URL,
    so a change to one derivation would have silently emptied the comparison
    rather than failing. The snapshot lookup now takes the resolved URLs it is
    given.
    """
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    url = "https://www.maryvillecollege.edu/about/downtown-center/rentals/"
    (fixtures / "about__downtown-center__rentals.expected.txt").write_text(
        "pinned body", encoding="utf-8"
    )
    (fixtures / "about__downtown-center__rentals.meta.txt").write_text(
        f"url: {url}\ntitle: Downtown Center Rental\nbreadcrumb: About > Downtown Center\n",
        encoding="utf-8",
    )

    expected, unresolved = _load_pinned_extractions(fixtures)

    assert unresolved == []
    assert list(expected) == [url]
    assert expected[url] == "pinned body"


def test_a_fixture_without_a_meta_file_is_reported_not_guessed(tmp_path: Path) -> None:
    """An unresolvable fixture comes back in a list the caller has to handle."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "orphan.expected.txt").write_text("body", encoding="utf-8")

    expected, unresolved = _load_pinned_extractions(fixtures)

    assert expected == {}
    assert [p.name for p in unresolved] == ["orphan.expected.txt"]


# ============================================================================
# Undefined is not zero
# ============================================================================


def test_a_baseline_run_records_the_count_it_established() -> None:
    """A first run has no drift to report, and one number worth reporting.

    `drift_fraction` is None, not 0.0 -- there is nothing to compare against,
    which is a different statement from "compared, and nothing moved". The
    current count is recorded because it is the whole output of a baseline run
    and the figure the next run's drift will be measured from; the first draft
    dropped it and logged only `baseline: True`.
    """
    current = [_fetched(f"https://example.com/p{i}") for i in range(7)]
    alert = VolumeAnomalyCheck().check(_context(previous_manifest=[], current_manifest=current))

    assert not alert.fired
    assert alert.detail["baseline"] is True
    assert alert.detail["current_count"] == 7
    assert alert.detail["previous_count"] == 0
    assert alert.detail["drift_fraction"] is None
    assert "7" in alert.summary


def test_an_other_silo_rate_over_nothing_fetched_is_none() -> None:
    """With nothing fetched the rate is undefined, and says so.

    0.0 would read as "every fetched page was correctly siloed" on a run that
    fetched no pages at all, and would sit under the ceiling forever.
    """
    alert = CorpusShapeDriftCheck().check(_context(current_manifest=[]))

    assert not alert.fired
    assert alert.detail["other_silo_rate"] is None
    assert "unchecked" in alert.summary


def test_a_naive_timestamp_is_refused_by_the_log(tmp_path: Path) -> None:
    """An ISO row with no offset would misdate itself on a non-UTC machine."""
    with pytest.raises(ValueError, match="timezone-aware"):
        append_maintenance_log(
            tmp_path / "log.jsonl",
            run_id="r1",
            started_at=datetime(2026, 10, 1, 3, 0),  # naive
            finished_at=datetime(2026, 10, 1, 3, 5, tzinfo=timezone.utc),
            exit_code=0,
            pages_fetched=1,
            alerts=[],
        )
    assert not (tmp_path / "log.jsonl").exists(), "a refused row must not be half-written"


# ============================================================================
# The real ingest chain
# ============================================================================


def test_the_real_chain_rechunks_rather_than_replaying_the_old_chunk_file() -> None:
    """`_default_ingest_chain` must chunk what it crawled.

    Read out of the source rather than executed, for the same reason the chat
    client's `sawDone` guard is: the chain fetches `maryvillecollege.edu` and
    loads a sentence-transformer, so no test drives it. That makes a structural
    assertion the only guard available, and the thing it guards is worth a weak
    test -- the first implementation handed `incremental_reindex` a chunker that
    replayed the existing `corpus/chunks.jsonl`, which made the maintenance pass
    overwrite freshly crawled text with its pre-change version, drop brand-new
    pages from the index, and leave Alert 4 unable to fire at all.

    What this does not prove: that the chain runs, or that it produces a correct
    corpus. Only that it is still wired to re-chunk and to rewrite the chunk file.
    """
    source = inspect.getsource(run_module._default_ingest_chain)

    assert "ParagraphChunker" in source, "the production chunker is not wired in"
    assert "_PrechunkedChunker" not in source, "the chain is replaying persisted chunks again"
    assert "tmp_chunks_path.replace(chunks_path)" in source, "chunks.jsonl is not rewritten"
    assert "chunker = ParagraphChunker(" in source, "the chunker is named but not constructed"


def test_the_chain_reports_what_it_did_and_main_logs_the_page_count() -> None:
    """Whatever the chain returns, `pages_fetched` is what reaches the log row."""
    assert "pages_fetched" in inspect.getsource(run_module._default_ingest_chain)


# ============================================================================
# The first live run crashed in code no test had ever executed
# ============================================================================

_PAGE_HTML = (
    "<html><body><main><article><h1>Admissions</h1>"
    + "".join(
        f"<p>Maryville College admits students on a rolling basis, and section {i} "
        "of the admissions guide explains the deadlines, the required documents, "
        "the campus visit options and the financial aid timeline in detail.</p>"
        for i in range(12)
    )
    + "</article></main></body></html>"
)


def _store_and_manifest(tmp_path: Path, urls_with_html: dict[str, str | None]):
    """A real SnapshotStore and Manifest. A None html means no snapshot."""
    from mcrag.crawl.fetcher import SnapshotStore
    from mcrag.crawl.manifest import Manifest

    store = SnapshotStore(tmp_path / "raw")
    manifest = Manifest(path=tmp_path / "manifest.jsonl")
    for i, (url, html) in enumerate(urls_with_html.items()):
        manifest.consider(url, "sitemap")
        if html is None:
            continue
        digest = f"{i:064x}"
        store.put(url, html, digest)
        manifest.mark_fetched(url, http=200, content_hash=digest, bytes_len=len(html))
    store.save_index()
    return tmp_path / "raw", manifest


def test_pinned_lookup_extracts_from_a_real_snapshot(tmp_path: Path) -> None:
    """The function crashed with AttributeError (`store.load` does not exist)
    the first time it ran, because nothing had ever called it."""
    url = "https://www.maryvillecollege.edu/admissions"
    raw, manifest = _store_and_manifest(tmp_path, {url: _PAGE_HTML})

    status, extractions, unresolved = run_module._load_pinned_http_status_and_extractions(
        raw, [url], manifest
    )

    assert status == {url: 200}
    assert "rolling basis" in extractions[url]
    assert unresolved == []


def test_pinned_lookup_reports_a_page_with_no_snapshot_instead_of_dropping_it(
    tmp_path: Path,
) -> None:
    """A page nobody looked at must not get a status or an empty extraction,
    and must be counted, not skipped silently."""
    have = "https://www.maryvillecollege.edu/admissions"
    lacks_snapshot = "https://www.maryvillecollege.edu/athletics"
    not_in_manifest = "https://www.maryvillecollege.edu/unknown"
    raw, manifest = _store_and_manifest(tmp_path, {have: _PAGE_HTML, lacks_snapshot: None})

    status, extractions, unresolved = run_module._load_pinned_http_status_and_extractions(
        raw, [have, lacks_snapshot, not_in_manifest], manifest
    )

    assert set(status) == {have}
    assert set(extractions) == {have}
    assert unresolved == [lacks_snapshot, not_in_manifest]


def test_pinned_lookup_treats_a_corrupt_snapshot_as_unresolved(tmp_path: Path) -> None:
    url = "https://www.maryvillecollege.edu/admissions"
    raw, manifest = _store_and_manifest(tmp_path, {url: _PAGE_HTML})
    for snapshot in raw.rglob("*"):
        if snapshot.is_file() and snapshot.name != "index.json":
            snapshot.write_bytes(b"not gzip")

    status, extractions, unresolved = run_module._load_pinned_http_status_and_extractions(
        raw, [url], manifest
    )

    assert (status, extractions, unresolved) == ({}, {}, [url])


def test_a_crash_after_the_chain_still_writes_an_exit_1_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before the guard, a failure between the chain and the log row wrote no
    row, so the trigger read 'no maintenance run has ever been logged' for a
    run that had in fact failed."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "corpus").mkdir()
    (tmp_path / "data" / "maintenance").mkdir(parents=True)
    # corpus/manifest.jsonl is absent or unusable -> context assembly raises.
    (tmp_path / "corpus" / "manifest.jsonl").write_text("{not json\n", encoding="utf-8")

    code = run_module.main(ingest_chain=lambda: {"pages_fetched": 7})

    assert code == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "data/maintenance/maintenance_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["exit_code"] == 1
    assert rows[0]["pages_fetched"] == 7  # the chain did report it
    assert rows[0]["alerts"] == []
    assert rows[0]["error"]
