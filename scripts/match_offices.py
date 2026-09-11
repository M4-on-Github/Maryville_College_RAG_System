"""Task 8 step 3: office-contact candidates for the top silo prefixes.

This produces *candidates for human review*, not ground truth. Decision 0002
requires `data/offices.yaml` to be "small, hand-checked, and reviewable in a
sitting" -- this script does the mechanical narrowing (find a plausible
contact page + email per prefix) so a human only has to confirm or correct a
short table, not read the whole corpus.

Two sources, kept separate because they need different confidence framing:

1. The department directory's own division-office block
   (`/directories/department/`) -- six fixed-pattern rows
   ("Division of X - Office" / name+title / building / phone email) that
   precede the flat personnel directory on the same page. High confidence:
   this is the site's own structured office listing.
2. For every other candidate prefix in `data/silo_histogram.csv`, the
   shortest-URL page under that prefix is inspected for a name+phone+email
   line. Lower confidence: this is a heuristic guess at "the page that
   answers who runs this," not a verified office listing.

    python scripts/match_offices.py
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

_DIVISION_ROW = re.compile(
    r"Division of ([^\n]+?) - Office\n([^\n]+)\n([^\n]+)\n(?:(\d{3}-\d{3}-\d{4}) )?"
    r"([\w.+-]+@maryvillecollege\.edu)"
)
_EMAIL = re.compile(r"[\w.+-]+@maryvillecollege\.edu")
_PHONE = re.compile(r"\d{3}-\d{3}-\d{4}")


def parse_division_offices(text: str) -> list[dict[str, str]]:
    """The department directory's own division-office block (high confidence)."""
    rows = []
    for m in _DIVISION_ROW.finditer(text):
        division, name_title, building, phone, email = m.groups()
        name, _, title = name_title.partition(", ")
        rows.append(
            {
                "silo": f"Division of {division}",
                "contact_name": name,
                "contact_title": title,
                "building": building,
                "phone": phone or "",
                "email": email,
                "source": "directories/department (division-office block)",
                "confidence": "high",
            }
        )
    return rows


def find_prefix_contact(text: str) -> tuple[str, str] | None:
    """First email + nearest phone on a page, or None if it has neither."""
    email_m = _EMAIL.search(text)
    if not email_m:
        return None
    window = text[max(0, email_m.start() - 200) : email_m.end()]
    phone_m = _PHONE.search(window)
    return (email_m.group(0), phone_m.group(0) if phone_m else "")


def load_documents(path: Path) -> dict[str, str]:
    docs: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            docs[doc["url"]] = doc["text"]
    return docs


def two_level_prefix(url: str, base: str) -> str:
    path = url.replace(base, "").strip("/").split("#")[0]
    if not path:
        return "(root)"
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]


def main() -> int:
    base = "https://www.maryvillecollege.edu"
    docs = load_documents(Path("corpus/extracted/documents.jsonl"))

    dept_url = f"{base}/directories/department/"
    division_rows = parse_division_offices(docs.get(dept_url, ""))

    with open("data/silo_histogram.csv", encoding="utf-8") as f:
        prefixes = [row["path_prefix"] for row in csv.DictReader(f)][:25]

    by_prefix: dict[str, list[str]] = {}
    for url in docs:
        prefix = two_level_prefix(url, base)
        by_prefix.setdefault(prefix, []).append(url)

    candidate_rows = []
    for prefix in prefixes:
        urls = sorted(by_prefix.get(prefix, []), key=len)
        found = None
        for url in urls[:5]:  # shortest URLs first: most likely to be the section root
            hit = find_prefix_contact(docs[url])
            if hit:
                found = (url, *hit)
                break
        candidate_rows.append(
            {
                "path_prefix": prefix,
                "candidate_url": found[0] if found else "",
                "email": found[1] if found else "",
                "phone": found[2] if found else "",
                "confidence": "low (heuristic: shortest page under prefix with an email)"
                if found
                else "no email found in top-5 shortest pages",
            }
        )

    out_path = Path("data/office_candidates.csv")
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["path_prefix", "candidate_url", "email", "phone", "confidence"]
        )
        writer.writeheader()
        writer.writerows(candidate_rows)

    div_path = Path("data/division_offices.csv")
    with div_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "silo",
                "contact_name",
                "contact_title",
                "building",
                "phone",
                "email",
                "source",
                "confidence",
            ],
        )
        writer.writeheader()
        writer.writerows(division_rows)

    print(f"division offices (high confidence): {len(division_rows)} -> {div_path}")
    hit_count = sum(1 for r in candidate_rows if r["candidate_url"])
    print(f"prefix candidates: {hit_count}/{len(candidate_rows)} found an email -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
