"""Task 15 (minimal) / Task 30 (full): `RESULTS.md`, regenerated from `runs/`.

Never hand-edited (Task 30's own acceptance criterion) -- this module is the
only thing allowed to write it. Task 15 needs just a leaderboard of the
retrieval metrics; Task 30 later adds a cost column and a Pareto-frontier plot
once generation runs exist to plot. Both read the same run-dir layout, so this
module is written once and extended, not replaced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

METRIC_COLUMNS = ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k")


def _load_run(run_path: Path) -> dict[str, Any] | None:
    config_path = run_path / "config.yaml"
    metrics_path = run_path / "metrics.json"
    if not config_path.exists() or not metrics_path.exists():
        return None
    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    return {"run_id": run_path.name, "config": config, "metrics": metrics}


def collect_runs(runs_root: str | Path = "runs") -> list[dict[str, Any]]:
    """Every run dir under `runs_root` that has both a config and metrics.

    Sorted by `run_id` (the timestamp prefix), so the table's row order is
    deterministic and reproducible byte-for-byte on regeneration (Task 30's
    verification step).
    """
    root = Path(runs_root)
    if not root.exists():
        return []
    runs = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        run = _load_run(child)
        if run is not None:
            runs.append(run)
    return runs


def _fmt_metric(metrics: dict[str, Any], key: str) -> str:
    m = metrics.get(key)
    if not isinstance(m, dict) or "value" not in m:
        return "--"
    return f"{m['value']:.3f} [{m['ci_low']:.3f}, {m['ci_high']:.3f}] (n={m['n']})"


def render_markdown(runs: list[dict[str, Any]]) -> str:
    """The leaderboard, as a single Markdown table.

    A run with no `arm` name falls back to `name` -- every `Config` carries
    one or the other, but a hand-built config in a test fixture might not.
    """
    lines = [
        "# RESULTS",
        "",
        "Regenerated from `runs/` by `scripts/generate_results.py` -- never hand-edited.",
        "",
        "| run | arm | split | " + " | ".join(METRIC_COLUMNS) + " |",
        "|---" * (3 + len(METRIC_COLUMNS)) + "|",
    ]
    for run in runs:
        config = run["config"]
        metrics = run["metrics"]
        arm = config.get("arm") or config.get("name") or "?"
        split = (config.get("eval") or {}).get("split") or "?"
        row = [run["run_id"], arm, split]
        row.extend(_fmt_metric(metrics, key) for key in METRIC_COLUMNS)
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def write_results_md(runs_root: str | Path = "runs", out_path: str | Path = "RESULTS.md") -> str:
    runs = collect_runs(runs_root)
    markdown = render_markdown(runs)
    Path(out_path).write_text(markdown, encoding="utf-8")
    return markdown
