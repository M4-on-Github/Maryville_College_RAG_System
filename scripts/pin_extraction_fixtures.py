"""Pin extraction regression fixtures from the snapshot store.

For each chosen page this writes two committed files: the raw HTML as fetched,
and the text the current extractor produces from it. The test then re-extracts
and compares. Committing the HTML too is what makes the test meaningful --
without the input, a "snapshot test" only checks that a file on disk still
matches itself.

What is pinned is the *extractor's* output, before the corpus-level boilerplate
filter runs -- that filter is a separate unit with its own fixture, and mixing
the two would make a single test fail for two unrelated reasons.

Re-run **deliberately**, after reviewing a diff. Regenerating fixtures to make a
failing test pass is how a regression suite quietly stops detecting regressions.

    python scripts/pin_extraction_fixtures.py --list
    python scripts/pin_extraction_fixtures.py --write
"""

from __future__ import annotations

import argparse
import gzip
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.crawl.fetcher import SnapshotStore  # noqa: E402
from mcrag.extract.trafilatura_extractor import TrafilaturaExtractor  # noqa: E402
from mcrag.types import RawPage  # noqa: E402

BASE = "https://www.maryvillecollege.edu"
FIXTURES = Path("tests/fixtures/extraction")

# One page per silo, chosen for structural variety rather than for being easy:
# a long prose page, a course record, a program page, a person page, a taxonomy
# listing, and a nav-heavy hub with almost no prose of its own.
PINNED = [
    "/about/",
    "/about/faith/",
    "/academics/",
    "/academics/course/advanced-neuroscience-2/",
    "/academics/programs-of-study/accounting/",
    "/academics/programs-of-study/american-sign-language-and-deaf-studies/",
    "/about/downtown-center/rentals/",
    "/orientation/",
    "/admissions/",
    "/alumni/",
    "/athletics/",
    "/business-office/",
    "/campus-life/",
    "/families/",
    "/giving/",
    "/international/",
    "/news/divisions/accounting/",
]


def slug(path: str) -> str:
    return path.strip("/").replace("/", "__") or "root"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default="corpus/raw", type=Path)
    parser.add_argument("--write", action="store_true", help="write the fixture files")
    parser.add_argument("--list", action="store_true", help="show what would be pinned")
    args = parser.parse_args()

    store = SnapshotStore(args.raw)
    extractor = TrafilaturaExtractor()
    missing: list[str] = []
    written = 0

    for path in PINNED:
        url = BASE + path
        html = store.get(url)
        if html is None:
            missing.append(path)
            continue

        doc = extractor.extract(
            RawPage(
                url=url,
                http_status=200,
                content_hash="",
                fetched_at=datetime.now(timezone.utc),
                html=html,
            )
        )
        if doc is None:
            print(f"  SKIP (extracts to nothing): {path}", file=sys.stderr)
            continue

        if args.list:
            print(f"  {path:<70} {doc.char_len:>6} chars  {doc.title[:40]}")
            continue

        if args.write:
            FIXTURES.mkdir(parents=True, exist_ok=True)
            name = slug(path)
            (FIXTURES / f"{name}.html.gz").write_bytes(gzip.compress(html.encode("utf-8")))
            (FIXTURES / f"{name}.expected.txt").write_text(doc.text + "\n", encoding="utf-8")
            (FIXTURES / f"{name}.meta.txt").write_text(
                f"url: {url}\ntitle: {doc.title}\nbreadcrumb: {' > '.join(doc.breadcrumb)}\n",
                encoding="utf-8",
            )
            written += 1

    if missing:
        print(f"\n{len(missing)} pinned pages are not in the snapshot store:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print("fetch them first (scripts/fetch_corpus.py)", file=sys.stderr)

    if args.write:
        print(f"\nwrote {written} fixtures to {FIXTURES}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
