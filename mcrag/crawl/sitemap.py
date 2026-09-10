"""Sitemap enumeration and the scope policy applied to it.

The site publishes a sitemap index naming 29 sitemaps and 5,514 URLs (see
`decisions/0001-corpus-scope.md`). Scope is a **declared table**, not a set of
conditionals scattered through the crawler: every sitemap is listed with a
disposition, and a sitemap that appears in the index but not in the table is an
error rather than a silent omission.

That last property is the point. The site can add a post type at any time; if it
does, the crawl stops and asks rather than quietly ignoring it.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from mcrag.crawl.manifest import Manifest, Status
from mcrag.crawl.ratelimit import RateLimiter
from mcrag.crawl.robots import RobotsPolicy, require_identified

_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.I | re.S)
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>", re.I)


class Disposition(StrEnum):
    IN_SCOPE = "in_scope"
    EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class SitemapRule:
    """One sitemap's disposition, with the reason spelled out if excluded."""

    key: str  # substring identifying the sitemap file
    disposition: Disposition
    reason: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.disposition is Disposition.EXCLUDED and not self.reason:
            raise ValueError(f"{self.key}: an excluded sitemap needs a policy reason")


# The scope table. Every sitemap in the published index appears exactly once.
SCOPE: tuple[SitemapRule, ...] = (
    # ---- in scope --------------------------------------------------------
    SitemapRule("posts-page", Disposition.IN_SCOPE, note="the core corpus"),
    SitemapRule("posts-academic_course", Disposition.IN_SCOPE, note="course records"),
    SitemapRule("posts-academic_programs", Disposition.IN_SCOPE, note="programs of study"),
    SitemapRule("posts-staff", Disposition.IN_SCOPE, note="office and contact source"),
    SitemapRule("posts-student_study", Disposition.IN_SCOPE, note="senior studies"),
    SitemapRule("taxonomies-divisions", Disposition.IN_SCOPE, note="the site's own taxonomy"),
    SitemapRule("taxonomies-department", Disposition.IN_SCOPE, note="the site's own taxonomy"),
    # ---- dated content ---------------------------------------------------
    SitemapRule(
        "posts-post",
        Disposition.EXCLUDED,
        "policy:news_excluded",
        "845 dated posts; a 2017 story carries a 2026 lastmod",
    ),
    SitemapRule(
        "posts-tribe_events", Disposition.EXCLUDED, "policy:events_excluded", "490 dated events"
    ),
    SitemapRule(
        "posts-tribe_venue", Disposition.EXCLUDED, "policy:events_excluded", "venue stubs"
    ),
    SitemapRule(
        "posts-tribe_organizer", Disposition.EXCLUDED, "policy:events_excluded", "organizer stubs"
    ),
    SitemapRule(
        "posts-tec_session", Disposition.EXCLUDED, "policy:events_excluded", "event sessions"
    ),
    SitemapRule(
        "taxonomies-tribe_events_cat", Disposition.EXCLUDED, "policy:events_excluded", ""
    ),
    SitemapRule("taxonomies-tec_location", Disposition.EXCLUDED, "policy:events_excluded", ""),
    # ---- robots-disallowed at the URL level, listed for the record -------
    SitemapRule(
        "posts-smart_catalog_course",
        Disposition.EXCLUDED,
        "policy:robots_blocked_type",
        "851 URLs under a Disallow; /academics/course/ carries the same data",
    ),
    SitemapRule(
        "posts-smart_catalog_prog",
        Disposition.EXCLUDED,
        "policy:robots_blocked_type",
        "138 URLs; THE degree-requirements view, and the corpus's largest gap",
    ),
    SitemapRule(
        "posts-smart_catalog_block", Disposition.EXCLUDED, "policy:robots_blocked_type", "157 URLs"
    ),
    # ---- thin or non-prose ----------------------------------------------
    SitemapRule("posts-product", Disposition.EXCLUDED, "policy:non_prose", "store items"),
    SitemapRule("taxonomies-product_cat", Disposition.EXCLUDED, "policy:non_prose", ""),
    SitemapRule("posts-maxgallery", Disposition.EXCLUDED, "policy:non_prose", "image galleries"),
    SitemapRule("posts-rl_gallery", Disposition.EXCLUDED, "policy:non_prose", "image galleries"),
    SitemapRule("taxonomies-media_category", Disposition.EXCLUDED, "policy:non_prose", ""),
    SitemapRule(
        "posts-external_relation", Disposition.EXCLUDED, "policy:non_prose", "8 partner stubs"
    ),
    # ---- news-derived taxonomies ----------------------------------------
    SitemapRule("taxonomies-category", Disposition.EXCLUDED, "policy:news_excluded", ""),
    SitemapRule("taxonomies-post_tag", Disposition.EXCLUDED, "policy:news_excluded", ""),
    SitemapRule("taxonomies-post_format", Disposition.EXCLUDED, "policy:news_excluded", ""),
    SitemapRule("taxonomies-alumni_note_type", Disposition.EXCLUDED, "policy:news_excluded", ""),
    SitemapRule(
        "taxonomies-wpa-stats-type", Disposition.EXCLUDED, "policy:non_prose", "analytics terms"
    ),
    SitemapRule(
        "taxonomies-personnel",
        Disposition.EXCLUDED,
        "policy:duplicate_view",
        "87 term pages listing staff already covered by posts-staff",
    ),
)


class UnknownSitemapError(ValueError):
    """A sitemap in the index that the scope table does not mention.

    Deliberately fatal. The site adding a post type should stop the crawl and
    prompt a decision, not be silently dropped from a corpus we then describe as
    complete.
    """


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    url: str
    lastmod: str | None
    sitemap: str

    @property
    def source(self) -> str:
        """Manifest ``source`` field: the sitemap file, without the extension."""
        return self.sitemap.rsplit("/", 1)[-1].removesuffix(".xml")


def classify(sitemap_url: str) -> SitemapRule:
    name = sitemap_url.rsplit("/", 1)[-1]
    matches = [r for r in SCOPE if r.key in name]
    if not matches:
        raise UnknownSitemapError(
            f"{name} is not in the scope table. A new post type must be given a "
            "disposition explicitly -- silently dropping it would leave the corpus "
            "incomplete while the coverage report still claimed it balanced."
        )
    # Longest key wins: "posts-post" must not shadow "posts-page" or vice versa.
    return max(matches, key=lambda r: len(r.key))


class SitemapCrawler:
    """Fetches the index, enumerates URLs, and writes every one to the manifest.

    Nothing is dropped between enumeration and the manifest. A URL is registered
    the moment it is seen, then a disposition is applied to it -- so a URL cannot
    vanish by falling through a branch.
    """

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        robots: RobotsPolicy,
        limiter: RateLimiter,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url
        self.user_agent = require_identified(user_agent)
        self.robots = robots
        self.limiter = limiter
        self.timeout = timeout

    # ---- fetching ------------------------------------------------------

    def _get(self, url: str) -> str:
        self.limiter.acquire()
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8", "replace")

    def index_urls(self) -> list[str]:
        """The sitemaps named by robots.txt, or by the wp-sitemap index."""
        parts = urlsplit(self.base_url)
        index = f"{parts.scheme}://{parts.netloc}/wp-sitemap.xml"
        return _LOC.findall(self._get(index))

    def entries(self, sitemap_url: str) -> list[SitemapEntry]:
        body = self._get(sitemap_url)
        found: list[SitemapEntry] = []
        for block in _URL_BLOCK.findall(body):
            loc = _LOC.search(block)
            if not loc:
                continue
            lastmod = _LASTMOD.search(block)
            found.append(
                SitemapEntry(
                    url=_unescape(loc.group(1)),
                    lastmod=lastmod.group(1) if lastmod else None,
                    sitemap=sitemap_url,
                )
            )
        if not found:  # a sitemap with <loc> but no <url> wrappers
            found = [SitemapEntry(_unescape(u), None, sitemap_url) for u in _LOC.findall(body)]
        return found

    # ---- the enumeration pass -------------------------------------------

    def enumerate_into(self, manifest: Manifest) -> dict[str, int]:
        """Walk every sitemap and give every URL a status and a reason.

        ``lastmod`` is recorded and **never trusted**: this WordPress install
        stamps a current date on posts written years earlier, so it is a cheap
        pre-filter for the incremental crawl and nothing more. The content hash
        is what decides whether a page changed.
        """
        stats = {
            "sitemaps": 0,
            "listings": 0,
            "considered": 0,
            "duplicates": 0,
            "in_scope": 0,
            "robots_blocked": 0,
        }
        seen: set[str] = set()

        for sitemap_url in self.index_urls():
            rule = classify(sitemap_url)
            stats["sitemaps"] += 1

            for entry in self.entries(sitemap_url):
                stats["listings"] += 1
                if entry.url in seen:
                    # The same URL is published in more than one sitemap. It is
                    # one page, so it gets one record; the duplicate listing is
                    # counted so the reconciliation still adds up.
                    stats["duplicates"] += 1
                    continue
                seen.add(entry.url)
                manifest.consider(entry.url, source=entry.source, lastmod=entry.lastmod)
                stats["considered"] += 1

                # Robots is checked FIRST, before the scope table. A URL the
                # site forbids is recorded as forbidden, naming the rule --
                # calling it a policy exclusion of ours would misattribute the
                # single largest gap in the corpus to a choice we made.
                decision = self.robots.decide(entry.url, self.user_agent)
                if not decision.allowed:
                    manifest.mark_excluded(entry.url, decision.reason)  # type: ignore[arg-type]
                    stats["robots_blocked"] += 1
                    continue

                if rule.disposition is Disposition.EXCLUDED:
                    manifest.mark_excluded(entry.url, rule.reason)  # type: ignore[arg-type]
                    continue

                # In scope and permitted. Left pending until the fetcher runs;
                # the queue is exactly the set of records in this state.
                manifest.mark_excluded(entry.url, "policy:pending_fetch")
                stats["in_scope"] += 1

        return stats


def pending_fetch(manifest: Manifest) -> list[str]:
    """URLs cleared for fetching. This is the fetcher's work queue."""
    return sorted(
        r.url
        for r in manifest.records.values()
        if r.status == Status.EXCLUDED and r.reason == "policy:pending_fetch"
    )


def _unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#039;", "'")
    )
