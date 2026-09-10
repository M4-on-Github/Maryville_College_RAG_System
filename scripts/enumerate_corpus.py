"""Walk every published sitemap and write the crawl manifest.

Enumeration only. Nothing is fetched beyond the sitemap XML itself, so this is
about thirty requests at one per second and safe to re-run.

    python scripts/enumerate_corpus.py --contact you@example.edu
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.crawl.manifest import Manifest  # noqa: E402
from mcrag.crawl.ratelimit import RateLimiter  # noqa: E402
from mcrag.crawl.robots import RobotsPolicy, build_user_agent  # noqa: E402
from mcrag.crawl.sitemap import SitemapCrawler  # noqa: E402

BASE = "https://www.maryvillecollege.edu"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contact", required=True, help="email or URL for the crawl User-Agent")
    parser.add_argument("--manifest", default="corpus/manifest.jsonl", type=Path)
    parser.add_argument("--rps", type=float, default=1.0)
    args = parser.parse_args()

    user_agent = build_user_agent("MaryvilleCollegeRAG", "0.1", args.contact)
    print(f"user agent: {user_agent}")

    robots = RobotsPolicy.fetch(BASE, user_agent)
    print(f"robots.txt: {len(robots.sitemaps)} sitemaps declared, "
          f"crawl-delay {robots.crawl_delay() or 'unset'}")

    limiter = RateLimiter(args.rps)
    limiter.respect_crawl_delay(robots.crawl_delay())

    manifest = Manifest.load(args.manifest)
    crawler = SitemapCrawler(BASE, user_agent, robots, limiter)

    stats = crawler.enumerate_into(manifest)
    manifest.save()

    print(
        f"\n{stats['sitemaps']} sitemaps, {stats['considered']} URLs considered\n"
        f"  in scope and permitted: {stats['in_scope']}\n"
        f"  blocked by robots:      {stats['robots_blocked']}\n"
        f"  manifest written to {args.manifest}"
    )

    report = manifest.reconcile(stats["considered"])
    if not report["balanced"]:
        print(f"\n!! manifest does not balance: {report}", file=sys.stderr)
        return 1
    if report["undecided"]:
        print(f"\n!! {report['undecided']} URLs left undecided", file=sys.stderr)
        return 1
    print("  reconciled: every URL considered has a status and a reason")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
