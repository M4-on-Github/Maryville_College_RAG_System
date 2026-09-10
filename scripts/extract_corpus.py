"""Extract the fetched snapshots into the document corpus.

Offline and idempotent: it reads `corpus/raw`, writes `corpus/extracted`, and
puts no traffic on the site. Safe to re-run after any extractor change.

    python scripts/extract_corpus.py
    python scripts/extract_corpus.py --no-boilerplate-filter   # to see the diff

The exit code is non-zero when the share of empty extractions crosses
``--max-empty-share``. An extraction run that quietly loses a fifth of the
corpus should stop the pipeline, not hand a smaller corpus to the indexer.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.crawl.fetcher import SnapshotStore  # noqa: E402
from mcrag.crawl.manifest import Manifest  # noqa: E402
from mcrag.extract.boilerplate import BoilerplateFilter  # noqa: E402
from mcrag.extract.pipeline import ExtractedCorpus, empty_by_prefix, extract_all  # noqa: E402
from mcrag.extract.trafilatura_extractor import TrafilaturaExtractor  # noqa: E402

BASE = "https://www.maryvillecollege.edu"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="corpus/manifest.jsonl", type=Path)
    parser.add_argument("--raw", default="corpus/raw", type=Path)
    parser.add_argument("--out", default="corpus/extracted/documents.jsonl", type=Path)
    parser.add_argument("--min-chars", type=int, default=200)
    parser.add_argument("--no-boilerplate-filter", action="store_true")
    parser.add_argument("--max-empty-share", type=float, default=0.2)
    args = parser.parse_args()

    manifest = Manifest.load(args.manifest)
    store = SnapshotStore(args.raw)
    if not len(store):
        print(f"no snapshots in {args.raw} -- run scripts/fetch_corpus.py", file=sys.stderr)
        return 1

    documents, stats = extract_all(
        manifest,
        store,
        TrafilaturaExtractor(min_chars=args.min_chars),
        ExtractedCorpus(args.out),
        None if args.no_boilerplate_filter else BoilerplateFilter(min_chars=args.min_chars),
    )

    empty = stats["extraction_empty"] + stats["boilerplate_only"]
    attempted = stats["extracted"] + empty
    share = empty / attempted if attempted else 0.0
    chars = sorted(d.char_len for d in documents)

    print(
        f"snapshots:            {len(store)}\n"
        f"documents extracted:  {stats['extracted']}\n"
        f"empty extractions:    {stats['extraction_empty']}\n"
        f"boilerplate-only:     {stats['boilerplate_only']}\n"
        f"template lines found: {stats['boilerplate_lines']}\n"
        f"chrome chars removed: {stats['boilerplate_chars_removed']}\n"
        f"written to {args.out}"
    )
    if chars:
        print(
            f"\nchars per document -- median {chars[len(chars) // 2]}, "
            f"min {chars[0]}, max {chars[-1]}"
        )

    by_prefix = empty_by_prefix(manifest, BASE)
    if by_prefix:
        print("\nempty extractions by path prefix (a spike here names a broken template):")
        for prefix, count in by_prefix.most_common(10):
            print(f"  {prefix:<24} {count:>5}")

    if share > args.max_empty_share:
        print(
            f"\n!! {share:.1%} of pages extracted to nothing, over the "
            f"{args.max_empty_share:.0%} threshold. That is an extraction failure, "
            "not a thin corpus -- check the prefixes above before indexing.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
