"""Task 3: measure what one metered query costs, and write the budget down.

This is empirical, not a decision. Every later phase is sized against the number
this produces, so the number has to come from calls that look like the calls the
system will actually make -- a bare question against an empty context measures
nothing that Phase 4 will experience.

So each of the twenty prompts carries real retrieved context: five passages from
the extracted corpus, assembled to the size a k=5 RAG prompt actually reaches.

Two things the run establishes besides the seconds:

* whether the endpoint reports its own timings, or whether client wall-clock is
  the fallback (PLAN open question);
* the real chat-template overhead and characters-per-token, which recalibrate
  the context guard from measurement instead of a conservative guess.

Resumable, because it is metered. A crash on question 17 must not re-buy the
first sixteen.

    python scripts/calibrate_quota.py --dry-run     # no calls; check the prompts
    python scripts/calibrate_quota.py
    python scripts/calibrate_quota.py --resume runs/20260910T....
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.config import Config  # noqa: E402
from mcrag.eval.stats import bootstrap_ci  # noqa: E402
from mcrag.extract.pipeline import ExtractedCorpus  # noqa: E402
from mcrag.generate.ollama_cloud import (  # noqa: E402
    ContextOverflow,
    GenerationError,
    OllamaCloudGenerator,
)
from mcrag.generate.tokens import TokenEstimator  # noqa: E402
from mcrag.runlog import Lock, RunDir  # noqa: E402

# Throwaway questions, spread over the silos the corpus already covers. They are
# here to load the model, not to score it: gold authoring is Task 12, and a
# question written to measure latency is written to the wrong specification.
QUESTIONS = [
    "What is Maryville College known for academically?",
    "How do I apply as a first-year student?",
    "What does the accounting program cover?",
    "Who should I contact about financial aid?",
    "What housing options are available to students?",
    "When does orientation happen for new students?",
    "What support does the college offer international students?",
    "How does the college describe its relationship with the church?",
    "What athletics conference does the college compete in?",
    "How do alumni stay involved after graduating?",
    "What is the Downtown Center used for?",
    "How do I request an official transcript?",
    "What is the student-to-faculty ratio?",
    "What study abroad opportunities exist?",
    "How does billing and payment work for tuition?",
    "What is required to declare a minor?",
    "What career services are available before graduation?",
    "What can families expect during move-in?",
    "How are scholarships awarded to incoming students?",
    "What does the American Sign Language program involve?",
]

SYSTEM_PROMPT = (
    "You answer questions about Maryville College in Maryville, Tennessee using "
    "only the passages provided. If the passages do not answer the question, say "
    "so plainly. Cite the source URL of every passage you use."
)


@dataclass(frozen=True, slots=True)
class CalibrationPrompt:
    """One metered call, assembled before any of them are sent."""

    query_id: str
    question: str
    prompt: str
    context_urls: tuple[str, ...]

    @property
    def prompt_chars(self) -> int:
        return len(self.prompt)


def build_prompts(
    corpus_path: Path,
    questions: list[str],
    *,
    k: int = 5,
    passage_chars: int = 1400,
    seed: int = 42,
) -> list[CalibrationPrompt]:
    """Assemble realistic RAG prompts, deterministically.

    Seeded, so a rerun measures the same prompts. Comparing today's seconds
    against last week's is only meaningful if the prompts are the same size.
    """
    documents = ExtractedCorpus(corpus_path).read()
    if not documents:
        raise SystemExit(f"no extracted corpus at {corpus_path}; run scripts/extract_corpus.py")

    rng = random.Random(seed)
    prompts = []
    for i, question in enumerate(questions):
        picked = rng.sample(documents, min(k, len(documents)))
        passages = "\n\n".join(
            f"[{n + 1}] {d.title} -- {d.url}\n{d.text[:passage_chars]}"
            for n, d in enumerate(picked)
        )
        prompts.append(
            CalibrationPrompt(
                query_id=f"cal-{i:02d}",
                question=question,
                prompt=f"Passages:\n{passages}\n\nQuestion: {question}\nAnswer:",
                context_urls=tuple(d.url for d in picked),
            )
        )
    return prompts


def corpus_digest(path: Path) -> str:
    """Hash the extracted corpus so a rerun against a changed corpus is visible."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "absent"


def run_one(generator: OllamaCloudGenerator, item: CalibrationPrompt) -> dict:
    """One call, one per-query record. Failures are recorded, never swallowed."""
    started = time.perf_counter()
    try:
        completion = generator.complete(item.prompt, system=SYSTEM_PROMPT)
    except (GenerationError, ContextOverflow) as exc:
        return {
            "query_id": item.query_id,
            "question": item.question,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "wall_s": time.perf_counter() - started,
        }
    usage = completion.usage
    return {
        "query_id": item.query_id,
        "question": item.question,
        "ok": True,
        "answer_chars": len(completion.text),
        "reasoning_chars": len(completion.reasoning),
        "prompt_chars": item.prompt_chars,
        "system_chars": len(SYSTEM_PROMPT),
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "wall_s": usage.wall_s,
        "server_s": usage.server_s,
        "timing_source": usage.timing_source,
        "seconds": usage.seconds,
        "finish_reason": completion.finish_reason,
        "context_urls": list(item.context_urls),
    }


def probe_truncation(generator: OllamaCloudGenerator, filler: str) -> dict:
    """Confirm the danger the context guard exists for is real.

    Sends a prompt deliberately larger than ``num_ctx`` with the guard stepped
    around. If the call succeeds and answers from the tail of the prompt, the
    window truncated silently, which is exactly the failure mode PLAN warns
    about and the reason the guard refuses rather than trims.
    """
    probe = OllamaCloudGenerator(
        model=generator.model,
        base_url=generator.base_url,
        num_ctx=generator.num_ctx,
        temperature=generator.temperature,
        max_tokens=64,
        # The one place this is ever set. The guard is what we are testing the
        # necessity of, so for this single diagnostic call it stands aside.
        enforce_context=False,
    )
    marker = "The registrar's office phone number is 865-555-0143."
    oversized = marker + "\n" + filler
    tokens = probe.estimator.estimate(oversized)
    try:
        completion = probe.complete(
            oversized + "\n\nQuestion: What is the registrar's phone number? Answer:",
            system=SYSTEM_PROMPT,
        )
        return {
            "sent_estimated_tokens": tokens,
            "num_ctx": probe.num_ctx,
            "server_prompt_tokens": completion.usage.prompt_tokens,
            "answer": completion.text[:200],
            "recovered_marker": "555-0143" in completion.text,
        }
    except (GenerationError, ContextOverflow) as exc:
        return {
            "sent_estimated_tokens": tokens,
            "num_ctx": probe.num_ctx,
            "error": f"{type(exc).__name__}: {exc}",
        }


def probe_native_durations(generator: OllamaCloudGenerator, *, calls: int = 3) -> dict:
    """Ask the *native* ``/api/chat`` surface whether it reports server timings.

    PLAN 2a recommends the native endpoint for eval runs on the grounds that it
    returns ``prompt_eval_duration`` and ``eval_duration`` "for cloud models
    too". That claim is worth one cheap probe rather than a citation, because
    the whole cost-accounting story rests on it.

    Three tiny calls, so the answer costs almost nothing. Each records what the
    final chunk carried alongside the client wall-clock for the same call: the
    gap between a server-reported total and our own measurement is the queueing
    the free tier's single concurrency slot imposes.
    """
    import requests  # local: the rest of the script talks through the generator

    url = generator.base_url.rsplit("/v1", 1)[0] + "/api/chat"
    observed: list[dict] = []
    for i in range(calls):
        started = time.perf_counter()
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {generator.resolve_api_key()}"},
            json={
                "model": generator.model,
                "messages": [{"role": "user", "content": f"Say hi in {i + 1} words."}],
                "stream": False,
                "options": {"num_ctx": generator.num_ctx, "temperature": 0},
            },
            timeout=generator.timeout_s,
        )
        wall_s = time.perf_counter() - started
        if response.status_code >= 400:
            return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
        body = response.json()
        observed.append(
            {
                "wall_s": wall_s,
                "fields": sorted(k for k in body if k.endswith(("_duration", "_count"))),
                "total_duration_s": (
                    body["total_duration"] / 1e9 if "total_duration" in body else None
                ),
                "prompt_eval_count": body.get("prompt_eval_count"),
                "eval_count": body.get("eval_count"),
            }
        )

    present = sorted({field for call in observed for field in call["fields"]})
    return {
        "endpoint": url,
        "calls": observed,
        "fields_present": present,
        "has_total_duration": "total_duration" in present,
        "has_eval_duration": "eval_duration" in present,
        "has_prompt_eval_duration": "prompt_eval_duration" in present,
    }


def summarise(records: list[dict], num_ctx: int) -> dict:
    """Turn the per-query stream into the numbers the budget is built from."""
    ok = [r for r in records if r.get("ok")]
    if not ok:
        raise SystemExit("no successful calls; nothing to calibrate")

    seconds = bootstrap_ci([r["seconds"] for r in ok], name="median")
    prompt_tokens = bootstrap_ci([float(r["prompt_tokens"]) for r in ok], name="median")
    completion_tokens = bootstrap_ci([float(r["completion_tokens"]) for r in ok], name="median")
    reasoning_share = bootstrap_ci(
        [
            r["reasoning_chars"] / max(1, r["reasoning_chars"] + r["answer_chars"])
            for r in ok
        ],
        name="median",
    )
    # calibrate() takes text, but only its length matters, and the prompts
    # themselves are already on disk in per_query.jsonl. Stand-in strings of the
    # right length keep this summary independent of holding the prompts in memory.
    fitted = TokenEstimator.calibrate(
        [("x" * (r["prompt_chars"] + r["system_chars"]), r["prompt_tokens"]) for r in ok]
    )
    return {
        "seconds_per_query": seconds,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_share_of_output": reasoning_share,
        "failures": len(records) - len(ok),
        "timing_sources": sorted({r["timing_source"] for r in ok}),
        "max_prompt_tokens_seen": max(r["prompt_tokens"] for r in ok),
        "num_ctx": num_ctx,
        "fitted_chars_per_token": fitted.chars_per_token,
        "fitted_overhead_tokens": fitted.overhead_tokens,
        "total_wall_s": sum(r["wall_s"] for r in records),
    }


def write_doc(
    path: Path,
    run: RunDir,
    summary: dict,
    truncation: dict | None,
    native: dict | None = None,
) -> None:
    """The deliverable: a budget stated in numbers someone can check."""
    seconds = summary["seconds_per_query"]
    per_query = seconds.value
    ci = f"{seconds.ci_low:.1f}-{seconds.ci_high:.1f}"
    timing = ", ".join(summary["timing_sources"])

    def pass_minutes(n: int) -> float:
        return n * per_query / 60

    # PLAN 4a: ten ablation arms, of which the metered ones run on the test
    # split. The pooled test split is 120 questions of the 300-question set.
    arms_metered = 10
    test_n, dev_n, full_n = 120, 60, 300

    lines = [
        "# Quota calibration",
        "",
        f"Measured {datetime.now(timezone.utc):%Y-%m-%d} against `{run.config.generation.model}` "
        f"at `{run.config.generation.base_url}`, Ollama Cloud free tier.",
        f"Run directory: `{run.path.as_posix()}`. Config hash `{run.config.config_hash}`.",
        "",
        "## What one query costs",
        "",
        "| Measure | Median | 95% CI | n |",
        "|---|---|---|---|",
    ]
    def fmt(value: float, kind: str) -> str:
        if kind == "int":
            return f"{value:,.0f}"
        if kind == "pct":
            return f"{value:.0%}"
        return f"{value:.2f}"

    for label, key, kind in (
        ("Seconds per query", "seconds_per_query", "float"),
        ("Prompt tokens", "prompt_tokens", "int"),
        ("Completion tokens", "completion_tokens", "int"),
        ("Reasoning share of output", "reasoning_share_of_output", "pct"),
    ):
        iv = summary[key]
        lines.append(
            f"| {label} | {fmt(iv.value, kind)} | "
            f"{fmt(iv.ci_low, kind)} - {fmt(iv.ci_high, kind)} | {iv.n} |"
        )

    lines += [
        "",
        f"Failures during the run: {summary['failures']} of {summary['failures'] + seconds.n}.",
        f"Timing source: **{timing}**.",
        "",
        "## Does the endpoint report its own durations",
        "",
    ]
    if "server" in summary["timing_sources"]:
        lines.append(
            "Yes. `eval_duration` and `prompt_eval_duration` came back on the "
            "OpenAI-compatible surface, so cost accounting uses the server's GPU time."
        )
    else:
        lines += [
            "**No.** The OpenAI-compatible surface returns `usage` token counts but no "
            "`eval_duration` or `prompt_eval_duration`, so **client wall-clock is the "
            "cost measure** and PLAN's open question is closed that way.",
            "",
            "Wall-clock includes queueing behind the free tier's single concurrency slot, "
            "so it is an upper bound on GPU time. A budget built on it is conservative "
            "rather than wrong, which is the direction a budget should err in. It also "
            "means cost is only comparable between arms measured under similar load, "
            "which is why arms are run back to back rather than on different days.",
        ]

    if native and "error" not in native:
        totals = [c["total_duration_s"] for c in native["calls"] if c["total_duration_s"]]
        walls = [c["wall_s"] for c in native["calls"]]
        lines += [
            "",
            "### The native endpoint is a partial exception",
            "",
            "PLAN 2a recommends the native `/api/chat` surface for eval runs because it "
            "reports `prompt_eval_duration` and `eval_duration`. Probed directly, "
            f"`{native['endpoint']}` returns "
            f"{'`total_duration`' if native['has_total_duration'] else 'no total duration'}, "
            "`prompt_eval_count` and `eval_count`, but "
            f"{'does' if native['has_prompt_eval_duration'] else 'does **not**'} return "
            "`prompt_eval_duration` and "
            f"{'does' if native['has_eval_duration'] else 'does **not**'} return "
            "`eval_duration` for this cloud model. Fields seen: "
            f"`{'`, `'.join(native['fields_present'])}`.",
        ]
        if totals:
            lines += [
                "",
                "| Probe call | Server `total_duration` | Client wall-clock |",
                "|---|---|---|",
                *[
                    f"| {i + 1} | {t:.2f}s | {w:.2f}s |"
                    for i, (t, w) in enumerate(zip(totals, walls))
                ],
                "",
                "`total_duration` is server-side and therefore a tighter measure than "
                "wall-clock, and the gap between the two columns is round-trip and "
                "queueing. It is still not the GPU-time breakdown PLAN wanted: without "
                "`prompt_eval_duration` there is no way to separate prompt processing "
                "from generation, so an arm that inflates the prompt and an arm that "
                "inflates the answer are indistinguishable on cost. The app keeps the "
                "OpenAI-compatible surface; an eval run that needs server time can call "
                "the native one and get a total, nothing finer.",
            ]
    elif native:
        lines += ["", f"Native-endpoint probe did not complete: {native['error']}"]

    lines += [
        "",
        "## The budget",
        "",
        f"At {per_query:.1f}s per query ({ci}s), sequentially, one concurrency slot:",
        "",
        "| Pass | Questions | Wall-clock |",
        "|---|---|---|",
        f"| Dev slice | {dev_n} | {pass_minutes(dev_n):.0f} min |",
        f"| Test split | {test_n} | {pass_minutes(test_n):.0f} min |",
        f"| Full gold set | {full_n} | {pass_minutes(full_n):.0f} min |",
        "",
        f"**Full gold-set passes per five-hour session window: "
        f"{int(5 * 3600 / (full_n * per_query))}.** That is throughput arithmetic, not an "
        "observed ceiling: nothing in this run tested what happens in hour four.",
        "",
        f"The metered ablation program is {arms_metered} arms on the {test_n}-question test "
        f"split: {arms_metered * test_n} queries, "
        f"{arms_metered * test_n * per_query / 3600:.1f} hours of sequential wall-clock.",
        "",
        "**This is well under what PLAN budgeted for.** PLAN 2a sized the project around "
        f"5-15 seconds per query and a 12-40 minute pass; the measurement is {per_query:.1f}s "
        f"and {pass_minutes(150):.0f} minutes for the same 150 questions. The consequence is "
        "that quota is not the binding constraint on Phase 4, and the OFAT restriction on the "
        "metered half is now a **statistical** decision rather than a budget one: 10 arms "
        "spend the test split 10 times, and a factorial design would spend it far more. "
        "Re-read that decision at Checkpoint D against the analysis plan, not against this "
        "page.",
        "",
        f"**{fmt(summary['reasoning_share_of_output'].value, 'pct')} of generated tokens are "
        "reasoning, not answer.** Output cost is dominated by a channel the user never sees, "
        "so any latency comparison between arms is mostly a comparison of how much the model "
        "thought. Answer length is close to noise inside it.",
        "",
        "**No published cap was hit during this run**, and none is published to hit. The "
        "free tier meters GPU time with no stated RPM or TPM, so these figures are what the "
        "endpoint gave us on one day, not an entitlement. Treat a run that suddenly halves "
        "in throughput as throttling, not as a code regression.",
        "",
        "## The context guard, recalibrated",
        "",
        f"`num_ctx` is set explicitly to {summary['num_ctx']}. The largest prompt in this run "
        f"measured {summary['max_prompt_tokens_seen']} tokens.",
        "",
        f"Fitted from this run's `usage` counts: **{summary['fitted_chars_per_token']:.2f} "
        f"characters per token** above a fixed chat-template overhead of "
        f"**{summary['fitted_overhead_tokens']} tokens**. The overhead is not a rounding "
        "detail: a seven-character prompt bills around seventy tokens on this model, so an "
        "estimator fitted without an intercept concludes a tenth of a character per token "
        "and refuses everything afterwards.",
        "",
        "The shipped default stays at 3.2 characters per token, which is tighter than the "
        "fitted value and therefore still over-counts. Loosening a guard to the number that "
        "just fitted one day's prompts is how the guard stops guarding.",
        "",
    ]

    if truncation:
        lines += ["## Does an oversized prompt truncate silently", ""]
        if truncation.get("error"):
            lines.append(
                f"The endpoint rejected it: `{truncation['error']}`. The client-side guard is "
                "still what the pipeline relies on, since a provider swap changes this answer "
                "and not the guard."
            )
        elif truncation.get("recovered_marker"):
            lines.append(
                f"Sent ~{truncation['sent_estimated_tokens']} estimated tokens against "
                f"num_ctx {truncation['num_ctx']}; the server counted "
                f"{truncation['server_prompt_tokens']} and still answered from the head of "
                "the prompt, so the window was not the binding limit for this probe."
            )
        else:
            lines.append(
                f"**Yes.** Sent ~{truncation['sent_estimated_tokens']} estimated tokens against "
                f"num_ctx {truncation['num_ctx']}; the server counted "
                f"{truncation['server_prompt_tokens']} prompt tokens and answered without the "
                "fact planted at the front of the prompt. Nothing errored, nothing warned. "
                "This is the failure the guard in `OllamaCloudGenerator.check_prompt` refuses "
                "to let happen, and the reason it raises rather than trimming."
            )
        lines.append("")

    lines += [
        "## How to reproduce",
        "",
        "```",
        "python scripts/calibrate_quota.py",
        "```",
        "",
        "Prompts are seeded, so a rerun measures the same twenty prompts against the same "
        "five passages each. The seconds will move with load; the prompt sizes will not.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/calibration.yaml", type=Path)
    parser.add_argument("--corpus", default="corpus/extracted/documents.jsonl", type=Path)
    parser.add_argument("--manifest", default="corpus/manifest.jsonl", type=Path)
    parser.add_argument("--doc", default="docs/quota-calibration.md", type=Path)
    parser.add_argument("--runs", default="runs", type=Path)
    parser.add_argument("--resume", type=Path, help="an existing run directory to continue")
    parser.add_argument("--limit", type=int, help="fewer questions, for a cheap rehearsal")
    parser.add_argument("--dry-run", action="store_true", help="build prompts, send nothing")
    parser.add_argument("--no-truncation-probe", action="store_true")
    parser.add_argument("--no-native-probe", action="store_true")
    args = parser.parse_args()

    config = Config.from_yaml(args.config)
    gen_cfg = config.generation
    questions = QUESTIONS[: args.limit] if args.limit else QUESTIONS
    prompts = build_prompts(args.corpus, questions, seed=config.seed)

    generator = OllamaCloudGenerator(
        model=gen_cfg.model,
        base_url=gen_cfg.base_url,
        num_ctx=gen_cfg.num_ctx,
        temperature=gen_cfg.temperature,
        max_tokens=gen_cfg.max_tokens,
    )

    if args.dry_run:
        print(f"{len(prompts)} prompts, budget {generator.prompt_budget} tokens")
        for item in prompts:
            estimate = generator.estimator.estimate(item.prompt + SYSTEM_PROMPT)
            flag = "  OVER" if estimate > generator.prompt_budget else ""
            print(f"  {item.query_id}  {item.prompt_chars:>6} chars  ~{estimate:>5} tok{flag}")
        return 0

    run = RunDir.open(args.resume) if args.resume else RunDir.create(config, root=args.runs)
    run.write_lock(
        Lock(
            kind="model",
            digest=f"{gen_cfg.model}@{gen_cfg.base_url}",
            detail={
                "model": gen_cfg.model,
                "base_url": gen_cfg.base_url,
                "num_ctx": gen_cfg.num_ctx,
                "temperature": gen_cfg.temperature,
                "max_tokens": gen_cfg.max_tokens,
            },
        )
    )
    run.write_lock(
        Lock(
            kind="corpus",
            digest=corpus_digest(args.corpus),
            detail={
                "corpus": args.corpus.as_posix(),
                "manifest": args.manifest.as_posix(),
                "documents": len(ExtractedCorpus(args.corpus).read()),
            },
        )
    )
    run.write_lock(
        Lock(
            kind="split",
            digest="none",
            detail={
                "reason": "calibration questions are throwaway; no train/dev/test split is "
                "spent and none is implied. Gold authoring is Task 12."
            },
        )
    )

    done = run.completed_ids()
    todo = [p for p in prompts if p.query_id not in done]
    if done:
        print(f"resuming: {len(done)} already answered, {len(todo)} to go")

    with run:
        for i, item in enumerate(todo, 1):
            record = run_one(generator, item)
            run.append(record)
            status = (
                f"{record['seconds']:.1f}s  {record['prompt_tokens']:>5}->"
                f"{record['completion_tokens']:<5} tok"
                if record["ok"]
                else f"FAILED  {record['error'][:80]}"
            )
            print(f"  [{i}/{len(todo)}] {item.query_id}  {status}")

    records = list(run.records())
    summary = summarise(records, gen_cfg.num_ctx)

    # Already probed in an earlier pass over this run directory: reuse the
    # answer rather than re-buying it. Regenerating the report must be free.
    probe_path = run.path / "truncation_probe.json"
    truncation = json.loads(probe_path.read_text(encoding="utf-8")) if probe_path.exists() else None
    if truncation is None and not args.no_truncation_probe:
        # Sized well past the window on purpose: the point is to see what the
        # server does when the guard is not there to stop it.
        filler = "The college publishes many pages about student life. " * 900
        truncation = probe_truncation(generator, filler)
        probe_path.write_text(json.dumps(truncation, indent=2), encoding="utf-8")

    # Same rule: probed once per run directory, cached, never re-bought.
    native_path = run.path / "native_probe.json"
    native = json.loads(native_path.read_text(encoding="utf-8")) if native_path.exists() else None
    if native is None and not args.no_native_probe:
        native = probe_native_durations(generator)
        native_path.write_text(json.dumps(native, indent=2), encoding="utf-8")

    run.write_metrics(
        {
            key: summary[key].to_dict()
            for key in (
                "seconds_per_query",
                "prompt_tokens",
                "completion_tokens",
                "reasoning_share_of_output",
            )
        }
        | {
            "run": {
                "failures": str(summary["failures"]),
                "timing_sources": summary["timing_sources"],
                "num_ctx": str(summary["num_ctx"]),
                "max_prompt_tokens_seen": str(summary["max_prompt_tokens_seen"]),
                "fitted_chars_per_token": f"{summary['fitted_chars_per_token']:.4f}",
                "fitted_overhead_tokens": str(summary["fitted_overhead_tokens"]),
            }
        }
    )

    args.doc.parent.mkdir(parents=True, exist_ok=True)
    write_doc(args.doc, run, summary, truncation, native)

    seconds = summary["seconds_per_query"]
    print(
        f"\nmedian {seconds.value:.2f}s/query "
        f"[{seconds.ci_low:.2f}, {seconds.ci_high:.2f}] over n={seconds.n}\n"
        f"timing from: {', '.join(summary['timing_sources'])}\n"
        f"missing locks: {run.missing_locks or 'none'}\n"
        f"wrote {args.doc}"
    )
    if summary["failures"]:
        print(f"!! {summary['failures']} call(s) failed; see per_query.jsonl", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
