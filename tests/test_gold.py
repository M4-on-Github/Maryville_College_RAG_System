"""Task 12: gold-set schema validation, deterministic splitting, split-lock."""

from __future__ import annotations

from mcrag.eval.gold import (
    SLICE_TARGETS,
    TestAccessCounter,
    load_gold_questions,
    load_split_lock,
    split_hash,
    stratified_split,
    validate,
    write_gold_questions,
    write_split_lock,
)
from mcrag.types import GoldQuestion


def _q(qid, slice_="single_silo", gold=("ref-1",), conjunctive=False):
    return GoldQuestion(
        qid=qid, slice=slice_, question=f"q {qid}", gold=gold, conjunctive=conjunctive
    )


def test_validate_accepts_a_well_formed_question():
    assert validate(_q("q1")) == []


def test_validate_rejects_unknown_slice():
    problems = validate(_q("q1", slice_="not_a_real_slice"))
    assert any("unknown slice" in p for p in problems)


def test_validate_requires_gold_refs_for_answerable_slices():
    problems = validate(_q("q1", gold=()))
    assert any("need at least one gold ref" in p for p in problems)


def test_validate_out_of_scope_must_have_no_gold_refs():
    problems = validate(_q("q1", slice_="out_of_scope", gold=("ref-1",)))
    assert any("no gold refs" in p for p in problems)
    assert validate(_q("q1", slice_="out_of_scope", gold=())) == []


def test_validate_conjunctive_requires_at_least_two_gold_refs():
    problems = validate(_q("q1", gold=("ref-1",), conjunctive=True))
    assert any("conjunctive" in p for p in problems)
    assert validate(_q("q1", gold=("ref-1", "ref-2"), conjunctive=True)) == []


def test_validate_defaults_provenance_to_synthetic():
    assert _q("q1").provenance == "synthetic"
    assert validate(_q("q1")) == []


def test_validate_rejects_unknown_provenance():
    q = GoldQuestion(
        qid="q1", slice="single_silo", question="q", gold=("ref-1",),
        conjunctive=False, provenance="made-up",
    )
    problems = validate(q)
    assert any("provenance" in p for p in problems)


def test_validate_multi_turn_requires_history():
    q = _q("q1", slice_="multi_turn")
    problems = validate(q)
    assert any("history" in p for p in problems)

    q_with_history = GoldQuestion(
        qid="q1", slice="multi_turn", question="what about for international students?",
        gold=("ref-1",), conjunctive=False, history=("Does MC offer study abroad?",),
    )
    assert validate(q_with_history) == []


def test_validate_rejects_history_outside_multi_turn():
    q = GoldQuestion(
        qid="q1", slice="single_silo", question="q", gold=("ref-1",),
        conjunctive=False, history=("some prior turn",),
    )
    problems = validate(q)
    assert any("history" in p for p in problems)


def test_stratified_split_is_deterministic_from_the_seed():
    questions = [_q(f"q{i}") for i in range(20)]
    a = stratified_split(questions, seed=42)
    b = stratified_split(questions, seed=42)
    assert a == b
    assert split_hash(a) == split_hash(b)


def test_stratified_split_different_seed_can_differ():
    questions = [_q(f"q{i}") for i in range(20)]
    a = stratified_split(questions, seed=1)
    b = stratified_split(questions, seed=2)
    assert a != b


def test_stratified_split_is_proportional_within_each_slice():
    questions = [_q(f"s{i}", slice_="single_silo") for i in range(10)] + [
        _q(f"c{i}", slice_="cross_silo") for i in range(10)
    ]
    assignment = stratified_split(questions, seed=42)
    for slice_name in ("single_silo", "cross_silo"):
        counts = {"train": 0, "dev": 0, "test": 0}
        for q in questions:
            if q.slice == slice_name:
                counts[assignment[q.qid]] += 1
        assert counts == {"train": 4, "dev": 2, "test": 4}


def test_split_lock_round_trips(tmp_path):
    questions = [_q(f"q{i}") for i in range(10)]
    assignment = stratified_split(questions, seed=42)
    lock_path = tmp_path / "split.lock"
    write_split_lock(lock_path, assignment, seed=42)
    loaded = load_split_lock(lock_path)
    assert loaded["seed"] == 42
    assert loaded["split_hash"] == split_hash(assignment)
    assert loaded["assignment"] == assignment


def test_test_access_counter_only_moves_on_explicit_increment(tmp_path):
    counter = TestAccessCounter(tmp_path / "test_access.json")
    assert counter.count == 0
    counter.increment("Checkpoint E frozen config, first test run")
    assert counter.count == 1
    counter.increment("re-run after a bug fix")
    assert counter.count == 2


def test_gold_questions_round_trip_through_jsonl(tmp_path):
    questions = [
        _q("q1"),
        GoldQuestion(
            qid="q2",
            slice="out_of_scope",
            question="does MC offer a PhD",
            gold=(),
            conjunctive=False,
            expected_referral="admissions@maryvillecollege.edu",
            provenance="real",
        ),
    ]
    path = tmp_path / "gold.jsonl"
    write_gold_questions(path, questions)
    loaded = load_gold_questions(path)
    assert loaded == questions
    assert loaded[0].provenance == "synthetic"
    assert loaded[1].provenance == "real"


def test_multi_turn_history_round_trips_through_jsonl(tmp_path):
    q = GoldQuestion(
        qid="mt1", slice="multi_turn", question="what about for international students?",
        gold=("ref-1",), conjunctive=False, history=("Does MC offer study abroad?", "Yes, ..."),
    )
    path = tmp_path / "gold.jsonl"
    write_gold_questions(path, [q])
    loaded = load_gold_questions(path)
    assert loaded[0].history == ("Does MC offer study abroad?", "Yes, ...")


def test_slice_targets_sum_to_roughly_300():
    assert sum(SLICE_TARGETS.values()) == 300
