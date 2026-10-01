"""Task 35: content-hash pinning, stale detection, and re-verification.

Tests for pin backfilling, staleness detection, and the metric exclusion
of stale questions.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

from mcrag.eval.gold import (
    ORIGIN_VALUES,
    Pin,
    ReverificationRecord,
    StaleQuestion,
    append_reverification_log,
    backfill_pins,
    find_stale_questions,
    load_chunks,
    load_gold_questions,
    reverify_pin,
    validate,
    write_gold_questions,
)
from mcrag.eval.retrieval_harness import evaluate_question, summarize
from mcrag.types import GoldQuestion


def test_pin_round_trips_through_json():
    """Pins serialize and deserialize correctly."""
    q = GoldQuestion(
        qid="test-q",
        slice="single_silo",
        question="test?",
        gold=("ref-1", "ref-2"),
        conjunctive=False,
        pins=(
            Pin(gold_ref="ref-1", content_hash="abc123", origin="backfill"),
            Pin(gold_ref="ref-2", content_hash="def456", origin="reverified"),
        ),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.jsonl"
        write_gold_questions(path, [q])
        loaded = load_gold_questions(path)
        assert len(loaded) == 1
        assert loaded[0].qid == q.qid
        assert len(loaded[0].pins) == 2
        assert loaded[0].pins[0].gold_ref == "ref-1"
        assert loaded[0].pins[0].content_hash == "abc123"
        assert loaded[0].pins[0].origin == "backfill"


def test_validate_accepts_questions_with_pins():
    """Validation passes for questions with valid pins."""
    q = GoldQuestion(
        qid="test",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(Pin(gold_ref="ref-1", content_hash="abc", origin="backfill"),),
    )
    assert validate(q) == []


def test_validate_rejects_pins_with_unknown_origin():
    """Validation rejects pins with invalid origin."""
    q = GoldQuestion(
        qid="test",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(Pin(gold_ref="ref-1", content_hash="abc", origin="unknown"),),
    )
    problems = validate(q)
    assert any("unknown origin" in p for p in problems)


def test_validate_rejects_pins_for_nonexistent_gold_refs():
    """Validation rejects pins that reference gold refs not in the question."""
    q = GoldQuestion(
        qid="test",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(Pin(gold_ref="ref-2", content_hash="abc", origin="backfill"),),
    )
    problems = validate(q)
    assert any("not in this question's gold set" in p for p in problems)


def test_validate_rejects_duplicate_pins_for_same_ref():
    """Validation rejects duplicate pins for the same gold ref."""
    q = GoldQuestion(
        qid="test",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(
            Pin(gold_ref="ref-1", content_hash="abc", origin="backfill"),
            Pin(gold_ref="ref-1", content_hash="def", origin="reverified"),
        ),
    )
    problems = validate(q)
    assert any("duplicate pin" in p for p in problems)


def test_backfill_pins_creates_pins_for_resolvable_refs():
    """Backfill creates pins for refs that resolve in the chunk lookup."""
    q = GoldQuestion(
        qid="test",
        slice="single_silo",
        question="q?",
        gold=("chunk-1", "chunk-2"),
        conjunctive=False,
        pins=(),
    )
    chunks = {
        "chunk-1": {
            "source_url": "https://example.com/page1",
            "content_hash": "hash1",
        },
        "chunk-2": {
            "source_url": "https://example.com/page2",
            "content_hash": "hash2",
        },
    }
    updated, unresolved = backfill_pins([q], chunks)
    assert len(updated) == 1
    assert len(updated[0].pins) == 2
    assert unresolved == []
    assert updated[0].pins[0].origin == "backfill"


def test_backfill_pins_reports_unresolvable_refs():
    """Backfill reports qids with refs that cannot be resolved."""
    q = GoldQuestion(
        qid="test-q",
        slice="single_silo",
        question="q?",
        gold=("chunk-1", "missing-chunk"),
        conjunctive=False,
        pins=(),
    )
    chunks = {
        "chunk-1": {
            "source_url": "https://example.com/page1",
            "content_hash": "hash1",
        },
    }
    updated, unresolved = backfill_pins([q], chunks)
    assert "test-q" in unresolved
    assert len(updated[0].pins) == 1  # Only chunk-1 was pinned


def test_backfill_pins_preserves_existing_pins():
    """Backfill does not overwrite existing pins."""
    q = GoldQuestion(
        qid="test",
        slice="single_silo",
        question="q?",
        gold=("ref-1", "ref-2"),
        conjunctive=False,
        pins=(Pin(gold_ref="ref-1", content_hash="old-hash", origin="authored"),),
    )
    chunks = {
        "ref-1": {"source_url": "https://example.com/1", "content_hash": "new-hash"},
        "ref-2": {"source_url": "https://example.com/2", "content_hash": "hash2"},
    }
    updated, unresolved = backfill_pins([q], chunks)
    # ref-1's existing pin should be kept, ref-2 should be added
    assert len(updated[0].pins) == 2
    ref1_pins = [p for p in updated[0].pins if p.gold_ref == "ref-1"]
    assert len(ref1_pins) == 1
    assert ref1_pins[0].content_hash == "old-hash"  # Preserved
    assert ref1_pins[0].origin == "authored"  # Preserved


def test_find_stale_questions_detects_hash_mismatch():
    """Stale detection identifies questions whose pin hashes no longer match."""
    q = GoldQuestion(
        qid="test",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(Pin(gold_ref="ref-1", content_hash="old-hash", origin="backfill"),),
    )
    chunks = {
        "ref-1": {
            "source_url": "https://example.com/page",
            "content_hash": "new-hash",
        },
    }
    stale = find_stale_questions([q], chunks)
    assert len(stale) == 1
    assert stale[0].qid == "test"
    assert stale[0].gold_ref == "ref-1"
    assert stale[0].pinned_hash == "old-hash"
    assert stale[0].current_hash == "new-hash"
    assert stale[0].source_url == "https://example.com/page"


def test_find_stale_questions_detects_missing_chunks():
    """Stale detection identifies refs where the chunk no longer exists."""
    q = GoldQuestion(
        qid="test",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(Pin(gold_ref="ref-1", content_hash="hash1", origin="backfill"),),
    )
    chunks = {}  # ref-1 doesn't exist
    stale = find_stale_questions([q], chunks)
    assert len(stale) == 1
    assert stale[0].current_hash == "(missing)"
    assert stale[0].source_url == "(unknown)"


def test_reverify_pin_updates_hash_and_logs():
    """Re-verification updates the pin hash and appends to the log."""
    q = GoldQuestion(
        qid="test-q",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(Pin(gold_ref="ref-1", content_hash="old-hash", origin="backfill"),),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "reverification_log.jsonl"
        updated_q = reverify_pin(
            [q],
            qid="test-q",
            gold_ref="ref-1",
            new_hash="new-hash",
            reverified_by="test@example.com",
            note="page was updated",
            log_path=log_path,
        )
        assert updated_q is not None
        assert updated_q.qid == "test-q"
        assert len(updated_q.pins) == 1
        assert updated_q.pins[0].content_hash == "new-hash"
        assert updated_q.pins[0].origin == "reverified"
        # Check the log
        assert log_path.exists()
        with log_path.open(encoding="utf-8") as f:
            record = json.loads(f.read())
        assert record["qid"] == "test-q"
        assert record["gold_ref"] == "ref-1"
        assert record["old_hash"] == "old-hash"
        assert record["new_hash"] == "new-hash"
        assert record["reverified_by"] == "test@example.com"
        assert record["note"] == "page was updated"


def test_reverify_pin_creates_new_pin_if_none_existed():
    """Re-verification can create a new pin if one didn't exist."""
    q = GoldQuestion(
        qid="test-q",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "reverification_log.jsonl"
        updated_q = reverify_pin(
            [q],
            qid="test-q",
            gold_ref="ref-1",
            new_hash="new-hash",
            reverified_by="test@example.com",
            log_path=log_path,
        )
        assert updated_q is not None
        assert len(updated_q.pins) == 1
        assert updated_q.pins[0].content_hash == "new-hash"
        # Log should record old_hash as "(none)"
        with log_path.open(encoding="utf-8") as f:
            record = json.loads(f.read())
        assert record["old_hash"] == "(none)"


def test_reverify_pin_returns_none_for_missing_qid():
    """Re-verification returns None if the qid doesn't exist."""
    q = GoldQuestion(
        qid="test-q",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "reverification_log.jsonl"
        result = reverify_pin(
            [q],
            qid="nonexistent",
            gold_ref="ref-1",
            new_hash="new-hash",
            reverified_by="test@example.com",
            log_path=log_path,
        )
        assert result is None
        # Log should not have been created for missing qid
        assert not log_path.exists()


def test_reverification_log_is_append_only():
    """Reverification log entries are appended, never deleted or overwritten."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "reverification_log.jsonl"
        q1 = GoldQuestion(
            qid="q1",
            slice="single_silo",
            question="q?",
            gold=("ref-1",),
            conjunctive=False,
            pins=(Pin(gold_ref="ref-1", content_hash="hash1", origin="backfill"),),
        )
        q2 = GoldQuestion(
            qid="q2",
            slice="single_silo",
            question="q?",
            gold=("ref-2",),
            conjunctive=False,
            pins=(Pin(gold_ref="ref-2", content_hash="hash2", origin="backfill"),),
        )
        # First reverification
        reverify_pin([q1], "q1", "ref-1", "new-hash1", "user1", log_path=log_path)
        # Second reverification
        reverify_pin([q2], "q2", "ref-2", "new-hash2", "user2", log_path=log_path)
        # Both should be in the log
        with log_path.open(encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2
        r1 = json.loads(lines[0])
        r2 = json.loads(lines[1])
        assert r1["qid"] == "q1"
        assert r2["qid"] == "q2"


def test_evaluate_question_skips_stale_questions():
    """evaluate_question returns a skip record for stale questions."""
    from mcrag.retrieval.dense import DenseIndex

    q = GoldQuestion(
        qid="stale-q",
        slice="single_silo",
        question="q?",
        gold=("ref-1",),
        conjunctive=False,
        pins=(Pin(gold_ref="ref-1", content_hash="hash", origin="backfill"),),
    )
    # A mock retriever (we won't actually call it)
    class MockRetriever:
        def search(self, query: str, k: int) -> list:
            return []

    result = evaluate_question(
        MockRetriever(), q, k=5, stale_qids={"stale-q"}
    )
    assert result["skipped"] == "stale"


def test_summarize_reports_stale_count():
    """The summarize function reports stale questions separately."""
    records = [
        {
            "query_id": "q1",
            "slice": "single_silo",
            "conjunctive": False,
            "skipped": "stale",
        },
        {
            "query_id": "q2",
            "slice": "single_silo",
            "conjunctive": False,
            "recall@k": 1.0,
            "mrr": 1.0,
            "ndcg@k": 1.0,
            "all_golds_retrieved@k": 1.0,
        },
        {
            "query_id": "q3",
            "slice": "single_silo",
            "conjunctive": False,
            "skipped": "no_gold_refs",
        },
    ]
    metrics = summarize(records, stale_checked=True)
    assert metrics["run"]["n_stale"] == "1"
    assert metrics["run"]["n_scored"] == "1"
    assert metrics["run"]["n_skipped"] == "2"  # Total skipped (stale + other)

    # Same records, but nobody checked for decay: the count must say so rather
    # than report the 1 it happens to see, or report 0.
    assert summarize(records)["run"]["n_stale"] == "unchecked"
