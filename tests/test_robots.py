"""Task 2 verification.

The fixture is the *live* robots.txt captured from www.maryvillecollege.edu on
2026-09-10, not an invented one. Tests written against a made-up robots file
prove the parser works on made-up robots files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcrag.crawl.ratelimit import RateLimiter
from mcrag.crawl.robots import (
    RobotsPolicy,
    UserAgentError,
    build_user_agent,
    require_identified,
)

FIXTURE = Path(__file__).parent / "fixtures" / "robots_maryvillecollege.txt"

# The five Disallow rules actually published by the site.
KNOWN_DISALLOWS = [
    ("/news/smart_catalog_block/anything", "/news/smart_catalog_block/*"),
    ("/academics/catalog/smart_catalog_course/bio101", "/academics/catalog/smart_catalog_course/*"),
    ("/news/smart_catalog_prog/nursing", "/news/smart_catalog_prog/*"),
    ("/wp-content/uploads/2024/handbook.pdf", "/wp-content/uploads/*"),
    ("/niche-direct-admissions.html", "/niche-direct-admissions.html"),
]


@pytest.fixture(scope="module")
def policy() -> RobotsPolicy:
    return RobotsPolicy(FIXTURE.read_text(encoding="utf-8"), user_agent="MaryvilleCollegeRAG/0.1")


class TestDisallowEnforcement:
    @pytest.mark.parametrize(("path", "expected_rule"), KNOWN_DISALLOWS)
    def test_each_known_disallow_is_refused(
        self, policy: RobotsPolicy, path: str, expected_rule: str
    ) -> None:
        decision = policy.decide(f"https://www.maryvillecollege.edu{path}")
        assert decision.allowed is False
        assert decision.rule is not None
        assert decision.rule.pattern == expected_rule

    @pytest.mark.parametrize(("path", "expected_rule"), KNOWN_DISALLOWS)
    def test_refusal_carries_a_manifest_ready_reason(
        self, policy: RobotsPolicy, path: str, expected_rule: str
    ) -> None:
        """The manifest needs the matched rule text, not a bare False."""
        reason = policy.decide(f"https://www.maryvillecollege.edu{path}").reason
        assert reason is not None
        assert reason.startswith("robots_disallow:")
        assert expected_rule in reason

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/admissions/",
            "/financial-aid/cost/",
            "/academics/majors/biology/",
            "/about/contact/",
        ],
    )
    def test_ordinary_pages_are_allowed(self, policy: RobotsPolicy, path: str) -> None:
        decision = policy.decide(f"https://www.maryvillecollege.edu{path}")
        assert decision.allowed is True
        assert decision.reason is None

    def test_allow_rule_is_honored(self, policy: RobotsPolicy) -> None:
        assert policy.allows("https://www.maryvillecollege.edu/orientation/schedule/")

    def test_allow_beats_disallow_on_equal_specificity(self) -> None:
        p = RobotsPolicy("User-agent: *\nDisallow: /x/\nAllow: /x/\n")
        assert p.allows("https://e.com/x/page")

    def test_longest_match_wins(self) -> None:
        p = RobotsPolicy("User-agent: *\nDisallow: /a/\nAllow: /a/keep/\n")
        assert p.allows("https://e.com/a/keep/page")
        assert not p.allows("https://e.com/a/other/page")

    def test_end_anchor(self) -> None:
        p = RobotsPolicy("User-agent: *\nDisallow: /*.pdf$\n")
        assert not p.allows("https://e.com/docs/f.pdf")
        assert p.allows("https://e.com/docs/f.pdf.html")

    def test_named_group_beats_wildcard_group(self) -> None:
        p = RobotsPolicy(
            "User-agent: *\nDisallow: /\n\nUser-agent: MaryvilleCollegeRAG\nDisallow: /private/\n",
            user_agent="MaryvilleCollegeRAG/0.1",
        )
        assert p.allows("https://e.com/public/")
        assert not p.allows("https://e.com/private/")

    def test_empty_disallow_means_allow_all(self) -> None:
        assert RobotsPolicy("User-agent: *\nDisallow:\n").allows("https://e.com/anything")


class TestSitemapDiscovery:
    def test_all_three_sitemaps_found(self, policy: RobotsPolicy) -> None:
        assert len(policy.sitemaps) == 3

    def test_news_sitemap_is_present_in_robots(self, policy: RobotsPolicy) -> None:
        """Exclusion is our policy decision, not an absence from robots.txt.

        The distinction matters: the manifest must record news URLs as
        ``policy:news_excluded``, which is only honest if we could have had them.
        """
        assert any("posts-post-1" in s for s in policy.sitemaps)

    def test_in_scope_sitemaps_present(self, policy: RobotsPolicy) -> None:
        assert any("posts-page-1" in s for s in policy.sitemaps)
        assert any("academic_programs-1" in s for s in policy.sitemaps)


class TestUserAgent:
    def test_contact_address_is_required(self) -> None:
        with pytest.raises(UserAgentError):
            build_user_agent("MaryvilleCollegeRAG", "0.1", "")
        with pytest.raises(UserAgentError):
            build_user_agent("MaryvilleCollegeRAG", "0.1", "a student")

    def test_email_and_url_contacts_both_accepted(self) -> None:
        assert "@" in build_user_agent("R", "0.1", "someone@example.edu")
        assert "https://" in build_user_agent("R", "0.1", "https://example.edu/about")

    def test_fetch_path_refuses_anonymous_agent(self) -> None:
        with pytest.raises(UserAgentError):
            require_identified("python-requests/2.31")
        assert require_identified("R/0.1 (+someone@example.edu)")


class TestRateLimiter:
    def test_ten_urls_take_at_least_ten_seconds(self) -> None:
        """The Task 2 verification, on a virtual clock.

        Real sleeping would put ten seconds into every test run to prove
        arithmetic. The clock and sleep are injected precisely so this stays
        honest and fast.
        """
        now = [0.0]
        waits: list[float] = []

        def clock() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            waits.append(seconds)
            now[0] += seconds

        limiter = RateLimiter(1.0, clock=clock, sleep=sleep)
        for _ in range(10):
            limiter.acquire()
            now[0] += 0.05  # each request itself takes a moment

        assert limiter.acquisitions == 10
        assert now[0] >= 9.0  # nine gaps of one second between ten requests
        assert sum(waits) == pytest.approx(9 * 0.95, abs=1e-6)

    def test_interval_is_global_not_per_caller(self) -> None:
        """Two threads sharing one limiter still produce one request per second."""
        import threading

        now = [0.0]
        lock = threading.Lock()

        def clock() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            with lock:
                now[0] += seconds

        limiter = RateLimiter(1.0, clock=clock, sleep=sleep)
        threads = [
            threading.Thread(target=lambda: [limiter.acquire() for _ in range(5)])
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert limiter.acquisitions == 10
        assert now[0] >= 9.0

    def test_crawl_delay_tightens_but_never_loosens(self) -> None:
        limiter = RateLimiter(1.0, clock=lambda: 0.0, sleep=lambda _: None)
        limiter.respect_crawl_delay(0.2)
        assert limiter.min_interval == 1.0
        limiter.respect_crawl_delay(5.0)
        assert limiter.min_interval == 5.0

    def test_rejects_nonpositive_rate(self) -> None:
        with pytest.raises(ValueError):
            RateLimiter(0)
