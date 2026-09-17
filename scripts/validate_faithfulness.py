"""Does Tier 1 faithfulness track human judgment? Checked against Task 16's
25 hand-scored answers (0 = wrong/ungrounded, 1 = partial, 2 = correct and
grounded), offline, no quota.

Pass criterion, fixed before the numbers were computed (Task 20): Tier 1 is
fit to remain the primary generation metric only if
  (a) mean faithfulness rises monotonically across hand scores 0 -> 1 -> 2, and
  (b) the Spearman rank correlation's 95% bootstrap CI excludes zero.
Refusals are excluded -- PLAN scores them separately (R), and faithfulness
is undefined for them.

The T16 set is 20 twos, 3 ones, 2 zeros: it can expose a metric that's badly
broken, but has little power to confirm a good one. Both are reported.

    python scripts/validate_faithfulness.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import statistics
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.eval.nli_faithfulness import SCORER_VERSION, NLIFaithfulnessScorer  # noqa: E402
from mcrag.eval.tier0_scoring import looks_like_a_refusal  # noqa: E402

T16_RUN = Path("runs/20260915T004143Z_2a62552d2271")
T16_CHUNKS = Path("corpus/baseline_chunks.jsonl")  # T15 baseline index the T16 answers were retrieved from
V1_COMMIT = "bf29473"  # Task 19's shipped scorer, the one that truncated
OUT_PATH = Path("runs/faithfulness_validation.json")


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1  # average rank for ties
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    rx, ry = _ranks(x), _ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return cov / var if var else 0.0


def bootstrap_spearman(x: list[float], y: list[float], seed: int = 42, iterations: int = 10_000) -> tuple[float, float]:
    rng = random.Random(seed)
    stats = []
    for _ in range(iterations):
        idx = [rng.randrange(len(x)) for _ in x]
        xs, ys = [x[i] for i in idx], [y[i] for i in idx]
        if len(set(xs)) > 1 and len(set(ys)) > 1:
            stats.append(spearman(xs, ys))
    if not stats:
        # A scorer that gives every answer the same value has no rank order
        # to correlate -- undefined, and it cannot pass.
        return float("nan"), float("nan")
    stats.sort()
    return stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats)) - 1]


def _v1_scorer():
    source = subprocess.run(
        ["git", "show", f"{V1_COMMIT}:mcrag/eval/nli_faithfulness.py"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    path = Path(os.environ.get("TMP", ".")) / "_faithfulness_v1.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_faithfulness_v1", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_faithfulness_v1"] = module
    spec.loader.exec_module(module)
    return module.NLIFaithfulnessScorer()


def evaluate(label: str, scorer, rows: list[dict], texts: dict[str, str]) -> dict:
    scores, humans = [], []
    for row in rows:
        context = [texts[r["chunk_id"]] for r in row["retrieved"] if r["chunk_id"] in texts]
        value = scorer.score_answer(row["answer"], context).value
        if value is not None:
            scores.append(value)
            humans.append(float(row["hand_score"]))

    by_group = {}
    for g in (0, 1, 2):
        group = [s for s, h in zip(scores, humans) if h == g]
        by_group[str(g)] = {"mean": statistics.mean(group) if group else None, "n": len(group)}
    means = [by_group[str(g)]["mean"] for g in (0, 1, 2)]
    monotone = all(m is not None for m in means) and means[0] <= means[1] <= means[2]

    constant = len(set(scores)) <= 1
    rho = float("nan") if constant else spearman(scores, humans)
    lo, hi = bootstrap_spearman(scores, humans)
    return {
        "scorer": label,
        "n_scored": len(scores),
        "distinct_values": len(set(scores)),
        "mean_by_hand_score": by_group,
        "monotone": monotone and not constant,
        "spearman": {"value": rho, "ci_low": lo, "ci_high": hi, "n": len(scores)},
        "passes": bool(monotone and not constant and lo == lo and lo > 0),
    }


def main() -> int:
    rows = [json.loads(line) for line in (T16_RUN / "per_query.jsonl").open(encoding="utf-8")]
    rows = [r for r in rows if r.get("ok") and r.get("hand_score") is not None]
    answered = [r for r in rows if not looks_like_a_refusal(r["answer"])]
    print(f"{len(rows)} hand-scored answers, {len(rows) - len(answered)} refusals excluded, {len(answered)} scored")

    texts = {}
    with T16_CHUNKS.open(encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line)
            texts[raw["chunk_id"]] = raw["text"]

    results = [
        evaluate(f"v1 (commit {V1_COMMIT}, joined premise)", _v1_scorer(), answered, texts),
        evaluate(SCORER_VERSION, NLIFaithfulnessScorer(), answered, texts),
    ]
    for r in results:
        g = r["mean_by_hand_score"]
        fmt = lambda k: "--" if g[k]["mean"] is None else f"{g[k]['mean']:.3f} (n={g[k]['n']})"
        s = r["spearman"]
        print(
            f"\n{r['scorer']}\n  mean faithfulness by hand score: 0={fmt('0')}  1={fmt('1')}  2={fmt('2')}"
            f"\n  distinct values across {r['n_scored']} answers: {r['distinct_values']}"
            f"\n  monotone: {r['monotone']}"
            f"\n  spearman: {s['value']:.3f} [{s['ci_low']:.3f}, {s['ci_high']:.3f}] (n={s['n']})"
            f"\n  PASSES pre-set criterion: {r['passes']}"
        )

    OUT_PATH.write_text(json.dumps({"criterion": __doc__.split("Refusals")[0].strip(), "results": results}, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
