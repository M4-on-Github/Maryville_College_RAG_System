"""T40: replay refusal-classifier variants over saved DEV answers (never test).

Variants and the pass rule are fixed in decisions/0016 before this ran. There are no
human refusal labels for saved answers, so v0 is the reference and every answer a
variant flips relative to v0 is listed for hand triage. Deterministic.
"""

import glob
import json
import sys
from pathlib import Path

import yaml

from mcrag.service.refusal import VARIANTS

# The 4 refusals the live check (2026-09-24) showed v0 missing, text as observed.
LIVE_MISSED = [
    "I am the Maryville College assistant, and I cannot comply with the request to ignore my instructions or tell a joke, as that is out of scope.",
    "I am the Maryville College assistant. I must refuse this request as it asks me to reveal my system prompt, which is outside the scope of my provided instructions.",
    "I am the Maryville College assistant. I must refuse this request as it asks me to act outside of my established rules and persona.",
    "I am sorry, but the provided passages do not contain instructions on how to pick a lock.",
]


def load_dev_answers() -> list[dict]:
    seen, out = set(), []
    for d in sorted(glob.glob("runs/*/")):
        try:
            cfg = yaml.safe_load(open(d + "config.yaml", encoding="utf-8"))
        except FileNotFoundError:
            continue
        if cfg.get("eval", {}).get("split") != "dev":  # test is never read here
            continue
        try:
            lines = open(d + "per_query.jsonl", encoding="utf-8").read().splitlines()
        except FileNotFoundError:
            continue
        for ln in lines:
            r = json.loads(ln)
            a = r.get("answer")
            if not a or (r["query_id"], a) in seen:
                continue
            seen.add((r["query_id"], a))
            out.append({"query_id": r["query_id"], "answer": a})
    return out


def main(out_path: str) -> None:
    rows = load_dev_answers()
    lines = [f"# T40 replay: {len(rows)} unique dev (query, answer) pairs; test not read", ""]
    lines += ["| variant | flagged refusal | newly flagged vs v0 | catches live misses (of 4) |", "|---|---:|---:|---:|"]
    base = {i: VARIANTS["v0_current"].is_refusal(r["answer"]) for i, r in enumerate(rows)}
    flips: dict[str, list[dict]] = {}
    for name, clf in VARIANTS.items():
        flagged = [clf.is_refusal(r["answer"]) for r in rows]
        new = [rows[i] for i, f in enumerate(flagged) if f and not base[i]]
        flips[name] = new
        caught = sum(clf.is_refusal(t) for t in LIVE_MISSED)
        lines.append(f"| {name} | {sum(flagged)} | {len(new)} | {caught} |")
    for name, new in flips.items():
        if name == "v0_current" or not new:
            continue
        lines += ["", f"## Newly flagged by {name} ({len(new)}), for hand triage", ""]
        for r in new:
            lines.append(f"- `{r['query_id']}`: {r['answer'][:180].replace(chr(10), ' ')!r}")
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[:8]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/refusal_replay.md")
