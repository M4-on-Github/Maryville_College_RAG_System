"""Task 8's `data/offices.yaml` as a silo -> contact lookup. Task 27 is the
first real caller: resolving a refusal's office from a chunk's silo.

No caching -- the file is small (one row per silo, hand-checked per
decision 0002) and this is called once per refused request, not in a hot
loop; a stale in-memory copy surviving a `data/offices.yaml` edit is a worse
failure mode than reading a few hundred bytes off disk each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

OFFICES_PATH = Path("data/offices.yaml")

# The corpus's own generic front door. Used only when a refusal cannot be
# routed to one specific silo -- no chunk was retrieved at all, or the
# routing chunk's silo is `other`/missing from `offices.yaml` (decision 0002
# keeps that table per-silo and hand-checked; it deliberately has no
# `other`/general row of its own, per `tests/test_offices.py`). Picking
# Admissions as the fallback is a Task 27 policy decision, not a fact drawn
# from `offices.yaml` itself: it is the one office whose job is genuinely
# "point anyone, about anything, somewhere useful."
GENERAL_SILO = "admissions"


@dataclass(frozen=True, slots=True)
class OfficeContact:
    silo: str
    email: str
    destination_url: str


def _load(path: Path) -> dict[str, OfficeContact]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        row["silo"]: OfficeContact(silo=row["silo"], email=row["email"], destination_url=row["destination_url"])
        for row in data["offices"]
    }


def resolve(silo: str | None, *, path: Path = OFFICES_PATH) -> OfficeContact:
    """`silo=None` (nothing retrieved) or a silo absent from `offices.yaml`
    (`other`, or one this table doesn't know) both fall back to
    `GENERAL_SILO` -- a refusal is never left with an empty office."""
    offices = _load(path)
    if silo and silo in offices:
        return offices[silo]
    return offices[GENERAL_SILO]
