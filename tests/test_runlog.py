"""Task 1 verification: config identity, run directories, resumability."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcrag.config import Config, ConfigError
from mcrag.interfaces import Reranker, Retriever
from mcrag.registry import allow_root, build, resolve
from mcrag.runlog import Lock, MetricShapeError, RunDir
from mcrag.types import Hit


def metric(value: float, n: int) -> dict:
    return {"value": value, "ci_low": value - 0.05, "ci_high": value + 0.05, "n": n}


class TestConfigIdentity:
    def test_round_trips_through_yaml(self, tmp_path: Path) -> None:
        original = Config.from_dict(
            {
                "name": "baseline",
                "arm": "dense-only",
                "retrieval": {"k": 10, "legs": [{"class": "mcrag.types:Hit", "weight": 1.0}]},
            }
        )
        path = tmp_path / "config.yaml"
        path.write_text(original.to_yaml(), encoding="utf-8")
        assert Config.from_yaml(path).config_hash == original.config_hash

    def test_identical_configs_hash_identically(self) -> None:
        a = Config.from_dict({"name": "x", "chunk": {"max_tokens": 400}})
        b = Config.from_dict({"chunk": {"max_tokens": 400}, "name": "x"})
        assert a.config_hash == b.config_hash

    def test_different_configs_hash_differently(self) -> None:
        a = Config.from_dict({"name": "x", "chunk": {"max_tokens": 400}})
        b = Config.from_dict({"name": "x", "chunk": {"max_tokens": 256}})
        assert a.config_hash != b.config_hash

    def test_hash_is_stable_across_processes(self, tmp_path: Path) -> None:
        """A hash from a dict id or memory address would be per-process.

        This is the check that catches it, and it matters because run directory
        names are compared across machines and across weeks.
        """
        src = (
            "import sys; sys.path.insert(0, r'%s');"
            "from mcrag.config import Config;"
            "print(Config.from_dict({'name':'x','chunk':{'max_tokens':400}}).config_hash)"
            % str(Path(__file__).resolve().parents[1])
        )
        out = subprocess.run(
            [sys.executable, "-c", src], capture_output=True, text=True, check=True
        )
        assert out.stdout.strip() == Config.from_dict(
            {"name": "x", "chunk": {"max_tokens": 400}}
        ).config_hash

    @pytest.mark.parametrize(
        "bad",
        [
            {"name": "x", "retreival": {}},
            {"name": "x", "chunk": {"max_token": 400}},
            {"name": "x", "generation": {"num_context": 8192}},
        ],
    )
    def test_unknown_keys_are_an_error(self, bad: dict) -> None:
        """A typo must not silently run a different arm than the one logged."""
        with pytest.raises(ConfigError):
            Config.from_dict(bad)

    def test_name_is_required(self) -> None:
        with pytest.raises(ConfigError):
            Config.from_dict({"arm": "a"})

    def test_seam_accepts_bare_string_or_mapping(self) -> None:
        cfg = Config.from_dict(
            {
                "name": "x",
                "retrieval": {
                    "legs": ["mcrag.types:Hit", {"class": "mcrag.types:Chunk", "weight": 2}]
                },
            }
        )
        assert cfg.retrieval.legs[0].cls == "mcrag.types:Hit"
        assert cfg.retrieval.legs[1].kwargs == {"weight": 2}

    def test_seam_mapping_without_class_key_is_an_error(self) -> None:
        with pytest.raises(ConfigError):
            Config.from_dict({"name": "x", "retrieval": {"legs": [{"weight": 2}]}})


class TestRegistry:
    """The runner instantiates from config with no branch on arm names."""

    def test_config_names_a_class_and_the_runner_builds_it(self) -> None:
        class FakeRetriever(Retriever):
            name = "fake"

            def __init__(self, k_boost: int = 0) -> None:
                self.k_boost = k_boost

            def search(self, query: str, k: int) -> list[Hit]:
                return [Hit("c1", 1.0, self.name, 1)] * (k + self.k_boost)

        # Register the test module so config can name a class defined here.
        sys.modules[__name__].FakeRetriever = FakeRetriever  # type: ignore[attr-defined]
        allow_root("tests")
        allow_root(__name__.split(".", 1)[0])

        cfg = Config.from_dict(
            {
                "name": "fake-arm",
                "retrieval": {"legs": [{"class": f"{__name__}:FakeRetriever", "k_boost": 2}]},
            }
        )
        leg = cfg.retrieval.legs[0]
        # This is the whole point: no `if arm == ...` anywhere below.
        built = build(leg.cls, Retriever, **leg.kwargs)
        assert isinstance(built, Retriever)
        assert len(built.search("q", 1)) == 3

    def test_bare_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="module.path:ClassName"):
            resolve("Hit")

    def test_imports_outside_the_allowlist_are_refused(self) -> None:
        with pytest.raises(ValueError, match="refusing to import"):
            resolve("subprocess:Popen")

    def test_wrong_seam_is_a_type_error(self) -> None:
        with pytest.raises(TypeError, match="cannot fill that seam"):
            build("mcrag.types:Hit", Reranker)


class TestRunDir:
    def test_creates_the_expected_layout(self, tmp_path: Path) -> None:
        cfg = Config.from_dict({"name": "demo"})
        run = RunDir.create(cfg, root=tmp_path, timestamp=datetime(2026, 9, 10, tzinfo=timezone.utc))
        assert run.path.name == f"20260910T000000Z_{cfg.config_hash}"
        for expected in ("config.yaml", "per_query.jsonl", "notes.md"):
            assert (run.path / expected).exists()

    def test_locks_are_reported_missing_until_written(self, tmp_path: Path) -> None:
        run = RunDir.create(Config.from_dict({"name": "demo"}), root=tmp_path)
        assert set(run.missing_locks) == {"corpus.lock", "model.lock", "split.lock"}
        run.write_lock(Lock("corpus", "abc123", {"pages": 812}))
        run.write_lock(Lock("model", "def456", {"model": "gpt-oss:20b-cloud"}))
        run.write_lock(Lock("split", "ghi789", {"split": "dev", "n": 60}))
        assert run.missing_locks == []
        assert run.read_lock("corpus").detail["pages"] == 812

    def test_unknown_lock_kind_is_refused(self, tmp_path: Path) -> None:
        run = RunDir.create(Config.from_dict({"name": "demo"}), root=tmp_path)
        with pytest.raises(ValueError):
            run.write_lock(Lock("weather", "x", {}))

    def test_per_query_requires_a_query_id(self, tmp_path: Path) -> None:
        run = RunDir.create(Config.from_dict({"name": "demo"}), root=tmp_path)
        with pytest.raises(ValueError, match="query_id"):
            run.append({"answer": "no id, so not resumable"})

    def test_records_round_trip(self, tmp_path: Path) -> None:
        run = RunDir.create(Config.from_dict({"name": "demo"}), root=tmp_path)
        with run:
            for i in range(5):
                run.append({"query_id": f"q{i}", "hit": i % 2 == 0})
        assert [r["query_id"] for r in run.records()] == [f"q{i}" for i in range(5)]
        assert run.completed_ids() == {"q0", "q1", "q2", "q3", "q4"}


class TestResumability:
    def test_killed_run_leaves_a_parsable_file(self, tmp_path: Path) -> None:
        """The Task 1 verification: kill mid-write, parse line by line.

        The child is killed hard, without a chance to flush or close. Anything
        the parent can still read is what the fsync bought.
        """
        root = tmp_path / "runs"
        src = f"""
import sys, time
sys.path.insert(0, r"{Path(__file__).resolve().parents[1]}")
from mcrag.config import Config
from mcrag.runlog import RunDir
run = RunDir.create(Config.from_dict({{"name": "demo"}}), root=r"{root}")
print(run.path, flush=True)
i = 0
while True:
    run.append({{"query_id": f"q{{i}}", "payload": "x" * 200}})
    i += 1
    time.sleep(0.01)
"""
        proc = subprocess.Popen(
            [sys.executable, "-c", src], stdout=subprocess.PIPE, text=True
        )
        try:
            run_path = Path(proc.stdout.readline().strip())
            time.sleep(0.6)
        finally:
            proc.kill()
            proc.wait(timeout=10)

        reopened = RunDir.open(run_path)
        records = list(reopened.records())
        assert len(records) >= 5, "fsync should have committed the completed records"
        ids = [r["query_id"] for r in records]
        assert ids == [f"q{i}" for i in range(len(ids))], "no gaps or duplicates"

    def test_torn_final_line_is_dropped_not_fatal(self, tmp_path: Path) -> None:
        run = RunDir.create(Config.from_dict({"name": "demo"}), root=tmp_path)
        with run:
            run.append({"query_id": "q0"})
        with (run.path / "per_query.jsonl").open("a", encoding="utf-8") as fh:
            fh.write('{"query_id": "q1", "trunca')
        assert [r["query_id"] for r in run.records()] == ["q0"]

    def test_reopening_resumes_rather_than_truncates(self, tmp_path: Path) -> None:
        cfg = Config.from_dict({"name": "demo"})
        first = RunDir.create(cfg, root=tmp_path)
        with first:
            first.append({"query_id": "q0"})
        second = RunDir.open(first.path)
        with second:
            second.append({"query_id": "q1"})
        assert second.completed_ids() == {"q0", "q1"}
        assert second.config.config_hash == cfg.config_hash


class TestMetricShape:
    def test_bare_float_is_refused(self, tmp_path: Path) -> None:
        """PLAN 4f: a point estimate with no n is not a reportable metric."""
        run = RunDir.create(Config.from_dict({"name": "demo"}), root=tmp_path)
        with pytest.raises(MetricShapeError, match="not a reportable metric"):
            run.write_metrics({"recall_at_10": 0.72})

    def test_interval_without_n_is_refused(self, tmp_path: Path) -> None:
        run = RunDir.create(Config.from_dict({"name": "demo"}), root=tmp_path)
        with pytest.raises(MetricShapeError, match="missing"):
            run.write_metrics({"recall_at_10": {"value": 0.72, "ci_low": 0.6, "ci_high": 0.8}})

    def test_well_formed_metrics_are_written(self, tmp_path: Path) -> None:
        run = RunDir.create(Config.from_dict({"name": "demo"}), root=tmp_path)
        run.write_metrics(
            {
                "overall": {"recall_at_10": metric(0.72, 120)},
                "by_slice": {"cross_silo": metric(0.51, 28)},
                "split": "test",
            }
        )
        written = json.loads((run.path / "metrics.json").read_text(encoding="utf-8"))
        assert written["by_slice"]["cross_silo"]["n"] == 28
        assert run.read_metrics() == written
