"""``policy:pending_fetch`` is a queue position, not a decision.

Before this fix, a URL cleared for fetching but not yet fetched was tallied
as ``excluded`` under ``by_status`` and as ``policy`` under
``by_reason_class`` -- so a corpus mid-crawl looked like it had dropped
whatever share of pages were simply still waiting in the queue.
"""

from __future__ import annotations

from pathlib import Path

from mcrag.crawl.manifest import Manifest
from scripts.coverage import report


def _manifest(tmp_path: Path) -> Manifest:
    manifest = Manifest(path=tmp_path / "manifest.jsonl")
    manifest.consider("https://www.maryvillecollege.edu/fetched/", source="pages")
    manifest.mark_fetched(
        "https://www.maryvillecollege.edu/fetched/",
        http=200,
        content_hash="abc123",
        bytes_len=1000,
    )
    manifest.consider("https://www.maryvillecollege.edu/events/x/", source="events")
    manifest.mark_excluded("https://www.maryvillecollege.edu/events/x/", "policy:events_dropped")
    manifest.consider("https://www.maryvillecollege.edu/queued-1/", source="pages")
    manifest.mark_excluded("https://www.maryvillecollege.edu/queued-1/", "policy:pending_fetch")
    manifest.consider("https://www.maryvillecollege.edu/queued-2/", source="pages")
    manifest.mark_excluded("https://www.maryvillecollege.edu/queued-2/", "policy:pending_fetch")
    return manifest


def test_pending_fetch_is_not_counted_as_excluded(tmp_path):
    text = report(_manifest(tmp_path))
    assert "2 still queued" in text
    # Of 4 URLs total, 2 are queued and 2 are decided: 1 fetched, 1 excluded.
    status_section = text.split("By status")[1].split("By reason class")[0]
    assert "fetched" in status_section and "1" in status_section
    assert "excluded" in status_section


def test_pending_fetch_is_absent_from_the_reason_class_table(tmp_path):
    text = report(_manifest(tmp_path))
    reason_section = text.split("By reason class")[1].split("By source sitemap")[0]
    assert "pending_fetch" not in reason_section


def test_pending_fetch_is_absent_from_policy_detail(tmp_path):
    text = report(_manifest(tmp_path))
    assert "policy:pending_fetch" not in text
    assert "policy:events_dropped" in text


def test_decided_total_excludes_the_queue(tmp_path):
    text = report(_manifest(tmp_path))
    assert "cover the 2 decided URLs" in text


def test_a_fully_decided_manifest_needs_no_queue_line(tmp_path):
    manifest = Manifest(path=tmp_path / "manifest.jsonl")
    manifest.consider("https://www.maryvillecollege.edu/fetched/", source="pages")
    manifest.mark_fetched(
        "https://www.maryvillecollege.edu/fetched/",
        http=200,
        content_hash="abc123",
        bytes_len=1000,
    )
    text = report(manifest)
    assert "still queued" not in text
