"""Task 15/30: RESULTS.md generation from runs/."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from mcrag.eval.results_table import collect_runs, render_markdown, write_results_md


def _make_run(root: Path, run_id: str, arm: str, split: str, recall: float) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "config.yaml").write_text(
        yaml.safe_dump({"name": "t15", "arm": arm, "eval": {"split": split}}), encoding="utf-8"
    )
    metrics = {
        "recall@k": {"value": recall, "ci_low": recall - 0.05, "ci_high": recall + 0.05, "n": 60},
        "mrr": {"value": 0.5, "ci_low": 0.4, "ci_high": 0.6, "n": 60},
        "ndcg@k": {"value": 0.6, "ci_low": 0.5, "ci_high": 0.7, "n": 60},
        "all_golds_retrieved@k": {"value": 0.4, "ci_low": 0.3, "ci_high": 0.5, "n": 60},
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")


def test_collect_runs_skips_incomplete_dirs(tmp_path: Path):
    _make_run(tmp_path, "20260101T000000Z_abc", "dense-only", "dev", 0.7)
    (tmp_path / "not_a_run").mkdir()
    (tmp_path / "half_written").mkdir()
    (tmp_path / "half_written" / "config.yaml").write_text("name: x", encoding="utf-8")

    runs = collect_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "20260101T000000Z_abc"


def test_collect_runs_is_sorted_by_run_id(tmp_path: Path):
    _make_run(tmp_path, "20260102T000000Z_b", "arm-b", "dev", 0.5)
    _make_run(tmp_path, "20260101T000000Z_a", "arm-a", "dev", 0.5)
    runs = collect_runs(tmp_path)
    assert [r["run_id"] for r in runs] == ["20260101T000000Z_a", "20260102T000000Z_b"]


def test_render_markdown_includes_arm_split_and_metrics(tmp_path: Path):
    _make_run(tmp_path, "20260101T000000Z_abc", "dense-only", "dev", 0.712)
    runs = collect_runs(tmp_path)
    md = render_markdown(runs)
    assert "dense-only" in md
    assert "dev" in md
    assert "0.712" in md
    assert "n=60" in md


def test_write_results_md_regeneration_is_byte_identical(tmp_path: Path):
    _make_run(tmp_path, "20260101T000000Z_abc", "dense-only", "dev", 0.7)
    out = tmp_path / "RESULTS.md"
    first = write_results_md(tmp_path, out)
    second = write_results_md(tmp_path, out)
    assert first == second
    assert out.read_text(encoding="utf-8") == first


def test_empty_runs_dir_produces_a_header_only_table(tmp_path: Path):
    md = render_markdown(collect_runs(tmp_path / "does_not_exist"))
    assert "# RESULTS" in md
