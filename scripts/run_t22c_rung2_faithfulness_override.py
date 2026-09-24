"""Task 22c rung 2: calibrated post-hoc faithfulness override -- decisions/0014.

Rung 1 (`scope_strict_gemma4_31b`, `scripts/run_t22c_scope_signal.py`) was
kept but didn't close the gap alone: 3/12 `out_of_scope` dev questions still
get a false answer. Rung 2 stacks a post-generation override on top of it --
if the drafted answer's Tier 1 faithfulness falls below a fitted threshold,
replace it with a refusal -- reusing rung 1's already-generated answers and
already-computed faithfulness scores. **Zero new generation calls.**

Unlike rung 0's diagnostic "refuse if faithfulness == 0.0" (chosen after
looking at the full sample, no train/dev split), this fits the threshold
with the same out-of-fold discipline `decisions/0009` used for the
cross-encoder tau: `mcrag.eval.abstention`'s `cross_validate`/`choose_tau`
are signal-agnostic pure functions over (feature, label, strata) -- reused
here verbatim with `feature = tier1_faithfulness`, `label = expects_answer`
(in-scope, i.e. correct to have answered) computed only over rung 1's
*answered* records (47/60; the other 13 are already refused and out of
scope for this override). This is the identical risk class as the rejected
CE gate -- a threshold trading answered-coverage for answered-precision --
so it gets the identical anti-leakage treatment, not a shortcut because the
signal lives at the answer level instead of the retrieval level.

    python scripts/run_t22c_rung2_faithfulness_override.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.eval.abstention import FLOOR, cross_validate, choose_tau, ratio_ci, sweep  # noqa: E402
from mcrag.eval.significance import paired_bootstrap_comparison  # noqa: E402
from mcrag.eval.stats import bootstrap_ci  # noqa: E402
from mcrag.runlog import RunDir  # noqa: E402

RUNG1_PRIMARY = Path("runs/20260922T201857Z_d6b307f5beff")  # scope_strict_gemma4_31b
RUNG0_REFERENCE = Path("runs/20260922T201857Z_3caf1dd6d3bd")  # free_form_gemma4_31b_a
FOLDS = 5
CV_SEED = 42
FLOORS = (FLOOR, 0.80)  # 0.95 (module default, decisions/0009's original), 0.80 (its own post-hoc-lowered floor)


def _mean_ci(values: list[float]) -> dict[str, Any]:
    return bootstrap_ci(values, statistics.mean, seed=42, name="mean").to_dict()


def _interval(iv) -> dict[str, Any] | None:
    return None if iv is None else iv.to_dict()


def fit_override(answered: list[dict[str, Any]], floor: float) -> dict[str, Any]:
    """Out-of-fold: for each answered record, decide keep-answered/override-to-refuse
    using a threshold fitted on the other folds only. Mirrors `run_tau_calibration.py`
    exactly, feature-for-feature swapped."""
    features = [r["tier1_faithfulness"] for r in answered]
    labels = [bool(r["expects_answer"]) for r in answered]
    strata = [r["slice"] for r in answered]

    cv = cross_validate(features, labels, strata, FOLDS, CV_SEED, floor)
    oof_keep = cv.oof_answered  # True = override keeps it answered

    coverage = bootstrap_ci([1.0 if k else 0.0 for k in oof_keep], statistics.mean, name="mean", seed=42)
    precision = ratio_ci(labels, oof_keep)
    false_refusal = ratio_ci([not k for k in oof_keep], labels)

    return {
        "floor": floor,
        "n_answered": len(answered),
        "n_legit": sum(labels),
        "n_false_answer": len(labels) - sum(labels),
        "fold_taus": cv.fold_taus,
        "in_sample_tau_reference_only": choose_tau(features, labels, floor),
        "oof_coverage": coverage.to_dict(),
        "oof_precision_among_kept": _interval(precision),
        "oof_false_refusal_rate_of_legit": _interval(false_refusal),
        "oof_keep_flags": {r["query_id"]: k for r, k in zip(answered, oof_keep)},
        "curve": [
            {"tau": p.tau, "coverage": p.coverage, "precision": p.precision, "false_refusal_rate": p.false_refusal_rate}
            for p in sweep(features, labels)
            if p.precision is not None
        ],
    }


def apply_override(rung1_records: list[dict[str, Any]], keep_flags: dict[str, bool]) -> dict[str, dict[str, Any]]:
    """Rebuild every dev record's post-override refused/refusal_correct/faithfulness,
    leaving already-refused records untouched."""
    out: dict[str, dict[str, Any]] = {}
    for r in rung1_records:
        qid = r["query_id"]
        if r["tier0"]["refused"]:
            new_refused = True
            new_faith = None
        elif qid in keep_flags and not keep_flags[qid]:
            new_refused = True  # override fires: drafted answer replaced with a refusal
            new_faith = None
        else:
            new_refused = False
            new_faith = r["tier1_faithfulness"]
        out[qid] = {
            "slice": r["slice"],
            "expects_answer": r["expects_answer"],
            "refused": new_refused,
            "refusal_correct": new_refused != r["expects_answer"],
            "faithfulness": new_faith,
            "citation_accuracy": r["tier0"]["citation_accuracy"] if not new_refused else None,
            "citation_validity": r["tier0"]["citation_validity"] if not new_refused else None,
        }
    return out


def compare(before: dict[str, dict], after: dict[str, dict], label: str, slice_filter: str | None = None) -> dict[str, Any]:
    qids = sorted(set(before) & set(after))
    if slice_filter is not None:
        qids = [q for q in qids if before[q]["slice"] == slice_filter]

    def paired(value_fn, metric: str) -> dict[str, Any] | None:
        both = [q for q in qids if value_fn(before[q]) is not None and value_fn(after[q]) is not None]
        if not both:
            return None
        result = paired_bootstrap_comparison(
            [float(value_fn(before[q])) for q in both], [float(value_fn(after[q])) for q in both],
            split="dev", metric=f"{label}:{metric}",
        )
        return result.interval.to_dict()

    return {
        "label": label,
        "slice": slice_filter or "pooled",
        "n_questions": len(qids),
        "after_minus_before": {
            "refusal_correct": paired(lambda r: 1.0 if r["refusal_correct"] else 0.0, "refusal_correct"),
            "faithfulness": paired(lambda r: r["faithfulness"], "faithfulness"),
            "citation_accuracy": paired(lambda r: r["citation_accuracy"], "citation_accuracy"),
            "citation_validity": paired(lambda r: r["citation_validity"], "citation_validity"),
        },
    }


def absolute_rate(records: dict[str, dict], slice_filter: str) -> dict[str, Any]:
    sub = [r for r in records.values() if r["slice"] == slice_filter]
    n = len(sub)
    refused = sum(1 for r in sub if r["refused"])
    return {"n": n, "refused": refused, "false_answer_rate": (n - refused) / n if n else None}


def main() -> int:
    rung1_records = list(RunDir.open(RUNG1_PRIMARY).records())
    rung0_records = list(RunDir.open(RUNG0_REFERENCE).records())
    answered = [r for r in rung1_records if not r["tier0"]["refused"]]
    print(f"rung 1 ({RUNG1_PRIMARY.name}): {len(rung1_records)} dev records, {len(answered)} answered -> override population")

    baseline0 = {
        r["query_id"]: {
            "slice": r["slice"], "expects_answer": r["expects_answer"],
            "refused": r["tier0"]["refused"], "refusal_correct": r["tier0"]["refusal_correct"],
            "faithfulness": r.get("tier1_faithfulness") if not r["tier0"]["refused"] else None,
            "citation_accuracy": r["tier0"]["citation_accuracy"], "citation_validity": r["tier0"]["citation_validity"],
        }
        for r in rung0_records
    }
    analysis: dict[str, Any] = {
        "rung1_run": str(RUNG1_PRIMARY), "rung0_reference_run": str(RUNG0_REFERENCE),
        "n_dev": len(rung1_records), "out_of_scope_rung0_baseline": absolute_rate(baseline0, "out_of_scope"),
        "by_floor": {},
    }

    for floor in FLOORS:
        fit = fit_override(answered, floor)
        after = apply_override(rung1_records, fit["oof_keep_flags"])
        before = {
            r["query_id"]: {
                "slice": r["slice"], "expects_answer": r["expects_answer"],
                "refused": r["tier0"]["refused"], "refusal_correct": r["tier0"]["refusal_correct"],
                "faithfulness": r.get("tier1_faithfulness") if not r["tier0"]["refused"] else None,
                "citation_accuracy": r["tier0"]["citation_accuracy"], "citation_validity": r["tier0"]["citation_validity"],
            }
            for r in rung1_records
        }
        analysis["by_floor"][str(floor)] = {
            "fit": fit,
            "out_of_scope_before": absolute_rate(before, "out_of_scope"),
            "out_of_scope_after": absolute_rate(after, "out_of_scope"),
            "primary_out_of_scope": compare(before, after, "rung2_vs_rung1", slice_filter="out_of_scope"),
            "pooled": compare(before, after, "rung2_vs_rung1"),
            "cumulative_vs_rung0_baseline_out_of_scope": compare(baseline0, after, "rung1+2_vs_rung0", slice_filter="out_of_scope"),
            "cumulative_vs_rung0_baseline_pooled": compare(baseline0, after, "rung1+2_vs_rung0"),
        }

    out_path = Path("runs/t22c_rung2_faithfulness_override_analysis.json")
    out_path.write_text(json.dumps(analysis, indent=2, default=str), encoding="utf-8")

    def fmt(iv):
        if iv is None:
            return "--"
        return f"{iv['value']:+.3f} [{iv['ci_low']:+.3f}, {iv['ci_high']:+.3f}] (n={iv['n']})"

    for floor in FLOORS:
        d = analysis["by_floor"][str(floor)]
        f = d["fit"]
        print(f"\n== floor={floor:.0%} == fold taus: {[round(t, 3) if t != float('inf') else 'inf' for t in f['fold_taus']]}")
        print(f"  override population: {f['n_answered']} answered ({f['n_legit']} legit, {f['n_false_answer']} false-answer)")
        print(f"  OOF coverage-of-answered {fmt(f['oof_coverage'])}  precision-among-kept {fmt(f['oof_precision_among_kept'])}  false-refusal-of-legit {fmt(f['oof_false_refusal_rate_of_legit'])}")
        print(f"  out_of_scope false-answer rate: before {d['out_of_scope_before']['false_answer_rate']:.3f} ({d['out_of_scope_before']['refused']}/{d['out_of_scope_before']['n']} refused) "
              f"-> after {d['out_of_scope_after']['false_answer_rate']:.3f} ({d['out_of_scope_after']['refused']}/{d['out_of_scope_after']['n']} refused)")
        print("  pooled dev, rung2 - rung1:")
        for k, v in d["pooled"]["after_minus_before"].items():
            print(f"    {k:<20} {fmt(v)}")
        print(f"  cumulative (rung1+2) - rung0 baseline, out_of_scope slice:")
        for k, v in d["cumulative_vs_rung0_baseline_out_of_scope"]["after_minus_before"].items():
            print(f"    {k:<20} {fmt(v)}")
        print(f"  cumulative (rung1+2) - rung0 baseline, pooled:")
        for k, v in d["cumulative_vs_rung0_baseline_pooled"]["after_minus_before"].items():
            print(f"    {k:<20} {fmt(v)}")

    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
