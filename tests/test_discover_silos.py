"""The path-prefix histogram: a pure function over manifest records."""

from __future__ import annotations

from datetime import datetime, timezone

from mcrag.crawl.manifest import Manifest
from scripts.discover_silos import histogram, two_level_prefix

BASE = "https://www.maryvillecollege.edu"


def _fetched_manifest(urls: list[str], tmp_path) -> Manifest:
    m = Manifest(path=tmp_path / "manifest.jsonl")
    for url in urls:
        m.consider(url, source="test")
        m.mark_fetched(
            url,
            http=200,
            content_hash="h",
            bytes_len=10,
            fetched_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )
    return m


def test_two_level_prefix_takes_the_first_two_segments():
    assert two_level_prefix(f"{BASE}/academics/course/bio101/", BASE) == "academics/course"


def test_two_level_prefix_falls_back_to_one_segment():
    assert two_level_prefix(f"{BASE}/about/", BASE) == "about"


def test_two_level_prefix_root_is_labeled():
    assert two_level_prefix(BASE, BASE) == "(root)"


def test_histogram_counts_only_fetched_pages_by_prefix(tmp_path):
    m = _fetched_manifest(
        [
            f"{BASE}/academics/course/a/",
            f"{BASE}/academics/course/b/",
            f"{BASE}/about/faith/",
        ],
        tmp_path,
    )
    counts = histogram(m, BASE)
    assert counts["academics/course"] == 2
    assert counts["about/faith"] == 1
    assert sum(counts.values()) == 3


def test_histogram_ignores_excluded_and_failed_records(tmp_path):
    m = Manifest(path=tmp_path / "manifest.jsonl")
    m.consider(f"{BASE}/news/x/", source="test")
    m.mark_excluded(f"{BASE}/news/x/", "policy:news_excluded")
    counts = histogram(m, BASE)
    assert counts == {}
