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
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from mcrag.types import GoldQuestion

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
                )
            )
    return questions


def write_gold_questions(path: Path, questions: list[GoldQuestion]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(asdict(q)) + "\n")
