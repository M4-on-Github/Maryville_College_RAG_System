"""Task 12: gold-set schema validation, stratified splitting, and split-lock.

The container is built before the 300 questions (Task 13) go into it, per the
task's own rationale: retrofitting granularity or conjunctive flags onto an
already-authored set is miserable. Nothing here reads or writes an actual gold
set yet -- that is Task 13's job.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcrag.types import GoldQuestion, Pin

PROVENANCE_VALUES = ("synthetic", "real")

# PLAN Phase 2 §"Sizing and splits": seven slices, non-proportional growth,
# summing to ~300. Kept here as the single source of truth for validation and
# for reporting how a drafted set compares to target.
SLICE_TARGETS: dict[str, int] = {
    "single_silo": 80,
    "cross_silo": 70,
    "out_of_scope": 60,
    "temporal": 25,
    "exact_match": 25,
    "adversarial": 25,
    "multi_turn": 15,
}

SLICES = tuple(SLICE_TARGETS)

# 40 / 20 / 40, stratified within every slice (PLAN Phase 2).
SPLIT_RATIOS: dict[str, float] = {"train": 0.4, "dev": 0.2, "test": 0.4}


ORIGIN_VALUES = ("authored", "backfill", "reverified")


def validate(question: GoldQuestion) -> list[str]:
    """Structural checks a question must pass before it enters the gold set.

    Returns a list of problems; empty means valid. Does not check whether the
    gold refs actually contain the answer -- that is a human sampling check
    (Task 13's verification step), not something a schema can assert.
    """
    problems = []
    if question.slice not in SLICE_TARGETS:
        problems.append(f"unknown slice {question.slice!r}; expected one of {SLICES}")
    if not question.qid:
        problems.append("qid must be non-empty")
    if not question.question.strip():
        problems.append("question text must be non-empty")
    if question.slice == "out_of_scope":
        if question.gold:
            problems.append("out_of_scope questions must have no gold refs")
    elif not question.gold:
        problems.append(f"{question.slice} questions need at least one gold ref")
    if question.conjunctive and len(question.gold) < 2:
        problems.append("conjunctive=true requires at least 2 gold refs")
    if question.provenance not in PROVENANCE_VALUES:
        problems.append(
            f"unknown provenance {question.provenance!r}; expected one of {PROVENANCE_VALUES}"
        )
    if question.slice == "multi_turn":
        if not question.history:
            problems.append("multi_turn questions need at least one prior turn in history")
    elif question.history:
        problems.append(f"{question.slice} questions must not carry history (multi_turn only)")
    # Validate pins if present
    pinned_refs = set()
    for pin in question.pins:
        if pin.origin not in ORIGIN_VALUES:
            problems.append(
                f"pin for {pin.gold_ref!r} has unknown origin {pin.origin!r}; "
                f"expected one of {ORIGIN_VALUES}"
            )
        if pin.gold_ref not in question.gold:
            problems.append(
                f"pin for {pin.gold_ref!r} references a gold ref not in this question's "
                f"gold set"
            )
        if pin.gold_ref in pinned_refs:
            problems.append(f"duplicate pin for gold ref {pin.gold_ref!r}")
        pinned_refs.add(pin.gold_ref)
    return problems


def stratified_split(
    questions: list[GoldQuestion], seed: int
) -> dict[str, str]:
    """qid -> split ("train"/"dev"/"test"), 40/20/40 within every slice.

    Deterministic from `seed`: the same questions and seed always produce the
    same assignment, which is what makes `split.lock`'s hash meaningful.
    """
    by_slice: dict[str, list[GoldQuestion]] = {}
    for q in questions:
        by_slice.setdefault(q.slice, []).append(q)

    assignment: dict[str, str] = {}
    for slice_name in sorted(by_slice):
        group = sorted(by_slice[slice_name], key=lambda q: q.qid)
        rng = random.Random(f"{seed}:{slice_name}")
        rng.shuffle(group)
        n = len(group)
        n_train = round(n * SPLIT_RATIOS["train"])
        n_dev = round(n * SPLIT_RATIOS["dev"])
        for i, q in enumerate(group):
            if i < n_train:
                assignment[q.qid] = "train"
            elif i < n_train + n_dev:
                assignment[q.qid] = "dev"
            else:
                assignment[q.qid] = "test"
    return assignment


def split_hash(assignment: dict[str, str]) -> str:
    """A hash over the whole qid->split mapping, order-independent."""
    canonical = json.dumps(dict(sorted(assignment.items())), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_split_lock(path: Path, assignment: dict[str, str], seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seed": seed,
        "split_hash": split_hash(assignment),
        "assignment": dict(sorted(assignment.items())),
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_split_lock(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestAccessCounter:
    """A test-set read that isn't logged didn't happen, for accountability.

    PLAN's standing rule: the test split is touched once, after Checkpoint E,
    and every access is logged. This counter only moves when `increment` is
    called explicitly -- nothing in the eval pipeline increments it as a side
    effect of an unrelated read, on purpose.
    """

    __test__ = False  # not a pytest test case; the name collides with the prefix

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict:
        if not self.path.exists():
            return {"count": 0, "log": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def increment(self, reason: str) -> int:
        state = self._load()
        state["count"] += 1
        state["log"].append(
            {"reason": reason, "at": datetime.now(timezone.utc).isoformat()}
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return state["count"]

    @property
    def count(self) -> int:
        return self._load()["count"]


def load_gold_questions(path: Path) -> list[GoldQuestion]:
    questions = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            # Deserialize pins if present: list of dicts -> tuple of Pin objects
            pins_raw = raw.get("pins", [])
            pins = tuple(
                Pin(
                    gold_ref=p["gold_ref"],
                    content_hash=p["content_hash"],
                    origin=p["origin"],
                )
                for p in pins_raw
            )
            questions.append(
                GoldQuestion(
                    qid=raw["qid"],
                    slice=raw["slice"],
                    question=raw["question"],
                    gold=tuple(raw.get("gold", [])),
                    conjunctive=raw.get("conjunctive", False),
                    notes=raw.get("notes", ""),
                    expected_referral=raw.get("expected_referral"),
                    split=raw.get("split"),
                    provenance=raw.get("provenance", "synthetic"),
                    history=tuple(raw.get("history", [])),
                    pins=pins,
                )
            )
    return questions


def write_gold_questions(path: Path, questions: list[GoldQuestion]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for q in questions:
            # asdict() recursively converts Pin dataclasses to dicts
            q_dict = asdict(q)
            f.write(json.dumps(q_dict) + "\n")


# --------------------------------------------------------------------------
# Task 35: Content-hash pinning and stale accounting
# --------------------------------------------------------------------------


def load_chunks(path: Path) -> dict[str, Any]:
    """Load chunks from the corpus JSONL file.

    Returns a dict mapping chunk_id -> chunk dict (for fast lookup by ref).
    """
    chunk_lookup: dict[str, Any] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunk = json.loads(line)
                chunk_lookup[chunk["chunk_id"]] = chunk
    return chunk_lookup


def resolve_gold_ref(
    gold_ref: str, chunks: dict[str, Any]
) -> tuple[str, str] | None:
    """Resolve a gold ref to its source URL and current content_hash.

    Args:
        gold_ref: chunk ID like "6f879be008729f80-5"
        chunks: dict mapping chunk_id -> chunk dict

    Returns:
        (source_url, content_hash) or None if the ref cannot be resolved
    """
    chunk = chunks.get(gold_ref)
    if chunk is None:
        return None
    return (chunk["source_url"], chunk["content_hash"])


@dataclass(frozen=True, slots=True)
class StaleQuestion:
    """A gold question whose pin hash no longer matches the current corpus."""

    qid: str
    gold_ref: str
    pinned_hash: str
    current_hash: str
    source_url: str


def find_stale_questions(
    questions: list[GoldQuestion], chunks: dict[str, Any]
) -> list[StaleQuestion]:
    """Find all gold questions whose pinned hashes have changed.

    Args:
        questions: the gold set
        chunks: dict mapping chunk_id -> chunk dict

    Returns:
        list of stale questions, sorted by qid
    """
    stale = []
    for q in questions:
        for pin in q.pins:
            chunk = chunks.get(pin.gold_ref)
            if chunk is None:
                # Chunk no longer exists; count as stale
                stale.append(
                    StaleQuestion(
                        qid=q.qid,
                        gold_ref=pin.gold_ref,
                        pinned_hash=pin.content_hash,
                        current_hash="(missing)",
                        source_url="(unknown)",
                    )
                )
            elif chunk["content_hash"] != pin.content_hash:
                # Hash mismatch; page has changed
                stale.append(
                    StaleQuestion(
                        qid=q.qid,
                        gold_ref=pin.gold_ref,
                        pinned_hash=pin.content_hash,
                        current_hash=chunk["content_hash"],
                        source_url=chunk["source_url"],
                    )
                )
    return sorted(stale, key=lambda s: s.qid)


def backfill_pins(
    questions: list[GoldQuestion], chunks: dict[str, Any]
) -> tuple[list[GoldQuestion], list[str]]:
    """Backfill content-hash pins for all resolvable gold refs.

    Existing pins are not overwritten; only missing pins are added with
    origin="backfill". Returns the updated questions and a list of qids
    for refs that could not be resolved.

    Args:
        questions: the gold set (unmodified)
        chunks: dict mapping chunk_id -> chunk dict

    Returns:
        (updated_questions, unresolved_qids)
    """
    unresolved_qids = []
    updated = []
    for q in questions:
        existing_pins_by_ref = {p.gold_ref: p for p in q.pins}
        new_pins = []
        for gold_ref in q.gold:
            if gold_ref in existing_pins_by_ref:
                # Keep existing pin
                new_pins.append(existing_pins_by_ref[gold_ref])
            else:
                # Try to resolve
                resolved = resolve_gold_ref(gold_ref, chunks)
                if resolved is None:
                    if q.qid not in unresolved_qids:
                        unresolved_qids.append(q.qid)
                else:
                    source_url, content_hash = resolved
                    new_pins.append(
                        Pin(
                            gold_ref=gold_ref,
                            content_hash=content_hash,
                            origin="backfill",
                        )
                    )
        # `replace` rather than re-listing every field: a field added to
        # GoldQuestion later must not be silently dropped by the backfill.
        updated.append(replace(q, pins=tuple(new_pins)))
    return updated, unresolved_qids


@dataclass(frozen=True, slots=True)
class ReverificationRecord:
    """A re-verification log entry (Task 35).

    Records when a human re-read a gold reference's page and confirmed or
    changed the pin.
    """

    qid: str
    gold_ref: str
    old_hash: str
    new_hash: str
    reverified_by: str
    reverified_at: str  # ISO-8601 UTC timestamp
    note: str = ""


def append_reverification_log(
    log_path: Path, record: ReverificationRecord
) -> None:
    """Append a re-verification record to the log (never edited or deleted).

    Args:
        log_path: path to data/gold/reverification_log.jsonl
        record: the re-verification to log
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record)) + "\n")


def reverify_pin(
    questions: list[GoldQuestion],
    qid: str,
    gold_ref: str,
    new_hash: str,
    reverified_by: str,
    note: str = "",
    log_path: Path = Path("data/gold/reverification_log.jsonl"),
) -> GoldQuestion | None:
    """Update a pin's hash and log the re-verification.

    Finds the question by qid, updates or creates its pin for gold_ref with
    the new_hash and origin="reverified", and appends to the reverification log.

    Args:
        questions: the gold set (unmodified)
        qid: the question's id
        gold_ref: the chunk id to reverify
        new_hash: the page's new content_hash
        reverified_by: who is performing the re-verification (email/name)
        note: optional free-text note
        log_path: path to the reverification log

    Returns:
        the updated question, or None if the qid was not found
    """
    target_q = None
    for q in questions:
        if q.qid == qid:
            target_q = q
            break
    if target_q is None:
        return None

    # Find the existing pin (if any) to log the old hash
    old_pin = None
    for pin in target_q.pins:
        if pin.gold_ref == gold_ref:
            old_pin = pin
            break
    old_hash = old_pin.content_hash if old_pin else "(none)"

    # Build new pins list
    new_pins = []
    for pin in target_q.pins:
        if pin.gold_ref != gold_ref:
            new_pins.append(pin)
    new_pins.append(
        Pin(
            gold_ref=gold_ref,
            content_hash=new_hash,
            origin="reverified",
        )
    )

    # `replace` for the same reason as in `backfill_pins`, and pins are kept in
    # gold order so a re-verification does not reshuffle the record it touches.
    order = {ref: i for i, ref in enumerate(target_q.gold)}
    new_pins.sort(key=lambda p: order.get(p.gold_ref, len(order)))
    updated_q = replace(target_q, pins=tuple(new_pins))

    # Log the reverification
    record = ReverificationRecord(
        qid=qid,
        gold_ref=gold_ref,
        old_hash=old_hash,
        new_hash=new_hash,
        reverified_by=reverified_by,
        reverified_at=datetime.now(timezone.utc).isoformat(),
        note=note,
    )
    append_reverification_log(log_path, record)

    return updated_q
