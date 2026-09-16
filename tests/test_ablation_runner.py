"""Task 17: resumable, cached ablation sweep runner.

Verification step this file exists to satisfy: kill mid-sweep, resume,
confirm no duplicate generations and identical final metrics.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

from mcrag.config import Config
from mcrag.eval.ablation_runner import (
    GenerationCache,
    SweepPaused,
    find_or_create_run_dir,
    run_arm,
    run_matrix,
)
from mcrag.eval.stats import bootstrap_ci
from mcrag.runlog import RunDir
from mcrag.types import GoldQuestion


def _config(arm: str, **overrides) -> Config:
    return Config.from_dict({"name": "t17-test", "arm": arm, **overrides})


def _q(qid: str, question: str = "q") -> GoldQuestion:
    return GoldQuestion(qid=qid, slice="single_silo", question=question, gold=("a",), conjunctive=False)


def _summarize(records: list[dict]) -> dict:
    values = [r["score"] for r in records]
    return {"score": bootstrap_ci(values, statistic=statistics.mean, name="mean", seed=1).to_dict()}


# ---- find_or_create_run_dir -----------------------------------------------


def test_find_or_create_makes_a_new_dir_for_an_unseen_config(tmp_path: Path):
    config = _config("arm-a")
    run_dir = find_or_create_run_dir(config, root=tmp_path)
    assert run_dir.path.exists()
    assert run_dir.path.name.endswith(config.config_hash)


def test_find_or_create_reopens_the_same_dir_for_the_same_config(tmp_path: Path):
    config = _config("arm-a")
    first = find_or_create_run_dir(config, root=tmp_path)
    first.append({"query_id": "q1"})
    first.close()

    second = find_or_create_run_dir(config, root=tmp_path)
    assert second.path == first.path
    assert second.completed_ids() == {"q1"}


def test_find_or_create_gives_different_configs_different_dirs(tmp_path: Path):
    a = find_or_create_run_dir(_config("arm-a"), root=tmp_path)
    b = find_or_create_run_dir(_config("arm-b"), root=tmp_path)
    assert a.path != b.path


# ---- GenerationCache --------------------------------------------------------


def test_generation_cache_miss_then_hit(tmp_path: Path):
    cache = GenerationCache(tmp_path / "cache.jsonl")
    assert cache.get("m", "d1", "prompt text") is None
    cache.put("m", "d1", "prompt text", {"answer": "42"})
    assert cache.get("m", "d1", "prompt text") == {"answer": "42"}


def test_generation_cache_is_keyed_on_model_digest_and_prompt(tmp_path: Path):
    cache = GenerationCache(tmp_path / "cache.jsonl")
    cache.put("model-a", "digest-1", "same prompt", {"answer": "from a"})
    # Different model, different digest, and different prompt text each miss
    # independently -- none of the three alone identifies a cached reply.
    assert cache.get("model-b", "digest-1", "same prompt") is None
    assert cache.get("model-a", "digest-2", "same prompt") is None
    assert cache.get("model-a", "digest-1", "different prompt") is None
    assert cache.get("model-a", "digest-1", "same prompt") == {"answer": "from a"}


def test_generation_cache_persists_across_reload(tmp_path: Path):
    path = tmp_path / "cache.jsonl"
    cache = GenerationCache(path)
    cache.put("m", "d", "p", {"answer": "cached"})
    cache.close()

    reopened = GenerationCache(path)
    assert reopened.get("m", "d", "p") == {"answer": "cached"}
    assert len(reopened) == 1


def test_generation_cache_put_is_idempotent_on_disk(tmp_path: Path):
    path = tmp_path / "cache.jsonl"
    cache = GenerationCache(path)
    cache.put("m", "d", "p", {"answer": "first"})
    cache.put("m", "d", "p", {"answer": "second"})  # same key: ignored, not overwritten
    assert cache.get("m", "d", "p") == {"answer": "first"}
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


# ---- run_arm: resume and caching in practice -------------------------------


def test_run_arm_resumes_without_recalling_evaluate_fn_for_done_questions(tmp_path: Path):
    config = _config("arm-a")
    questions = [_q("q1"), _q("q2"), _q("q3")]
    calls: list[str] = []

    def evaluate_fn(q: GoldQuestion) -> dict:
        calls.append(q.qid)
        return {"query_id": q.qid, "score": 1.0}

    run_arm(config, questions, evaluate_fn, _summarize, root=tmp_path)
    assert calls == ["q1", "q2", "q3"]

    calls.clear()
    run_dir = run_arm(config, questions, evaluate_fn, _summarize, root=tmp_path)
    assert calls == []  # every question already on disk; nothing recomputed
    assert run_dir.completed_ids() == {"q1", "q2", "q3"}


def test_run_arm_raises_sweep_paused_on_a_quota_error_and_keeps_prior_records(tmp_path: Path):
    config = _config("arm-a")
    questions = [_q("q1"), _q("q2"), _q("q3")]

    class QuotaWall(RuntimeError):
        pass

    def evaluate_fn(q: GoldQuestion) -> dict:
        if q.qid == "q2":
            raise QuotaWall("out of quota")
        return {"query_id": q.qid, "score": 1.0}

    with pytest.raises(SweepPaused) as exc_info:
        run_arm(config, questions, evaluate_fn, _summarize, root=tmp_path, quota_errors=(QuotaWall,))
    assert exc_info.value.arm == "arm-a"
    assert exc_info.value.qid == "q2"

    run_dir = RunDir.open(find_or_create_run_dir(config, root=tmp_path).path)
    assert run_dir.completed_ids() == {"q1"}  # q1 landed; q2 never wrote a torn record
    assert not (run_dir.path / "metrics.json").exists()  # arm never finished, so never scored


def test_run_arm_resumes_past_a_quota_wall_and_finishes(tmp_path: Path):
    config = _config("arm-a")
    questions = [_q("q1"), _q("q2"), _q("q3")]

    class QuotaWall(RuntimeError):
        pass

    fail_once = {"armed": True}

    def evaluate_fn(q: GoldQuestion) -> dict:
        if q.qid == "q2" and fail_once["armed"]:
            fail_once["armed"] = False
            raise QuotaWall("out of quota")
        return {"query_id": q.qid, "score": 1.0}

    with pytest.raises(SweepPaused):
        run_arm(config, questions, evaluate_fn, _summarize, root=tmp_path, quota_errors=(QuotaWall,))

    run_dir = run_arm(config, questions, evaluate_fn, _summarize, root=tmp_path, quota_errors=(QuotaWall,))
    assert run_dir.completed_ids() == {"q1", "q2", "q3"}
    assert run_dir.read_metrics()  # arm completed this time, so it was scored


def test_run_arm_rejects_a_non_quota_error_immediately(tmp_path: Path):
    config = _config("arm-a")
    questions = [_q("q1")]

    def evaluate_fn(q: GoldQuestion) -> dict:
        raise ValueError("a real bug, not a quota wall")

    with pytest.raises(ValueError, match="a real bug"):
        run_arm(config, questions, evaluate_fn, _summarize, root=tmp_path, quota_errors=(RuntimeError,))


# ---- run_matrix: the full sweep verification step --------------------------


def test_run_matrix_stops_at_the_arm_that_hits_the_wall_then_resumes_the_rest(tmp_path: Path):
    configs = [_config("arm-a"), _config("arm-b"), _config("arm-c")]
    questions = [_q("q1"), _q("q2")]
    calls: list[tuple[str, str]] = []

    class QuotaWall(RuntimeError):
        pass

    tripped: set[str] = set()

    def evaluate_fn_for(config: Config):
        def evaluate_fn(q: GoldQuestion) -> dict:
            calls.append((config.arm, q.qid))
            if config.arm == "arm-b" and q.qid == "q2" and config.arm not in tripped:
                tripped.add(config.arm)
                raise QuotaWall("wall")
            return {"query_id": q.qid, "score": 1.0}

        return evaluate_fn

    with pytest.raises(SweepPaused) as exc_info:
        run_matrix(configs, questions, evaluate_fn_for, _summarize, root=tmp_path, quota_errors=(QuotaWall,))
    assert exc_info.value.arm == "arm-b"
    # arm-a ran to completion; arm-b got as far as its wall; arm-c never started
    assert ("arm-a", "q1") in calls and ("arm-a", "q2") in calls
    assert ("arm-b", "q1") in calls and ("arm-b", "q2") in calls
    assert not any(arm == "arm-c" for arm, _ in calls)

    calls.clear()
    results = run_matrix(configs, questions, evaluate_fn_for, _summarize, root=tmp_path, quota_errors=(QuotaWall,))
    # Resuming must not recall arm-a at all, and must not redo arm-b's q1.
    assert ("arm-a", "q1") not in calls and ("arm-a", "q2") not in calls
    assert ("arm-b", "q1") not in calls
    assert ("arm-b", "q2") in calls  # only the one that actually failed reruns
    assert set(results) == {"arm-a", "arm-b", "arm-c"}
    for run_dir in results.values():
        assert run_dir.completed_ids() == {"q1", "q2"}
        assert run_dir.read_metrics()


def test_run_matrix_final_metrics_are_identical_whether_or_not_a_wall_was_hit(tmp_path: Path):
    # Two independent sweeps of the same matrix, one uninterrupted and one
    # that pauses partway through, must land on the same numbers -- the
    # resumed run is not allowed to silently diverge from a clean run.
    configs_a = [_config("clean-a"), _config("clean-b")]
    configs_b = [_config("resumed-a"), _config("resumed-b")]
    questions = [_q(f"q{i}") for i in range(1, 5)]

    class QuotaWall(RuntimeError):
        pass

    tripped: set[str] = set()

    def evaluate_fn_for(config: Config):
        def evaluate_fn(q: GoldQuestion) -> dict:
            if config.arm == "resumed-a" and q.qid == "q3" and config.arm not in tripped:
                tripped.add(config.arm)
                raise QuotaWall("wall")
            return {"query_id": q.qid, "score": float(q.qid[-1])}

        return evaluate_fn

    clean_results = run_matrix(configs_a, questions, evaluate_fn_for, _summarize, root=tmp_path / "clean", quota_errors=(QuotaWall,))

    with pytest.raises(SweepPaused):
        run_matrix(configs_b, questions, evaluate_fn_for, _summarize, root=tmp_path / "resumed", quota_errors=(QuotaWall,))
    resumed_results = run_matrix(configs_b, questions, evaluate_fn_for, _summarize, root=tmp_path / "resumed", quota_errors=(QuotaWall,))

    clean_metrics = [rd.read_metrics() for rd in clean_results.values()]
    resumed_metrics = [rd.read_metrics() for rd in resumed_results.values()]
    assert clean_metrics == resumed_metrics
