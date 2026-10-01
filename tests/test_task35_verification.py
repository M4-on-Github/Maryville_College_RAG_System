"""Task 35 verification: mutate a fixture page and watch the question drop out.

The acceptance criterion is not "staleness can be detected" -- it is that a
changed page makes the affected questions *leave the metrics* and *show up in
the stale count with their URLs*. So this drives the real harness end to end
rather than only calling the detector.

Every guard here is a hard failure or an explicit `pytest.skip`. The earlier
draft of this file returned early when the corpus or the pins were missing,
which meant a checkout with no corpus reported a green test that had verified
nothing -- exactly the failure mode pinning exists to prevent.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from mcrag.config import Config
from mcrag.eval.gold import (
    find_stale_questions,
    load_chunks,
    load_gold_questions,
)
from mcrag.eval.retrieval_harness import run
from mcrag.runlog import RunDir
from mcrag.types import Hit

GOLD_PATH = Path("data/gold/gold_v1.jsonl")
CHUNKS_PATH = Path("corpus/chunks.jsonl")


class _StubRetriever:
    """Returns each question's own gold refs, so every scored question is a hit.

    That makes the stale question the only thing that can move the numbers.
    """

    def __init__(self, by_question: dict[str, tuple[str, ...]]) -> None:
        self._by_question = by_question

    def search(self, query: str, k: int) -> list[Hit]:
        refs = self._by_question.get(query, ())
        return [
            Hit(chunk_id=ref, score=1.0 / (i + 1), leg="stub", rank=i + 1)
            for i, ref in enumerate(refs[:k])
        ]


def _pinned_questions():
    if not GOLD_PATH.exists() or not CHUNKS_PATH.exists():
        pytest.skip(f"needs {GOLD_PATH} and {CHUNKS_PATH}")
    questions = load_gold_questions(GOLD_PATH)
    pinned = [q for q in questions if q.pins]
    # Not a skip: the committed gold set *has* pins, and a run where it stopped
    # having them is a regression in the thing under test, not a missing fixture.
    assert pinned, "the committed gold set carries no pins; backfill has regressed"
    return questions, pinned


def test_mutated_page_is_reported_stale_with_its_url():
    questions, pinned = _pinned_questions()
    chunks = load_chunks(CHUNKS_PATH)

    target = pinned[0]
    pin = target.pins[0]
    chunk = chunks[pin.gold_ref]

    clean = find_stale_questions(questions, chunks)
    assert not [s for s in clean if s.qid == target.qid], (
        "the unmutated corpus already reports this question stale; "
        "the pins and the corpus have drifted apart"
    )

    mutated = dict(chunks)
    mutated[pin.gold_ref] = {**chunk, "content_hash": "mutated-" + pin.content_hash}

    stale = find_stale_questions(questions, mutated)
    hits = [s for s in stale if s.qid == target.qid and s.gold_ref == pin.gold_ref]
    assert len(hits) == 1, f"mutation of {pin.gold_ref} was not detected"

    record = hits[0]
    assert record.pinned_hash == pin.content_hash
    assert record.current_hash == "mutated-" + pin.content_hash
    # The URL is the whole point of the report: it is what a human opens to
    # re-read the page before re-verifying the pin.
    assert record.source_url == chunk["source_url"]
    assert "://" in record.source_url


def test_a_stale_question_leaves_the_metrics_and_shows_in_the_count(tmp_path: Path):
    questions, pinned = _pinned_questions()
    chunks = load_chunks(CHUNKS_PATH)

    target = pinned[0]
    pin = target.pins[0]
    cohort = [q for q in pinned if q.gold][:8]
    assert target in cohort
    retriever = _StubRetriever({q.question: q.gold for q in cohort})
    config = Config.from_dict({"name": "t35-verification", "retrieval": {"k": 5}})

    baseline = run(
        retriever,
        cohort,
        k=5,
        run_dir=RunDir.create(config, root=tmp_path / "clean"),
        stale_qids=set(),
    )
    assert baseline["run"]["n_scored"] == str(len(cohort))
    assert baseline["run"]["n_stale"] == "0"

    mutated = dict(chunks)
    mutated[pin.gold_ref] = {
        **chunks[pin.gold_ref],
        "content_hash": "mutated-" + pin.content_hash,
    }
    stale_qids = {s.qid for s in find_stale_questions(cohort, mutated)}
    assert target.qid in stale_qids

    after = run(
        retriever,
        cohort,
        k=5,
        run_dir=RunDir.create(config, root=tmp_path / "mutated"),
        stale_qids=stale_qids,
    )
    # Dropped out of the denominator, and visibly so.
    assert after["run"]["n_stale"] == str(len(stale_qids))
    assert int(after["run"]["n_scored"]) == len(cohort) - len(stale_qids)
    assert after["recall@k"]["n"] == len(cohort) - len(stale_qids)


def test_an_unchecked_run_says_unchecked_rather_than_zero(tmp_path: Path):
    """`stale_qids=None` is a caller saying "I did not look" -- it must not read 0."""
    questions, pinned = _pinned_questions()
    cohort = [q for q in pinned if q.gold][:4]
    retriever = _StubRetriever({q.question: q.gold for q in cohort})
    config = Config.from_dict({"name": "t35-unchecked", "retrieval": {"k": 5}})

    metrics = run(
        retriever,
        cohort,
        k=5,
        run_dir=RunDir.create(config, root=tmp_path),
        stale_qids=None,
    )
    assert metrics["run"]["n_stale"] == "unchecked"


def test_stale_marking_never_edits_the_question_text():
    questions, pinned = _pinned_questions()
    before = {q.qid: q.question for q in questions}
    chunks = load_chunks(CHUNKS_PATH)
    pin = pinned[0].pins[0]
    mutated = dict(chunks)
    mutated[pin.gold_ref] = {**chunks[pin.gold_ref], "content_hash": "mutated"}

    find_stale_questions(questions, mutated)
    after = {q.qid: q.question for q in load_gold_questions(GOLD_PATH)}
    assert after == before
    # And the record itself is frozen, so no stale-marking code path could have
    # edited the question text even if it tried.
    with pytest.raises(FrozenInstanceError):
        questions[0].question = "rewritten"  # type: ignore[misc]
