"""Task 4 verification: every URL considered is accounted for, with a reason."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcrag.crawl.manifest import (
    Manifest,
    ManifestError,
    ManifestRecord,
    Status,
)
from mcrag.crawl.ratelimit import RateLimiter
from mcrag.crawl.robots import RobotsPolicy
from mcrag.crawl.sitemap import (
    SCOPE,
    Disposition,
    SitemapCrawler,
    UnknownSitemapError,
    classify,
    pending_fetch,
)

ROBOTS = (Path(__file__).parent / "fixtures" / "robots_maryvillecollege.txt").read_text(
    encoding="utf-8"
)
UA = "MaryvilleCollegeRAG/0.1 (+someone@example.edu)"

# The 29 sitemaps actually published, captured 2026-09-10.
PUBLISHED_SITEMAPS = [
    "posts-post-1", "posts-page-1", "posts-staff-1", "posts-academic_programs-1",
    "posts-product-1", "posts-student_study-1", "posts-external_relation-1",
    "posts-academic_course-1", "posts-smart_catalog_course-1", "posts-smart_catalog_block-1",
    "posts-smart_catalog_prog-1", "posts-maxgallery-1", "posts-rl_gallery-1",
    "posts-tribe_venue-1", "posts-tribe_organizer-1", "posts-tribe_events-1",
    "posts-tec_session-1", "taxonomies-category-1", "taxonomies-post_tag-1",
    "taxonomies-post_format-1", "taxonomies-wpa-stats-type-1", "taxonomies-department-1",
    "taxonomies-divisions-1", "taxonomies-product_cat-1", "taxonomies-alumni_note_type-1",
    "taxonomies-personnel-1", "taxonomies-media_category-1", "taxonomies-tribe_events_cat-1",
    "taxonomies-tec_location-1",
]


class TestRecordDiscipline:
    def test_non_fetched_record_without_a_reason_is_refused(self) -> None:
        with pytest.raises(ManifestError, match="needs a reason"):
            ManifestRecord(url="https://e.com/a", source="s", status=Status.EXCLUDED)

    def test_bare_reason_without_a_class_prefix_is_refused(self) -> None:
        """'excluded' with no class cannot be counted, so it fails review."""
        with pytest.raises(ManifestError, match="no known class prefix"):
            ManifestRecord(
                url="https://e.com/a", source="s", status=Status.EXCLUDED, reason="excluded"
            )

    @pytest.mark.parametrize(
        "reason",
        [
            "robots_disallow:Disallow: /wp-content/uploads/*",
            "policy:news_excluded",
            "http_error",
            "extraction_empty",
            "unchanged_hash",
        ],
    )
    def test_each_reason_class_is_accepted(self, reason: str) -> None:
        record = ManifestRecord(
            url="https://e.com/a", source="s", status=Status.EXCLUDED, reason=reason
        )
        assert record.reason_class in {
            "robots_disallow", "policy", "http_error", "extraction_empty", "unchanged_hash"
        }

    def test_fetched_record_needs_no_reason(self) -> None:
        record = ManifestRecord(url="https://e.com/a", source="s", status=Status.FETCHED)
        assert record.reason is None

    def test_redirect_collapses_to_the_final_url(self) -> None:
        record = ManifestRecord(
            url="https://e.com/faculty/x/",
            final_url="https://e.com/academics/faculty/x/",
            source="posts-staff-1",
            status=Status.FETCHED,
        )
        assert record.canonical_url == "https://e.com/academics/faculty/x/"

    def test_round_trips_through_json(self) -> None:
        original = ManifestRecord(
            url="https://e.com/a",
            source="posts-page-1",
            status=Status.FETCHED,
            http=200,
            content_hash="abc",
            fetched_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
            bytes=48213,
            extracted_chars=3117,
            silo=("finaid",),
            chunks=6,
        )
        assert ManifestRecord.from_json(original.to_json()) == original


class TestScopeTable:
    def test_every_published_sitemap_has_a_disposition(self) -> None:
        """The whole point of the table: no sitemap falls through."""
        for name in PUBLISHED_SITEMAPS:
            rule = classify(f"https://www.maryvillecollege.edu/wp-sitemap-{name}.xml")
            assert rule.disposition in (Disposition.IN_SCOPE, Disposition.EXCLUDED)

    def test_an_unlisted_sitemap_stops_the_crawl(self) -> None:
        """A new post type must prompt a decision, not be silently dropped."""
        with pytest.raises(UnknownSitemapError):
            classify("https://www.maryvillecollege.edu/wp-sitemap-posts-podcast-1.xml")

    def test_posts_post_does_not_shadow_posts_page(self) -> None:
        """Substring matching is a trap here; longest key must win."""
        page = classify("https://x/wp-sitemap-posts-page-1.xml")
        post = classify("https://x/wp-sitemap-posts-post-1.xml")
        assert page.disposition is Disposition.IN_SCOPE
        assert post.reason == "policy:news_excluded"

    def test_every_exclusion_carries_a_class_prefixed_reason(self) -> None:
        for rule in SCOPE:
            if rule.disposition is Disposition.EXCLUDED:
                assert ":" in rule.reason
                assert rule.reason.split(":")[0] == "policy"

    def test_news_is_excluded_by_policy_not_by_omission(self) -> None:
        """It is in the index and we could have had it. That is what makes the
        manifest's 845 news records an honest statement rather than a gap."""
        assert classify("https://x/wp-sitemap-posts-post-1.xml").reason == "policy:news_excluded"


class FakeCrawler(SitemapCrawler):
    """Serves canned sitemap XML so enumeration is tested without the network."""

    def __init__(self, pages: dict[str, str], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.pages = pages
        self.requested: list[str] = []

    def _get(self, url: str) -> str:
        self.requested.append(url)
        return self.pages[url]


def urlset(*entries: tuple[str, str | None]) -> str:
    body = "".join(
        f"<url><loc>{u}</loc>{f'<lastmod>{m}</lastmod>' if m else ''}</url>" for u, m in entries
    )
    return f'<?xml version="1.0"?><urlset>{body}</urlset>'


@pytest.fixture
def crawler(tmp_path: Path) -> FakeCrawler:
    base = "https://www.maryvillecollege.edu"
    pages = {
        f"{base}/wp-sitemap.xml": (
            "<sitemapindex>"
            f"<sitemap><loc>{base}/wp-sitemap-posts-page-1.xml</loc></sitemap>"
            f"<sitemap><loc>{base}/wp-sitemap-posts-post-1.xml</loc></sitemap>"
            f"<sitemap><loc>{base}/wp-sitemap-posts-smart_catalog_course-1.xml</loc></sitemap>"
            "</sitemapindex>"
        ),
        f"{base}/wp-sitemap-posts-page-1.xml": urlset(
            (f"{base}/about/", "2026-01-02"),
            (f"{base}/financial-aid/", "2026-01-03"),
            (f"{base}/wp-content/uploads/2024/handbook.pdf", None),
        ),
        f"{base}/wp-sitemap-posts-post-1.xml": urlset(
            (f"{base}/news/2017/big-gift/", "2026-08-01"),
            (f"{base}/news/2018/other/", "2026-08-01"),
        ),
        f"{base}/wp-sitemap-posts-smart_catalog_course-1.xml": urlset(
            (f"{base}/academics/catalog/smart_catalog_course/bio101/", None),
        ),
    }
    return FakeCrawler(
        pages,
        base_url=base,
        user_agent=UA,
        robots=RobotsPolicy(ROBOTS, user_agent=UA),
        limiter=RateLimiter(1.0, clock=lambda: 0.0, sleep=lambda _: None),
    )


class TestEnumeration:
    def test_every_url_considered_lands_in_the_manifest(
        self, crawler: FakeCrawler, tmp_path: Path
    ) -> None:
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        stats = crawler.enumerate_into(manifest)
        assert stats["considered"] == 6
        assert stats["listings"] == 6
        assert len(manifest) == 6

    def test_excluded_urls_stay_in_the_manifest(
        self, crawler: FakeCrawler, tmp_path: Path
    ) -> None:
        """Exclusion is recorded, not silent."""
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        crawler.enumerate_into(manifest)
        news = [r for r in manifest.records.values() if "/news/" in r.url]
        assert len(news) == 2
        assert all(r.reason == "policy:news_excluded" for r in news)

    def test_no_news_url_is_ever_fetched(self, crawler: FakeCrawler, tmp_path: Path) -> None:
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        crawler.enumerate_into(manifest)
        assert not [r for r in manifest.fetched() if "/news/" in r.url]

    def test_duplicate_listings_collapse_to_one_record(
        self, crawler: FakeCrawler, tmp_path: Path
    ) -> None:
        """35 URLs are published in two sitemaps. One page gets one record."""
        base = "https://www.maryvillecollege.edu"
        crawler.pages[f"{base}/wp-sitemap-posts-page-1.xml"] = urlset(
            (f"{base}/about/", "2026-01-02"),
            (f"{base}/about/", "2026-01-02"),
        )
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        stats = crawler.enumerate_into(manifest)
        assert stats["duplicates"] == 1
        assert stats["listings"] == stats["considered"] + stats["duplicates"]
        assert manifest.reconcile(stats["considered"])["balanced"] is True

    def test_robots_beats_the_scope_table(
        self, crawler: FakeCrawler, tmp_path: Path
    ) -> None:
        """A catalog URL is recorded as robots-forbidden, not as our policy.

        The scope table also excludes that sitemap, so order decides the reason.
        Attributing the corpus's largest gap to a choice we made, when the site
        actually forbade it, would misdescribe the limitation in the writeup.
        """
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        crawler.enumerate_into(manifest)
        catalog = manifest.records[
            "https://www.maryvillecollege.edu/academics/catalog/smart_catalog_course/bio101/"
        ]
        assert catalog.reason_class == "robots_disallow"
        assert "smart_catalog_course" in catalog.reason

    def test_robots_blocked_url_names_the_rule(
        self, crawler: FakeCrawler, tmp_path: Path
    ) -> None:
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        crawler.enumerate_into(manifest)
        pdf = manifest.records[
            "https://www.maryvillecollege.edu/wp-content/uploads/2024/handbook.pdf"
        ]
        assert pdf.reason_class == "robots_disallow"
        assert "/wp-content/uploads/*" in pdf.reason

    def test_robots_is_checked_before_any_fetch_is_attempted(
        self, crawler: FakeCrawler, tmp_path: Path
    ) -> None:
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        crawler.enumerate_into(manifest)
        queue = pending_fetch(manifest)
        assert all(crawler.robots.allows(u, UA) for u in queue)
        assert "handbook.pdf" not in " ".join(queue)

    def test_lastmod_is_recorded(self, crawler: FakeCrawler, tmp_path: Path) -> None:
        """Recorded, and documented as untrusted: this install stamps a 2026
        lastmod on a 2017 post, so only the content hash decides change."""
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        crawler.enumerate_into(manifest)
        assert manifest.records["https://www.maryvillecollege.edu/about/"].lastmod == "2026-01-02"
        stale = manifest.records["https://www.maryvillecollege.edu/news/2017/big-gift/"]
        assert stale.lastmod == "2026-08-01"

    def test_work_queue_is_exactly_the_permitted_in_scope_urls(
        self, crawler: FakeCrawler, tmp_path: Path
    ) -> None:
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        crawler.enumerate_into(manifest)
        assert pending_fetch(manifest) == [
            "https://www.maryvillecollege.edu/about/",
            "https://www.maryvillecollege.edu/financial-aid/",
        ]

    def test_nothing_is_left_undecided(self, crawler: FakeCrawler, tmp_path: Path) -> None:
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        crawler.enumerate_into(manifest)
        assert manifest.undecided() == []


class TestReconciliation:
    def test_totals_balance_against_the_enumerated_count(
        self, crawler: FakeCrawler, tmp_path: Path
    ) -> None:
        """The coverage claim rests on this arithmetic."""
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        stats = crawler.enumerate_into(manifest)
        report = manifest.reconcile(stats["considered"])
        assert report["balanced"] is True
        assert report["undecided"] == 0

    def test_imbalance_is_reported_not_hidden(self, tmp_path: Path) -> None:
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        manifest.consider("https://e.com/a", source="s")
        assert manifest.reconcile(expected_total=5)["balanced"] is False

    def test_persists_and_reloads(self, crawler: FakeCrawler, tmp_path: Path) -> None:
        path = tmp_path / "manifest.jsonl"
        manifest = Manifest(path=path)
        crawler.enumerate_into(manifest)
        manifest.mark_fetched(
            "https://www.maryvillecollege.edu/about/",
            http=200,
            content_hash="deadbeef",
            bytes_len=1234,
        )
        manifest.save()

        reloaded = Manifest.load(path)
        assert len(reloaded) == len(manifest)
        assert reloaded.records["https://www.maryvillecollege.edu/about/"].content_hash == "deadbeef"
        assert reloaded.by_status()["fetched"] == 1

    def test_status_transitions_are_recorded(self, tmp_path: Path) -> None:
        manifest = Manifest(path=tmp_path / "manifest.jsonl")
        url = "https://e.com/a"
        manifest.consider(url, source="posts-page-1")
        manifest.mark_failed(url, http=404, attempts=3)
        assert manifest.records[url].status == Status.FAILED
        assert manifest.records[url].attempts == 3

        manifest.mark_skipped(url, content_hash="abc")
        assert manifest.records[url].reason == "unchanged_hash"

        manifest.mark_extraction_empty(url)
        assert manifest.records[url].reason == "extraction_empty"
        assert manifest.records[url].extracted_chars == 0
