"""Task 14: the retrieval eval loop -- gold set in, run dir + metrics.json out."""

from __future__ import annotations

from pathlib import Path

from mcrag.config import Config
from mcrag.eval.retrieval_harness import evaluate_question, run, summarize
from mcrag.runlog import RunDir
from mcrag.types import GoldQuestion, Hit


class _FakeRetriever:
    """Returns a canned, ranked hit list per query text, ignoring k semantics
    beyond truncation -- deterministic, so a test can hand-verify the score."""

    def __init__(self, hits_by_query: dict[str, list[str]]) -> None:
        self._hits = hits_by_query

    def search(self, query: str, k: int) -> list[Hit]:
        ids = self._hits.get(query, [])[:k]
        return [Hit(chunk_id=cid, score=1.0 / (i + 1), leg="fake", rank=i + 1) for i, cid in enumerate(ids)]


def _q(qid, slice_="single_silo", question="q", gold=("a",), conjunctive=False):
    return GoldQuestion(qid=qid, slice=slice_, question=question, gold=gold, conjunctive=conjunctive)


def test_evaluate_question_scores_a_hit():
    retriever = _FakeRetriever({"q1": ["a", "b", "c"]})
    question = _q("ss-1", question="q1", gold=("a",))
    record = evaluate_question(retriever, question, k=3)
    assert record["recall@k"] == 1.0
    assert record["mrr"] == 1.0
    assert record["all_golds_retrieved@k"] == 1.0
    assert record["query_id"] == "ss-1"


def test_evaluate_question_skips_questions_with_no_gold():
    retriever = _FakeRetriever({})
    question = _q("oos-1", slice_="out_of_scope", question="anything", gold=())
    record = evaluate_question(retriever, question, k=3)
    assert record["skipped"] == "no_gold_refs"
    assert "recall@k" not in record


def test_summarize_reports_conjunctive_breakout():
    records = [
        evaluate_question(_FakeRetriever({"q1": ["a", "b"]}), _q("cs-1", "cross_silo", "q1", ("a", "b"), True), k=3),
        evaluate_question(_FakeRetriever({"q2": ["a"]}), _q("cs-2", "cross_silo", "q2", ("a", "z"), True), k=3),
    ]
    summary = summarize(records, seed=1)
    assert summary["conjunctive_all_golds_retrieved@k"]["n"] == 2
    # one found both golds, one found only one -> mean all_golds_retrieved@k = 0.5
    assert summary["conjunctive_all_golds_retrieved@k"]["value"] == 0.5


def test_summarize_excludes_skipped_from_scored_metrics():
    scored = evaluate_question(_FakeRetriever({"q1": ["a"]}), _q("ss-1", question="q1", gold=("a",)), k=3)
    skipped = evaluate_question(_FakeRetriever({}), _q("oos-1", "out_of_scope", "q2", ()), k=3)
    summary = summarize([scored, skipped], seed=1)
    assert summary["run"]["n_scored"] == "1"
    assert summary["run"]["n_skipped"] == "1"
    assert summary["recall@k"]["n"] == 1


def test_run_writes_a_valid_run_dir_and_is_resumable(tmp_path: Path):
    config = Config.from_dict({"name": "t14-test", "retrieval": {"k": 3}})
    retriever = _FakeRetriever({"q1": ["a", "b"], "q2": ["z"]})
    questions = [
        _q("ss-1", question="q1", gold=("a",)),
        _q("ss-2", question="q2", gold=("a",)),
    ]

    run_dir = RunDir.create(config, root=tmp_path)
    metrics = run(retriever, questions, k=3, run_dir=run_dir)
    assert metrics["run"]["n_scored"] == "2"
    assert (run_dir.path / "metrics.json").exists()
    assert (run_dir.path / "per_query.jsonl").exists()

    # Resuming an already-complete run must not re-score anything (a query
    # whose text isn't in _FakeRetriever's map would return no hits and
    # silently change the numbers if it reran).
    reopened = RunDir.open(run_dir.path)
    second_pass_retriever = _FakeRetriever({})  # would score everything 0 if re-run
    metrics_again = run(second_pass_retriever, questions, k=3, run_dir=reopened)
    assert metrics_again == metrics
