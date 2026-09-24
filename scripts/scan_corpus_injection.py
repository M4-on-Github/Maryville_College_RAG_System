"""T37: scan corpus/chunks.jsonl for instruction-like text (indirect prompt injection).

The pattern list is FIXED here, before the first run (pre-registered). A hit is a
candidate, not a finding: every hit is triaged by hand in docs/injection_scan.md.
Deterministic: same chunks.jsonl -> byte-identical report.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "override": re.compile(r"\b(?:ignore|disregard|forget|override)\b.{0,30}\b(?:previous|prior|above|earlier|all|your)\b.{0,20}\b(?:instructions?|rules?|prompts?)\b", re.I),
    "role_change": re.compile(r"\byou are now\b|\bact as (?:an?|the)\b|\bpretend (?:to be|you)\b|\bfrom now on,? you\b", re.I),
    "system_marker": re.compile(r"</?\s*(?:system|assistant|question|passages?)\s*>|\bsystem prompt\b|^\s*system\s*:", re.I | re.M),
    "reveal": re.compile(r"\b(?:reveal|repeat|print|show|output)\b.{0,30}\b(?:system prompt|instructions|hidden)\b", re.I),
    "llm_address": re.compile(r"\b(?:as an? (?:ai|language model|llm)|dear (?:ai|assistant|chatbot|llm)|note to (?:ai|assistant|llm))\b", re.I),
    "exfil_or_command": re.compile(r"\b(?:send|post|email|forward)\b.{0,40}\b(?:to|at)\b.{0,20}(?:https?://|\S+@\S+)", re.I),
    "encoded_blob": re.compile(r"[A-Za-z0-9+/]{80,}={0,2}"),
    "hidden_unicode": re.compile("[​‌‍⁠﻿‪-‮]"),
}


def scan(chunks_path: Path) -> dict:
    hits: dict[str, list[dict]] = {k: [] for k in PATTERNS}
    n = 0
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        n += 1
        for name, pat in PATTERNS.items():
            m = pat.search(c["text"])
            if m:
                s = max(0, m.start() - 40)
                hits[name].append(
                    {
                        "chunk_id": c["chunk_id"],
                        "url": c["source_url"],
                        "snippet": c["text"][s : m.end() + 40].replace("\n", " ")[:200],
                    }
                )
    return {"n_chunks": n, "hits": hits}


def render(result: dict) -> str:
    out = ["# Indirect-injection scan of corpus/chunks.jsonl (T37)", "",
           f"Chunks scanned: {result['n_chunks']}. Patterns fixed before the first run; "
           "a hit is a candidate to triage, not a finding.", "", "| pattern | hits |", "|---|---:|"]
    for name, hs in result["hits"].items():
        out.append(f"| {name} | {len(hs)} |")
    for name, hs in result["hits"].items():
        if not hs:
            continue
        out += ["", f"## {name} ({len(hs)})", ""]
        for h in hs[:40]:
            out.append(f"- `{h['chunk_id']}` {h['url']}: {h['snippet']!r}")
        if len(hs) > 40:
            out.append(f"- ... {len(hs) - 40} more not listed")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    res = scan(Path("corpus/chunks.jsonl"))
    text = render(res)
    Path(sys.argv[1] if len(sys.argv) > 1 else "docs/injection_scan.md").write_text(text, encoding="utf-8", newline="\n")
    print(text.split("\n## ")[0])
