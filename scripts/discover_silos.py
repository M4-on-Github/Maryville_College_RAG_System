"""Task 8 step 1: a path-prefix histogram over the manifest, as data.

Offline: reads `corpus/manifest.jsonl`, writes `data/silo_histogram.csv`. Every
row is a two-level path prefix (e.g. `academics/course`) and how many fetched
pages fall under it. A single-level split is too coarse -- `academics` alone
is two thirds of the fetched corpus -- so this is the finest split that still
groups by URL structure rather than by individual page.

This is raw material for steps 2-4 of the discovery procedure in PLAN.md
Sec.2c, not a finished taxonomy: a prefix with real page counts still needs a
matching office (staff/office directory) before it becomes a silo. A prefix
with no office match is a topic, not a silo, per Task 8's governing test.

    python scripts/discover_silos.py
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.crawl.manifest import Manifest, Status  # noqa: E402

BASE = "https://www.maryvillecollege.edu"


def two_level_prefix(url: str, base: str) -> str:
    path = url.replace(base, "").strip("/")
    if not path:
        return "(root)"
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]


def histogram(manifest: Manifest, base: str = BASE) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in manifest.records.values():
        if record.status != Status.FETCHED:
            continue
        counts[two_level_prefix(record.canonical_url, base)] += 1
    return counts


def main() -> int:
    manifest = Manifest.load("corpus/manifest.jsonl")
    counts = histogram(manifest)

    out_path = Path("data/silo_histogram.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path_prefix", "fetched_pages"])
        for prefix, n in counts.most_common():
            writer.writerow([prefix, n])

    print(f"{len(counts)} distinct path prefixes, {sum(counts.values())} fetched pages")
    print(f"written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
