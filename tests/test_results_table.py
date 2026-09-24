"""Task 15/30: RESULTS.md generation from runs/."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from mcrag.eval.results_table import (
    collect_runs,
    render_factorial_section,
    render_markdown,
    write_results_md,
)


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


# ---- Task 18: the factorial main-effects/interactions section --------------


def _write_factorial_summary(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "headline_k": 5,
                "n_cells": 32,
                "main_effects": {"reranker": 0.0573, "boilerplate": -0.0156},
                "interactions": {"boilerplate*reranker": 0.026},
            }
        ),
        encoding="utf-8",
    )


def test_render_factorial_section_is_empty_when_no_summary_exists(tmp_path: Path):
    assert render_factorial_section(tmp_path / "missing.json") == ""


def test_render_factorial_section_reports_main_effects_and_interactions(tmp_path: Path):
    summary_path = tmp_path / "summary.json"
    _write_factorial_summary(summary_path)
    section = render_factorial_section(summary_path)
    assert "Main effects" in section
    assert "reranker" in section and "+0.0573" in section
    assert "boilerplate*reranker" in section and "+0.0260" in section
    assert "32 cells" in section


def test_write_results_md_without_factorial_path_has_no_factorial_section(tmp_path: Path):
    _make_run(tmp_path, "20260101T000000Z_abc", "dense-only", "dev", 0.7)
    md = write_results_md(tmp_path, tmp_path / "RESULTS.md")
    assert "Task 18" not in md


def test_write_results_md_appends_the_factorial_section_when_given_a_real_path(tmp_path: Path):
    _make_run(tmp_path, "20260101T000000Z_abc", "dense-only", "dev", 0.7)
    summary_path = tmp_path / "summary.json"
    _write_factorial_summary(summary_path)
    md = write_results_md(tmp_path, tmp_path / "RESULTS.md", factorial_summary_path=summary_path)
    assert "dense-only" in md  # the ordinary leaderboard is still there
    assert "Task 18" in md  # and the factorial section is appended after it


def _gen_run(root, run_id, arm, split, faith, walls):
    _make_run(root, run_id, arm, split, 0.7)
    d = root / run_id
    m = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    m["faithfulness"] = {"value": faith, "ci_low": faith - 0.1, "ci_high": faith + 0.1, "n": 50}
    (d / "metrics.json").write_text(json.dumps(m), encoding="utf-8")
    (d / "per_query.jsonl").write_text("\n".join(json.dumps({"wall_s": w}) for w in walls), encoding="utf-8")


def test_cost_is_median_not_mean_and_retrieval_only_has_none(tmp_path):
    from mcrag.eval.results_table import median_wall_s

    _gen_run(tmp_path, "20260101T000000Z_a", "gen", "dev", 0.5, [1.0, 1.0, 100.0])
    _make_run(tmp_path, "20260101T000001Z_b", "retrieval-only", "dev", 0.7)
    a, b = collect_runs(tmp_path)
    assert median_wall_s(a) == 1.0  # a mean would be 34
    assert median_wall_s(b) is None
    assert render_markdown([a, b]).count("| -- |") >= 1


def test_controls_are_marked_in_role_column(tmp_path):
    _make_run(tmp_path, "20260101T000000Z_a", "3a-dense-only-naive-chunks", "dev", 0.7)
    _make_run(tmp_path, "20260101T000001Z_b", "something-else", "dev", 0.7)
    md = render_markdown(collect_runs(tmp_path))
    assert "control 3a" in md
    assert md.count("control") == 1


def test_pareto_frontier_excludes_dominated_and_other_splits(tmp_path):
    from mcrag.eval.results_table import pareto_points

    _gen_run(tmp_path, "20260101T000000Z_a", "cheap-ok", "dev", 0.4, [1.0])
    _gen_run(tmp_path, "20260101T000001Z_b", "dear-good", "dev", 0.6, [3.0])
    _gen_run(tmp_path, "20260101T000002Z_c", "dominated", "dev", 0.3, [4.0])
    _gen_run(tmp_path, "20260101T000003Z_d", "test-run", "test", 0.9, [0.1])
    pts = {p["run"]["config"]["arm"]: p["frontier"] for p in pareto_points(collect_runs(tmp_path))}
    assert pts == {"cheap-ok": True, "dear-good": True, "dominated": False}


def test_regeneration_is_byte_identical(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _gen_run(runs, "20260101T000000Z_a", "gen", "dev", 0.5, [1.0, 2.0])
    out = tmp_path / "RESULTS.md"
    write_results_md(runs, out)
    first = (out.read_bytes(), (tmp_path / "results_pareto.svg").read_bytes())
    out.unlink()
    (tmp_path / "results_pareto.svg").unlink()
    write_results_md(runs, out)
    assert first == (out.read_bytes(), (tmp_path / "results_pareto.svg").read_bytes())
