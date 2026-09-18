"""Task 17: resumable, cached ablation sweep runner.

Turns a list of `Config` objects into one `RunDir` each, executing them in
turn against a shared, on-disk generation cache. Two mechanisms below are
what the whole of Phase 4 leans on:

**Resume is arm-aware, not just question-aware.** A run dir is looked up by
its config's own hash, not by timestamp -- so re-invoking a sweep after a
kill finds the same directory for the same arm and continues from
`completed_ids()`, instead of starting a fresh, empty run next to a
half-finished one.

**The generation cache is shared across the whole sweep, not scoped to one
run dir.** Two arms that happen to send the identical prompt (same retrieved
passages, same question, same decoding config) pay for the generation once.
That is what makes this task's verification step -- kill mid-sweep, resume,
confirm no duplicate generations -- true across arms, not just within one.

Nothing here knows what a "question" evaluates to. Callers supply
`evaluate_fn`, the same shape `mcrag.eval.retrieval_harness.evaluate_question`
already has. T17 depends only on T1 (config/run-dir) and T14 (the harness
shape); T18 and later tasks supply the config matrices and per-question logic.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from mcrag.config import Config
from mcrag.runlog import RunDir
from mcrag.types import GoldQuestion

EvaluateFn = Callable[[GoldQuestion], dict[str, Any]]
SummarizeFn = Callable[[list[dict[str, Any]]], dict[str, Any]]


def find_or_create_run_dir(config: Config, root: str | Path = "runs") -> RunDir:
    """Locate an existing run dir for this exact config, or start one.

    `RunDir.create` names directories `<timestamp>_<config_hash>`; calling it
    twice for the same config makes two directories, since the timestamp
    differs -- which would silently orphan a killed run's progress instead of
    resuming it. Resuming a sweep means finding the run directory whose
    suffix already matches this config's hash, not making a new one.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    suffix = f"_{config.config_hash}"
    existing = sorted(p for p in root.glob(f"*{suffix}") if p.is_dir())
    if existing:
        return RunDir.open(existing[-1])
    return RunDir.create(config, root=root)


class GenerationCache:
    """A generation cache shared across an entire ablation sweep.

    Keyed on `(model, digest, prompt_hash)` per this task's acceptance
    criteria: `model` and `digest` together pin everything that can change a
    reply for the same prompt text -- decoding params, base URL, embedder
    version, whatever the caller folds into `digest` -- and the prompt hash
    pins the text itself. An identical rerun -- the same arm resumed after a
    kill, or two arms whose retrieval happened to produce the same passages
    for a question -- is a cache hit and costs no quota.

    Backed by an append-only JSONL file with the same fsync-per-record
    discipline as `RunDir.append`, for the same reason: an entry that was
    already paid for must survive a crash.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._entries: dict[str, dict[str, Any]] = {}
        self._handle = None
        if self.path.exists():
            with self.path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._entries[record["key"]] = record

    @staticmethod
    def make_key(model: str, digest: str, prompt: str) -> str:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:24]
        return f"{model}|{digest}|{prompt_hash}"

    def get(self, model: str, digest: str, prompt: str) -> dict[str, Any] | None:
        record = self._entries.get(self.make_key(model, digest, prompt))
        return record["result"] if record is not None else None

    def put(self, model: str, digest: str, prompt: str, result: dict[str, Any]) -> None:
        key = self.make_key(model, digest, prompt)
        if key in self._entries:
            return  # already paid for; never overwrite or double-append
        record = {"key": key, "model": model, "digest": digest, "result": result}
        self._entries[key] = record
        if self._handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8", buffering=1)
        self._handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> GenerationCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __len__(self) -> int:
        return len(self._entries)


class SweepPaused(RuntimeError):
    """Raised when a quota wall stops a sweep cleanly, mid-arm.

    The run dir underneath is never corrupt when this is raised: every
    record that reached `evaluate_fn` successfully was already appended and
    fsynced (`RunDir.append`) before the exception could propagate. The arm
    and question it stopped at are carried so a caller can report exactly
    where, and a second call with the same config/questions resumes there.
    """

    def __init__(self, arm: str, qid: str, cause: Exception) -> None:
        super().__init__(f"sweep paused in arm {arm!r} at question {qid!r}: {cause}")
        self.arm = arm
        self.qid = qid
        self.cause = cause


def run_arm(
    config: Config,
    questions: Iterable[GoldQuestion],
    evaluate_fn: EvaluateFn,
    summarize_fn: SummarizeFn,
    *,
    root: str | Path = "runs",
    quota_errors: tuple[type[Exception], ...] = (),
) -> RunDir:
    """Run one config to completion (or to a quota wall), resuming from disk.

    `quota_errors` names the exception types that mean "the metered backend
    stopped serving us", not "this question is broken". Anything else
    propagates immediately, uncaught -- a bug in `evaluate_fn` must not be
    silently treated as a clean pause.
    """
    run_dir = find_or_create_run_dir(config, root=root)
    done = run_dir.completed_ids()
    todo = [q for q in questions if q.qid not in done]

    with run_dir:
        for question in todo:
            try:
                record = evaluate_fn(question)
            except quota_errors as exc:
                raise SweepPaused(config.arm, question.qid, exc) from exc
            run_dir.append(record)

    records = list(run_dir.records())
    metrics = summarize_fn(records)
    run_dir.write_metrics(metrics)
    return run_dir


def build_work_queue(
    configs: list[Config], questions: list[GoldQuestion]
) -> list[tuple[Config, GoldQuestion]]:
    """Question-major order: every config's turn on q1, then every config's
    turn on q2, and so on -- so no two consecutive items share a config
    (Task 22's own verification step), and any drift in the metered backend
    lands on all arms roughly equally instead of confounding one arm's
    wall-clock position against another's (PLAN Sec 4, "interleave by
    question, never by config").
    """
    return [(config, question) for question in questions for config in configs]


def run_interleaved(
    configs: list[Config],
    questions: Iterable[GoldQuestion],
    evaluate_fn_for: Callable[[Config], EvaluateFn],
    summarize_fn: SummarizeFn,
    *,
    expected_model: str | dict[str, str],
    root: str | Path = "runs",
    quota_errors: tuple[type[Exception], ...] = (),
) -> dict[str, RunDir]:
    """Task 22: run every config's turn on one question before any config's
    turn on the next, resuming per (config, question) pair.

    **Model drift, checked per record, not pre-flight.** Nothing in the
    metered API exposes "which model is live" without actually generating,
    so drift can only be caught after the fact: `evaluate_fn`'s returned
    record is expected to carry the model string the provider actually
    answered with (`OllamaCloudGenerator`'s `Completion.model` already
    provides this). A record whose `model` doesn't match its arm's expected
    model is quarantined -- kept on disk, `quarantined: True`, excluded from
    `summarize_fn`'s aggregates by the caller -- rather than voiding the arm
    or the sweep. A record with no `model` field (a config with no
    generation call in it, e.g. a retrieval-only arm) is never quarantined.

    `expected_model` is a single string when every arm is pinned to the same
    model (a prompt or gate ablation, say), or `{arm: model}` when arms
    deliberately use *different* models (Task 22's #10) -- a single global
    string there would wrongly flag every non-default arm as drifted. In
    dict form, every config's `arm` must have an entry.

    Requires at least two configs: interleaving one arm against itself is
    meaningless, and `build_work_queue`'s no-two-consecutive-share-a-config
    guarantee needs a second config to hold against.
    """
    configs = list(configs)
    if len(configs) < 2:
        raise ValueError("interleaving needs at least two configs")
    if isinstance(expected_model, dict):
        missing = [c.arm for c in configs if c.arm not in expected_model]
        if missing:
            raise ValueError(f"expected_model dict is missing arm(s): {missing}")

    run_dirs = {c.arm: find_or_create_run_dir(c, root=root) for c in configs}
    evaluators = {c.arm: evaluate_fn_for(c) for c in configs}

    for config, question in build_work_queue(configs, list(questions)):
        run_dir = run_dirs[config.arm]
        if question.qid in run_dir.completed_ids():
            continue
        try:
            record = evaluators[config.arm](question)
        except quota_errors as exc:
            raise SweepPaused(config.arm, question.qid, exc) from exc
        expected = expected_model[config.arm] if isinstance(expected_model, dict) else expected_model
        model_seen = record.get("model")
        if model_seen is not None and model_seen != expected:
            record = {
                **record,
                "quarantined": True,
                "quarantine_reason": f"model drift: expected {expected!r}, saw {model_seen!r}",
            }
        run_dir.append(record)

    results: dict[str, RunDir] = {}
    for config in configs:
        run_dir = run_dirs[config.arm]
        records = list(run_dir.records())
        metrics = summarize_fn(records)
        run_dir.write_metrics(metrics)
        results[config.arm] = run_dir
    return results


def unquarantined(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Records `run_interleaved` did not flag for model drift. `summarize_fn`
    callers should aggregate over this, not the raw record list -- a
    quarantined record is kept on disk for audit, never for a metric."""
    return [r for r in records if not r.get("quarantined")]


def run_matrix(
    configs: Iterable[Config],
    questions: Iterable[GoldQuestion],
    evaluate_fn_for: Callable[[Config], EvaluateFn],
    summarize_fn: SummarizeFn,
    *,
    root: str | Path = "runs",
    quota_errors: tuple[type[Exception], ...] = (),
) -> dict[str, RunDir]:
    """Run every config in `configs`, one variable at a time, one run dir each.

    Stops at the first `SweepPaused`: the arms before it are complete and on
    disk with their own metrics; the arm that hit the wall is exactly as
    resumable as a single `run_arm` call would leave it; arms after it in the
    matrix simply never started. Re-invoking `run_matrix` with the same
    `configs` picks up exactly there, because `find_or_create_run_dir` maps
    each config back to its own directory rather than making a new one.
    """
    questions = list(questions)
    results: dict[str, RunDir] = {}
    for config in configs:
        run_dir = run_arm(
            config,
            questions,
            evaluate_fn_for(config),
            summarize_fn,
            root=root,
            quota_errors=quota_errors,
        )
        results[config.arm] = run_dir
    return results
