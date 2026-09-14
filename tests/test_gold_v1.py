"""Task 13: the committed 300-question gold set must stay valid and locked.

This is a regression guard on the data file itself, not on the tooling --
`test_gold.py` already covers `validate()`/`stratified_split()` in isolation.
If a future hand-edit to `gold_v1.jsonl` breaks schema, drifts from
`SLICE_TARGETS`, or goes stale against `corpus/chunks.jsonl`, this is what
catches it.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from mcrag.eval.gold import SLICE_TARGETS, load_gold_questions, load_split_lock, validate

GOLD_PATH = Path("data/gold/gold_v1.jsonl")
SPLIT_LOCK_PATH = Path("data/gold/split.lock")


def _load_chunk_ids() -> set[str]:
    ids = set()
    with open("corpus/chunks.jsonl", encoding="utf-8") as f:
        for line in f:
            ids.add(json.loads(line)["chunk_id"])
    return ids


def _load_office_emails() -> set[str]:
    data = yaml.safe_load(Path("data/offices.yaml").read_text(encoding="utf-8"))
    return {o["email"] for o in data["offices"]}


def test_gold_set_has_exactly_300_questions_at_target_proportions():
    questions = load_gold_questions(GOLD_PATH)
    assert len(questions) == 300
    counts = Counter(q.slice for q in questions)
    assert dict(counts) == SLICE_TARGETS


def test_every_question_passes_validate():
    questions = load_gold_questions(GOLD_PATH)
    for q in questions:
        assert validate(q) == [], (q.qid, validate(q))


def test_no_duplicate_qids():
    questions = load_gold_questions(GOLD_PATH)
    qids = [q.qid for q in questions]
    assert len(qids) == len(set(qids))


def test_every_gold_chunk_id_exists_in_the_corpus():
    chunk_ids = _load_chunk_ids()
    questions = load_gold_questions(GOLD_PATH)
    for q in questions:
        for cid in q.gold:
            assert cid in chunk_ids, (q.qid, cid)


def test_single_silo_gold_shares_one_silo_and_cross_silo_spans_two():
    chunk_silo = {}
    with open("corpus/chunks.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            chunk_silo[d["chunk_id"]] = set(d["silo"])

    for q in load_gold_questions(GOLD_PATH):
        silos = set().union(*(chunk_silo[c] for c in q.gold)) if q.gold else set()
        if q.slice == "single_silo":
            assert len(silos) == 1, (q.qid, silos)
        elif q.slice == "cross_silo":
            assert len(silos) >= 2, (q.qid, silos)


def test_every_expected_referral_is_a_real_office_email():
    emails = _load_office_emails()
    for q in load_gold_questions(GOLD_PATH):
        if q.expected_referral is not None:
            assert q.expected_referral in emails, (q.qid, q.expected_referral)


def test_split_lock_matches_the_gold_set_and_is_stratified_40_20_40():
    questions = load_gold_questions(GOLD_PATH)
    lock = load_split_lock(SPLIT_LOCK_PATH)
    assignment = lock["assignment"]

    assert set(assignment) == {q.qid for q in questions}

    by_slice: dict[str, Counter] = {}
    for q in questions:
        by_slice.setdefault(q.slice, Counter())[assignment[q.qid]] += 1

    for slice_name, target in SLICE_TARGETS.items():
        counts = by_slice[slice_name]
        assert sum(counts.values()) == target
        # 40/20/40, rounded -- allow the same +/-1 rounding slack stratified_split allows.
        assert abs(counts["train"] - round(target * 0.4)) <= 1
        assert abs(counts["dev"] - round(target * 0.2)) <= 1
        assert abs(counts["test"] - round(target * 0.4)) <= 1
