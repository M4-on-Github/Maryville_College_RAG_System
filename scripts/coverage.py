"""Report what the corpus has and what it does not.

Reads `corpus/manifest.jsonl` and prints counts by status, by reason class, and
by source, plus the reconciliation check. This is the evidence behind any
coverage claim in the writeup.

    python scripts/coverage.py [--manifest corpus/manifest.jsonl] [--markdown]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.crawl.manifest import Manifest, Status  # noqa: E402


def _table(title: str, counts: Counter[str], total: int, markdown: bool) -> str:
    lines = []
    if markdown:
        lines.append(f"\n### {title}\n")
        lines.append("| | count | share |")
        lines.append("|---|---:|---:|")
        for key, n in counts.most_common():
            lines.append(f"| {key} | {n} | {n / total:.1%} |")
        lines.append(f"| **total** | **{total}** | |")
    else:
        lines.append(f"\n{title}")
        lines.append("-" * len(title))
        width = max((len(k) for k in counts), default=10)
        for key, n in counts.most_common():
            lines.append(f"  {key:<{width}}  {n:>6}  {n / total:>6.1%}")
        lines.append(f"  {'total':<{width}}  {total:>6}")
    return "\n".join(lines)


def report(manifest: Manifest, markdown: bool = False) -> str:
    total = len(manifest)
    if total == 0:
        return "manifest is empty -- run scripts/enumerate.py first"

    out = [f"# Corpus coverage\n\n{total} URLs considered." if markdown else f"{total} URLs considered."]
    out.append(_table("By status", manifest.by_status(), total, markdown))
    out.append(_table("By reason class", manifest.by_reason_class(), total, markdown))
    out.append(_table("By source sitemap", manifest.by_source(), total, markdown))

    # The detail that matters most: which policy excluded what.
    policy = Counter(
        r.reason for r in manifest.records.values() if r.reason and r.reason.startswith("policy:")
    )
    if policy:
        out.append(_table("Policy exclusions in detail", policy, total, markdown))

    # Robots exclusions grouped by the rule that matched, not by URL.
    by_rule: defaultdict[str, int] = defaultdict(int)
    for record in manifest.records.values():
        if record.reason_class == "robots_disallow":
            by_rule[record.reason.split(":", 1)[1].strip()] += 1
    if by_rule:
        out.append(_table("Robots exclusions by rule", Counter(by_rule), total, markdown))

    fetched = manifest.fetched()
    if fetched:
        redirected = sum(1 for r in fetched if r.final_url and r.final_url != r.url)
        chars = [r.extracted_chars for r in fetched if r.extracted_chars is not None]
        out.append(f"\nFetched: {len(fetched)}; redirected: {redirected}")
        if chars:
            chars.sort()
            out.append(
                f"Extracted chars -- median {chars[len(chars) // 2]}, "
                f"min {chars[0]}, max {chars[-1]}"
            )

    undecided = manifest.undecided()
    pending = [
        r for r in manifest.records.values()
        if r.status == Status.EXCLUDED and r.reason == "policy:pending_fetch"
    ]
    out.append(f"\nPending fetch: {len(pending)}")
    if undecided:
        out.append(
            f"\n!! {len(undecided)} URLs are still 'policy:undecided'. "
            "Something reached the end of the crawl without a disposition; "
            "the coverage numbers above cannot be trusted until that is fixed."
        )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="corpus/manifest.jsonl", type=Path)
    parser.add_argument("--markdown", action="store_true", help="emit a Markdown table")
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"no manifest at {args.manifest}", file=sys.stderr)
        return 1
    print(report(Manifest.load(args.manifest), markdown=args.markdown))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
