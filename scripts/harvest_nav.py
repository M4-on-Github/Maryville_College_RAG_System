"""Task 8 step 2: top-nav and breadcrumb trails, harvested as data.

Offline: reads the homepage snapshot already in `corpus/raw` (no new network
traffic) for the site's own top-level navigation, and `corpus/extracted/documents.jsonl`
for breadcrumb roots. Writes two files under `data/`:

- `nav_top_level.csv` — the site's own declared top-level sections (main
  navbar dropdowns plus the flat utility-bar items), each with its child
  links as harvested from the homepage markup.
- `breadcrumb_vs_path.csv` — for every extracted document that carries a
  JSON-LD breadcrumb, its first breadcrumb label next to its two-level path
  prefix. A mismatch here is a genuine nav/URL disagreement (per Task 8 step
  2: "nav/URL disagreements recorded, not silently resolved"), not something
  this script tries to reconcile.

    python scripts/harvest_nav.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.crawl.fetcher import SnapshotStore  # noqa: E402

HOMEPAGE = "https://www.maryvillecollege.edu/"
_TAG = re.compile(r"<[^>]+>")

# The two navbars this site actually ships: the main dropdown menu (desktop)
# and the flat utility bar (audience-based quicklinks like Alumni, Families).
# Both are Bootstrap navbars; there is no ARIA landmark that names either one,
# so the split found here was done by hand, once, by reading the homepage
# markup -- not by a heuristic that would silently break on a template change.
_DROPDOWN_TRIGGER = re.compile(
    r'<a[^>]*class="dropdown-toggle"[^>]*href="#"[^>]*>(.*?)<', re.S
)
_LINK = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def _clean(text: str) -> str:
    return _TAG.sub("", text).strip()


def harvest_main_nav(html: str) -> dict[str, list[tuple[str, str]]]:
    """Top-level dropdown labels -> their child (href, text) pairs.

    Walks link-by-link rather than trying to balance `<nav>` tags: the
    template nests navbars for desktop/mobile breakpoints, so a naive
    tag-balance approach double-counts every section. A dropdown trigger
    (`href="#"` on a `.dropdown-toggle`) starts a new top-level group; every
    real link after it, up to the next trigger, belongs to that group.
    """
    idx = html.find("navbar navbar-expand-lg")
    if idx == -1:
        return {}
    start = html.rfind("<nav", 0, idx)
    chunk = html[start : start + 60000]

    groups: dict[str, list[tuple[str, str]]] = {}
    seen_labels: set[str] = set()
    current: str | None = None
    for match in _LINK.finditer(chunk):
        href, raw_text = match.group(1), match.group(2)
        text = _clean(raw_text)
        if not text:
            continue
        if href == "#":
            if text in seen_labels:
                # The template repeats the whole navbar for a mobile
                # breakpoint. Stop at the first repeat rather than merging
                # a second copy's children into the first's totals.
                break
            current = text
            seen_labels.add(text)
            groups[current] = []
        elif current:
            groups[current].append((href, text))
    return groups


def harvest_utility_nav(html: str) -> list[tuple[str, str]]:
    """Flat, non-dropdown top-level links: the audience-based quicklinks bar."""
    items = []
    seen = set()
    for match in re.finditer(
        r'<a href="([^"]+)"[^>]*aria-label="Open ([^"]+) section">([^<]+)<', html
    ):
        href, _label, text = match.group(1), match.group(2), _clean(match.group(3))
        if text not in seen:
            seen.add(text)
            items.append((href, text))
    return items


def two_level_prefix(url: str, base: str) -> str:
    path = url.replace(base, "").strip("/").split("#")[0]
    if not path:
        return "(root)"
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]


def main() -> int:
    base = HOMEPAGE.rstrip("/")
    store = SnapshotStore("corpus/raw")
    html = store.get(HOMEPAGE)
    if html is None:
        print("no homepage snapshot in corpus/raw -- run the crawl first")
        return 1

    main_nav = harvest_main_nav(html)
    utility_nav = harvest_utility_nav(html)

    nav_path = Path("data/nav_top_level.csv")
    nav_path.parent.mkdir(parents=True, exist_ok=True)
    with nav_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["nav_kind", "top_level_label", "child_href", "child_text"])
        for label, children in main_nav.items():
            for href, text in children:
                writer.writerow(["dropdown", label, href, text])
        for href, text in utility_nav:
            writer.writerow(["utility", text, href, text])

    print(f"main nav: {len(main_nav)} sections, {sum(len(c) for c in main_nav.values())} links")
    print(f"utility nav: {len(utility_nav)} sections")
    print(f"written to {nav_path}")

    docs_path = Path("corpus/extracted/documents.jsonl")
    bc_path = Path("data/breadcrumb_vs_path.csv")
    if docs_path.exists():
        with docs_path.open(encoding="utf-8") as f, bc_path.open(
            "w", encoding="utf-8", newline=""
        ) as out:
            writer = csv.writer(out)
            writer.writerow(["url", "path_prefix", "breadcrumb_root"])
            rows = 0
            for line in f:
                doc = json.loads(line)
                breadcrumb = doc.get("breadcrumb") or []
                if not breadcrumb:
                    continue
                writer.writerow(
                    [doc["url"], two_level_prefix(doc["url"], base), breadcrumb[0]]
                )
                rows += 1
        print(f"breadcrumb roots: {rows} documents -> {bc_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
