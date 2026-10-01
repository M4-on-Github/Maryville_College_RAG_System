"""Task 15 (minimal) / Task 30 (full): `RESULTS.md`, regenerated from `runs/`.

Never hand-edited (Task 30's own acceptance criterion) -- this module is the
only thing allowed to write it. Task 15 built the retrieval leaderboard; Task 30
adds the cost column, control markers and the quality/cost Pareto frontier.
Both read the same run-dir layout, so this module was extended, not replaced.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

METRIC_COLUMNS = ("recall@k", "mrr", "ndcg@k", "all_golds_retrieved@k")

# Baseline controls (PLAN Phase 3): 3a retrieval baseline, 3c generation baseline.
# There is no 3b run dir -- 3b was a read-through sanity check, not a scored run.
CONTROL_ARMS = {
    "3a-dense-only-naive-chunks": "control 3a",
    "phase3c-baseline": "control 3c",
}

PARETO_SVG = "results_pareto.svg"


def _per_query_wall_s(path: Path) -> list[float]:
    """Per-question generation wall time, or [] for a retrieval-only run.

    Read from `per_query.jsonl` rather than the run-level `wall_s` mean because
    PLAN 4f says cost is summarised by the **median, never the mean** -- cold
    starts skew a mean.
    """
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            wall = json.loads(line).get("wall_s")
            if isinstance(wall, (int, float)):
                out.append(float(wall))
    return out


def _load_run(run_path: Path) -> dict[str, Any] | None:
    config_path = run_path / "config.yaml"
    metrics_path = run_path / "metrics.json"
    if not config_path.exists() or not metrics_path.exists():
        return None
    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    return {
        "run_id": run_path.name,
        "config": config,
        "metrics": metrics,
        "wall_s": _per_query_wall_s(run_path / "per_query.jsonl"),
    }


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


def run_role(run: dict[str, Any]) -> str:
    return CONTROL_ARMS.get(run["config"].get("arm") or "", "")


def median_wall_s(run: dict[str, Any]) -> float | None:
    return statistics.median(run["wall_s"]) if run["wall_s"] else None


def _fmt_cost(run: dict[str, Any]) -> str:
    med = median_wall_s(run)
    if med is None:
        return "--"
    tokens = run["metrics"].get("completion_tokens")
    tok = f", {tokens['value']:.0f} tok" if isinstance(tokens, dict) and "value" in tokens else ""
    return f"{med:.2f}s median{tok} (n={len(run['wall_s'])})"


def render_markdown(runs: list[dict[str, Any]]) -> str:
    """The leaderboard, as a single Markdown table.

    Every row carries its split, its n (inside each metric cell) and its cost
    next to quality. Cost is `--` for retrieval-only runs: they spend no
    generation quota, and a made-up 0 would plot as a free lunch. Controls are
    marked in the `role` column. A run with no `arm` name falls back to `name`.

    Task 35: the stale count (`n_stale`) is reported next to `n_scored` as
    `scored / stale`, so a shrinking denominator is never silently conflated
    with improved retrieval performance. A `?` there means the run never
    checked -- runs recorded before pinning existed, and any run whose caller
    passed `stale_qids=None` -- and is deliberately not shown as `0`.
    """
    lines = [
        "# RESULTS",
        "",
        "Regenerated from `runs/` by `scripts/generate_results.py` -- never hand-edited.",
        "",
        "Cost is the **median** per-question generation wall time (PLAN 4f: never the "
        "mean) with mean completion tokens; `--` means the run made no generation "
        "calls. Quality cells are `value [95% CI] (n=questions)`.",
        "",
        "| run | arm | role | split | scored / stale | " + " | ".join(METRIC_COLUMNS) + " | faithfulness | cost |",
        "|---" * (5 + len(METRIC_COLUMNS) + 2) + "|",
    ]
    for run in runs:
        config = run["config"]
        metrics = run["metrics"]
        arm = config.get("arm") or config.get("name") or "?"
        split = (config.get("eval") or {}).get("split") or "?"
        run_info = metrics.get("run", {})
        n_scored = run_info.get("n_scored", "?")
        # Task 35: a run from before pinning existed never checked for decay, so
        # its stale count is `?` -- the same thing the module already prints for
        # an unknown split. Defaulting it to 0 would publish "no decay" on the
        # strength of nobody having looked.
        n_stale = run_info.get("n_stale") or "?"
        if n_stale == "unchecked":
            n_stale = "?"
        row = [run["run_id"], arm, run_role(run), split, f"{n_scored}/{n_stale}"]
        row.extend(_fmt_metric(metrics, key) for key in METRIC_COLUMNS)
        row.extend([_fmt_metric(metrics, "faithfulness"), _fmt_cost(run)])
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def pareto_points(runs: list[dict[str, Any]], split: str = "dev") -> list[dict[str, Any]]:
    """Generation runs on one split with both a quality and a cost, each flagged
    if on the frontier (no other point is both cheaper-or-equal and
    better-or-equal, strictly better on at least one). Dev only by default:
    mixing dev and test in one frontier would compare different question sets.
    """
    pts = []
    for run in runs:
        faith = run["metrics"].get("faithfulness")
        cost = median_wall_s(run)
        if (run["config"].get("eval") or {}).get("split") != split:
            continue
        if cost is None or not isinstance(faith, dict) or "value" not in faith:
            continue
        pts.append({"run": run, "cost": cost, "quality": faith["value"]})
    for p in pts:
        p["frontier"] = not any(
            q["cost"] <= p["cost"]
            and q["quality"] >= p["quality"]
            and (q["cost"] < p["cost"] or q["quality"] > p["quality"])
            for q in pts
        )
    return pts


def render_pareto_svg(points: list[dict[str, Any]]) -> str:
    """Hand-written SVG, no plotting dependency: matplotlib output embeds
    nondeterministic ids, which would break Task 30's byte-identical check."""
    if not points:
        return ""
    w, h, ml, mr, mt, mb = 720, 420, 60, 20, 20, 50
    xs = [p["cost"] for p in points]
    ys = [p["quality"] for p in points]
    x0, x1 = 0.0, max(xs) * 1.1
    y0, y1 = min(ys) - 0.05, max(ys) + 0.05

    def px(v: float) -> float:
        return ml + (v - x0) / (x1 - x0) * (w - ml - mr)

    def py(v: float) -> float:
        return h - mb - (v - y0) / (y1 - y0) * (h - mt - mb)

    mid_y = (mt + h - mb) / 2
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        'font-family="sans-serif" font-size="11">',
        f'<rect width="{w}" height="{h}" fill="white"/>',
        f'<line x1="{ml}" y1="{h - mb}" x2="{w - mr}" y2="{h - mb}" stroke="black"/>',
        f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{h - mb}" stroke="black"/>',
        f'<text x="{(ml + w - mr) / 2:.0f}" y="{h - 12}" text-anchor="middle">'
        "median generation wall time per question (s) -- lower is cheaper</text>",
        f'<text x="14" y="{mid_y:.0f}" text-anchor="middle" '
        f'transform="rotate(-90 14 {mid_y:.0f})">Tier 1 faithfulness (dev)</text>',
    ]
    for t in range(0, int(x1) + 1):
        out.append(f'<text x="{px(t):.1f}" y="{h - mb + 14}" text-anchor="middle">{t}</text>')
    for i in range(5):
        v = y0 + (y1 - y0) * i / 4
        out.append(f'<text x="{ml - 6}" y="{py(v) + 4:.1f}" text-anchor="end">{v:.2f}</text>')
    front = sorted((p for p in points if p["frontier"]), key=lambda p: p["cost"])
    if len(front) > 1:
        path = " ".join(f"{px(p['cost']):.1f},{py(p['quality']):.1f}" for p in front)
        out.append(f'<polyline points="{path}" fill="none" stroke="#c33" stroke-width="1.5"/>')
    for p in points:
        colour = "#c33" if p["frontier"] else "#888"
        x, y = px(p["cost"]), py(p["quality"])
        label = p["run"]["config"].get("arm") or "?"
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{colour}"/>')
        out.append(f'<text x="{x + 6:.1f}" y="{y - 5:.1f}" fill="{colour}">{label}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_pareto_section(runs: list[dict[str, Any]], svg_name: str = PARETO_SVG) -> str:
    pts = pareto_points(runs)
    if not pts:
        return ""
    lines = [
        "",
        "## Quality / cost Pareto frontier (PLAN 4b)",
        "",
        f"![quality vs cost]({svg_name})",
        "",
        "Dev split, generation runs only. Quality is Tier 1 faithfulness (the primary "
        "generation metric, `decisions/0006`); cost is the median per-question wall "
        "time. Frontier points (red) are not beaten on both axes by any other run. "
        "Cost is cloud wall time, so it carries queue and cold-start noise: read the "
        "spread between same-model reruns as the noise floor before reading any "
        "frontier gap as an effect. Faithfulness alone can be bought by refusing "
        "more, so a frontier point is not an endorsement: check `refusal_correct` "
        "in the table above (`answerability_gate` sits on this frontier and was "
        "rejected in `decisions/0014` for exactly that). Test-split runs are in the table above, "
        "deliberately not on this frontier.",
        "",
        "| run | arm | faithfulness | median wall_s | on frontier |",
        "|---|---|---|---|---|",
    ]
    for p in sorted(pts, key=lambda p: (p["cost"], -p["quality"])):
        r = p["run"]
        lines.append(
            f"| {r['run_id']} | {r['config'].get('arm') or '?'} | {p['quality']:.3f} | "
            f"{p['cost']:.2f} | {'yes' if p['frontier'] else ''} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_factorial_section(summary_path: str | Path) -> str:
    """Task 18's main-effects/interactions tables, generated from the JSON
    `scripts/run_phase4_free_ablations.py` writes -- never hand-typed, same
    "never hand-edited" invariant `write_results_md` already holds for the
    per-run leaderboard above it. Returns "" if the file doesn't exist yet,
    so `write_results_md` stays a no-op addition before T18 has run.
    """
    path = Path(summary_path)
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = [
        "",
        "## Task 18: free retrieval factorial -- main effects and interactions",
        "",
        f"`all_golds_retrieved@{data['headline_k']}`, {data['n_cells']} cells, "
        "dev split, zero generation quota. Effects are in the metric's own "
        "units (a difference of means, PLAN Sec 4b's \"worth +X\" framing); "
        "interactions follow the standard half-the-difference-of-simple-effects "
        "convention -- see `mcrag.eval.factorial`.",
        "",
        "### Main effects",
        "",
        "| factor | effect |",
        "|---|---|",
    ]
    for factor, effect in sorted(data["main_effects"].items(), key=lambda kv: -abs(kv[1])):
        lines.append(f"| {factor} | {effect:+.4f} |")
    lines += ["", "### Two-way interactions", "", "| factors | effect |", "|---|---|"]
    for pair, effect in sorted(data["interactions"].items(), key=lambda kv: -abs(kv[1])):
        lines.append(f"| {pair} | {effect:+.4f} |")
    lines.append("")
    return "\n".join(lines)


def write_results_md(
    runs_root: str | Path = "runs",
    out_path: str | Path = "RESULTS.md",
    factorial_summary_path: str | Path | None = None,
) -> str:
    runs = collect_runs(runs_root)
    markdown = render_markdown(runs)
    if factorial_summary_path is not None:
        markdown += render_factorial_section(factorial_summary_path)
    markdown += render_pareto_section(runs)
    out = Path(out_path)
    svg = render_pareto_svg(pareto_points(runs))
    if svg:
        (out.parent / PARETO_SVG).write_text(svg, encoding="utf-8", newline="\n")
    out.write_text(markdown, encoding="utf-8", newline="\n")
    return markdown
