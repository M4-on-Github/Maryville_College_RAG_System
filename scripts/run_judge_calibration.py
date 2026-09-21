"""Score the calibration set with the Tier 3 judge (Nemotron) and the Tier 1 NLI
scorer, then measure both against the human labels.

Needs `data/calibration/labels.csv` fully filled in by the human. The judge
prompt/parse code is used directly rather than through `Tier3JudgeScorer.judge`
because that method refuses to run without a passing calibration -- and this
script is what produces one.

Outputs, all under `data/calibration/`:
  judge_outputs.jsonl        raw judge text per item (resumable, audit trail)
  calibration_result.json    kappa + CI, confusion matrix, per-generator
                             agreement, NLI-vs-human Spearman, judge-vs-NLI

    python scripts/run_judge_calibration.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_faithfulness import bootstrap_spearman, spearman  # noqa: E402

from mcrag.eval.calibration_set import read_human_labels  # noqa: E402
from mcrag.eval.judge_calibration import MIN_ACCEPTABLE_KAPPA, calibrate_judge, cohens_kappa  # noqa: E402
from mcrag.eval.nli_faithfulness import NLIFaithfulnessScorer  # noqa: E402
from mcrag.eval.tier0_scoring import looks_like_a_refusal  # noqa: E402
from mcrag.eval.tier3_judge import UnparseableJudgeOutputError, build_judge_prompt, parse_judge_score  # noqa: E402
from mcrag.generate.ollama_cloud import OllamaCloudGenerator  # noqa: E402

DIR = Path("data/calibration")
JUDGE_MODEL = "nemotron-3-nano:30b"
GENERATORS_JUDGED = {"gemma4:31b", "gpt-oss:20b"}
SEED = 42
# Nemotron reasons before answering; the default 1024-token reply budget is
# what the generation arms used and can be exhausted by reasoning alone.
JUDGE_MAX_TOKENS = 4096
JUDGE_NUM_CTX = 16384


def judge_all(items: list[dict]) -> dict[str, dict]:
    assert JUDGE_MODEL not in GENERATORS_JUDGED, "a judge must never grade its own output"
    path = DIR / "judge_outputs.jsonl"
    done = {}
    if path.exists():
        done = {r["item_id"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
    gen = OllamaCloudGenerator(
        model=JUDGE_MODEL, temperature=0.0, max_tokens=JUDGE_MAX_TOKENS,
        num_ctx=JUDGE_NUM_CTX, timeout_s=300.0,
    )
    with path.open("a", encoding="utf-8") as out:
        for it in items:
            if it["item_id"] in done:
                continue
            prompt = build_judge_prompt(it["question"], it["answer"], [p["text"] for p in it["passages"]])
            c = gen.complete(prompt)
            try:
                score, error = parse_judge_score(c.text), None
            except UnparseableJudgeOutputError as exc:
                score, error = None, str(exc)
            rec = {"item_id": it["item_id"], "score": score, "error": error, "text": c.text,
                   "finish_reason": c.finish_reason, "completion_tokens": c.usage.completion_tokens}
            out.write(json.dumps(rec) + "\n"); out.flush()
            done[it["item_id"]] = rec
            print(f"  {it['item_id']}: judge={score}")
    return done


def kappa_ci(a: list[int], b: list[int], iterations: int = 5000) -> tuple[float, float]:
    rng = random.Random(SEED)
    stats = []
    for _ in range(iterations):
        idx = [rng.randrange(len(a)) for _ in a]
        stats.append(cohens_kappa([a[i] for i in idx], [b[i] for i in idx]))
    stats.sort()
    return stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats)) - 1]


def main() -> int:
    items = json.loads((DIR / "items.json").read_text(encoding="utf-8"))
    human = read_human_labels(DIR / "labels.csv")
    missing = {i["item_id"] for i in items} - set(human)
    if missing:
        raise SystemExit(f"labels.csv is missing {len(missing)} items")

    judged = judge_all(items)
    ok = [i for i in items if judged[i["item_id"]]["score"] is not None]
    h = [human[i["item_id"]] for i in ok]
    j = [judged[i["item_id"]]["score"] for i in ok]

    cal = calibrate_judge(j, h)
    lo, hi = kappa_ci(j, h)
    confusion = {f"human{a}_judge{b}": sum(1 for x, y in zip(h, j) if x == a and y == b)
                 for a in (0, 1, 2) for b in (0, 1, 2)}
    by_generator = {}
    for model in sorted(GENERATORS_JUDGED):
        idx = [n for n, i in enumerate(ok) if i["model"] == model]
        by_generator[model] = {
            "n": len(idx),
            "exact_agreement": sum(h[n] == j[n] for n in idx) / len(idx) if idx else None,
            "mean_human": sum(h[n] for n in idx) / len(idx) if idx else None,
            "mean_judge": sum(j[n] for n in idx) / len(idx) if idx else None,
        }

    nli = NLIFaithfulnessScorer()
    nli_vals, nli_h, nli_j = [], [], []
    for n, it in enumerate(ok):
        if looks_like_a_refusal(it["answer"]):
            continue
        v = nli.score_answer(it["answer"], [p["text"] for p in it["passages"]]).value
        if v is not None:
            nli_vals.append(v); nli_h.append(float(h[n])); nli_j.append(float(j[n]))
    nli_lo, nli_hi = bootstrap_spearman(nli_vals, nli_h)
    nli_report = {
        "n": len(nli_vals),
        "spearman_vs_human": {"value": spearman(nli_vals, nli_h), "ci_low": nli_lo, "ci_high": nli_hi},
        "mean_nli_by_human_score": {
            str(g): (sum(v for v, hh in zip(nli_vals, nli_h) if hh == g) / max(1, sum(hh == g for hh in nli_h)))
            for g in (0, 1, 2)
        },
    }

    result = {
        "judge_model": JUDGE_MODEL,
        "n_items": len(items),
        "n_judged": len(ok),
        "n_unparseable": len(items) - len(ok),
        "kappa": {"value": cal.kappa, "ci_low": lo, "ci_high": hi, "n": cal.n, "floor": MIN_ACCEPTABLE_KAPPA},
        "passes_gate": cal.kappa >= MIN_ACCEPTABLE_KAPPA,
        "exact_agreement": sum(a == b for a, b in zip(h, j)) / len(h),
        "human_label_counts": dict(Counter(h)),
        "judge_label_counts": dict(Counter(j)),
        "confusion": confusion,
        "by_generator": by_generator,
        "nli": nli_report,
    }
    (DIR / "calibration_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
