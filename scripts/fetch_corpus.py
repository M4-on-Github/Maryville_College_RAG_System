"""Fetch every in-scope URL in the manifest into the raw snapshot store.

This one puts real, sustained traffic on a live institutional site: roughly
2,450 requests at one per second, about 41 minutes. Run it deliberately.

    python scripts/fetch_corpus.py --contact you@example.edu --sample 30  # rehearsal
    python scripts/fetch_corpus.py --contact you@example.edu              # full pass

Interrupting is safe. The pass state file records what has been done, and a
restart picks up from there rather than starting over.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.crawl.fetcher import CrawlPass, Fetcher, SnapshotStore  # noqa: E402
from mcrag.crawl.manifest import Manifest  # noqa: E402
from mcrag.crawl.ratelimit import RateLimiter  # noqa: E402
from mcrag.crawl.robots import RobotsPolicy, build_user_agent  # noqa: E402
from mcrag.crawl.sitemap import fetch_queue  # noqa: E402

BASE = "https://www.maryvillecollege.edu"


def stratified_sample(manifest: Manifest, urls: list[str], n: int) -> list[str]:
    """Spread a sample of ``n`` URLs across sitemaps and top-level path prefixes.

    Deterministic: strata are visited round-robin in sorted order and each is
    drawn from in sorted order, so the same queue always yields the same sample.
    A seeded random draw would do as well; this is easier to eyeball.
    """
    strata: dict[tuple[str, str], list[str]] = {}
    for url in urls:
        record = manifest.records[url]
        prefix = url.replace(BASE, "").strip("/").split("/")[0] or "(root)"
        strata.setdefault((record.source, prefix), []).append(url)

    picked: list[str] = []
    keys = sorted(strata)
    depth = 0
    while len(picked) < n and any(len(strata[k]) > depth for k in keys):
        for key in keys:
            bucket = strata[key]
            if depth < len(bucket):
                picked.append(bucket[depth])
                if len(picked) == n:
                    return picked
        depth += 1
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contact", required=True, help="email or URL for the crawl User-Agent")
    parser.add_argument("--manifest", default="corpus/manifest.jsonl", type=Path)
    parser.add_argument("--raw", default="corpus/raw", type=Path)
    parser.add_argument("--state", default="corpus/.crawl_pass.json", type=Path)
    parser.add_argument("--rps", type=float, default=1.0, help="requests per second ceiling")
    parser.add_argument("--limit", type=int, default=0, help="stop after N URLs (0 = all)")
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="fetch N URLs spread across every source sitemap and path prefix, "
        "rather than the first N. Use this for a rehearsal: the first N URLs "
        "alphabetically are all one silo, which tells you nothing about the rest.",
    )
    args = parser.parse_args()

    if args.rps > 1.0:
        print("refusing to crawl faster than 1 req/s against a live site", file=sys.stderr)
        return 2

    user_agent = build_user_agent("MaryvilleCollegeRAG", "0.1", args.contact)
    robots = RobotsPolicy.fetch(BASE, user_agent)
    limiter = RateLimiter(args.rps)
    limiter.respect_crawl_delay(robots.crawl_delay())

    manifest = Manifest.load(args.manifest)
    if not manifest.records:
        print(f"no manifest at {args.manifest} -- run scripts/enumerate_corpus.py", file=sys.stderr)
        return 1

    queue = fetch_queue(manifest)
    state = CrawlPass(args.state)
    unvisited = [u for u in queue if not state.visited(u)]
    if args.sample:
        remaining = stratified_sample(manifest, unvisited, args.sample)
    elif args.limit:
        remaining = unvisited[: args.limit]
    else:
        remaining = unvisited

    print(
        f"user agent: {user_agent}\n"
        f"queue: {len(queue)} URLs, {len(queue) - len(unvisited)} already done this pass\n"
        f"fetching {len(remaining)} at {args.rps} req/s "
        f"(~{len(remaining) / max(args.rps, 0.01) / 60:.0f} min)"
    )

    fetcher = Fetcher(user_agent, robots, limiter, SnapshotStore(args.raw))
    started = time.monotonic()

    def progress(i: int, total: int, url: str, stats: dict[str, int]) -> None:
        if i % 25 == 0 or i == total:
            elapsed = time.monotonic() - started
            print(
                f"  {i}/{total}  {elapsed / 60:5.1f}m  "
                f"new={stats['new_snapshots']} unchanged={stats['unchanged']} "
                f"failed={stats['failed']}",
                flush=True,
            )

    try:
        stats = fetcher.crawl(
            manifest,
            remaining,
            pass_state=state,
            on_progress=progress,
            close_pass=len(remaining) == len(unvisited) and not args.sample,
        )
    except KeyboardInterrupt:
        manifest.save()
        fetcher.store.save_index()
        state.save()
        print("\ninterrupted; progress saved. Rerun to resume.", file=sys.stderr)
        return 130

    print(
        f"\ndone in {(time.monotonic() - started) / 60:.1f} min\n"
        f"  changed/new:    {stats['fetched']}\n"
        f"  unchanged:      {stats['unchanged']}\n"
        f"  new snapshots:  {stats['new_snapshots']}\n"
        f"  failed:         {stats['failed']}\n"
        f"  robots-refused: {stats['forbidden']}"
    )
    if stats["failed"]:
        print("  (failures are recorded in the manifest with their status codes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
