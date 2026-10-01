"""Task 36: evaluate the re-run trigger, and re-run if it fired.

    python scripts/run_rerun_trigger.py

Exit codes, each a distinct event for whatever runs this on a schedule:

- 0  the published numbers still stand; nothing was re-run
- 1  the trigger itself failed, or the re-run it started failed
- 2  a measured condition fired and the re-run was executed
- 3  a condition could not be established; nothing was re-run, a human must look

3 is the code that exists because of `decisions/0020` and `decisions/0021`: an
unmeasurable condition is not a passing one. It does not fire, because firing
spends generation quota and quota is spent on measured effects -- but it does
not read as silence either.

Every run appends one row to `data/maintenance/trigger_log.jsonl` before
returning, including the failure rows.

The re-run executor is injected (`rerun_fn`), the same seam
`mcrag.maintain.run.main` uses for its ingest chain, so the decision logic is
testable without a generator. See `_default_rerun_fn` for what production must
supply.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcrag.config import Config  # noqa: E402
from mcrag.maintain.frozen import frozen_config  # noqa: E402
from mcrag.maintain.trigger import (  # noqa: E402
    TriggerDecision,
    append_trigger_log,
    compute_trigger_decision,
)

PUBLISHED_LOCK_PATH = Path("data/maintenance/published_corpus.lock")
LIVE_LOCK_PATH = Path("indexes/corpus.lock")
MAINTENANCE_LOG_PATH = Path("data/maintenance/maintenance_log.jsonl")
TRIGGER_LOG_PATH = Path("data/maintenance/trigger_log.jsonl")


def _default_rerun_fn(config: Config) -> None:
    """Refuse, loudly, because no executor is wired yet.

    A re-run means running the full metered eval: a sentence-transformer, the
    three live indexes, and `gemma4:31b` behind a keyed endpoint. None of that
    can be exercised from a test, so writing it here would put unverified code
    on the one path that spends quota.

    It raises instead of doing nothing. A no-op default would make a fired
    trigger print "re-running" and exit 2 having re-run nothing, which is the
    exact failure `decisions/0021` was written about -- a feature that reports
    success because the thing that would have failed never ran. Raising sends
    the run to exit 1 with a logged reason, so a scheduled trigger that fires
    before an executor exists is a visible failure rather than a quiet lie.

    Production supplies the executor by passing `rerun_fn`; it should call
    `mcrag.eval.ablation_runner.run_arm(config, questions, evaluate_fn,
    summarize_fn)` and write the run directory's corpus Lock from the live
    `indexes/corpus.lock` snapshot hash so the new RESULTS.md row is
    attributable to the snapshot it was measured on.
    """
    raise NotImplementedError(
        f"The trigger fired for arm {config.arm!r}, but no re-run executor is wired. "
        "Task 36 ships the trigger decision and the result versioning; the metered "
        "re-run itself needs a live index and a keyed generator, so it is passed in "
        "as rerun_fn. Nothing was re-run and RESULTS.md is unchanged."
    )


def main(rerun_fn: Callable[[Config], None] | None = None) -> int:
    """Evaluate the trigger; re-run the frozen config if it fired.

    Returns the exit code rather than raising it, so the code itself is
    testable -- `decisions/0021` records what happened last time two of these
    were asserted without ever being produced.
    """
    if rerun_fn is None:
        rerun_fn = _default_rerun_fn

    evaluated_at = datetime.now(timezone.utc)
    decision: TriggerDecision | None = None

    try:
        decision = compute_trigger_decision(
            published_lock_path=PUBLISHED_LOCK_PATH,
            live_lock_path=LIVE_LOCK_PATH,
            maintenance_log_path=MAINTENANCE_LOG_PATH,
        )

        if decision.change_ratio is not None:
            print(f"Corpus change ratio: {decision.change_ratio:.1%}")
        if decision.alerts_open is not None:
            print(f"T34 alert open: {decision.alerts_open}")
        for sentence in decision.undetermined:
            print(f"  undetermined: {sentence}")
        for sentence in decision.reasons:
            print(f"  fired: {sentence}")

        if decision.fires:
            # Both lists print: an open alert fires while a missing published
            # lock stays undetermined, and the reader needs to see both.
            print("\nTrigger fired. Re-running the frozen Checkpoint-E config.")
            rerun_fn(frozen_config())
            exit_code = 2
        elif decision.undetermined:
            print("\nA trigger condition could not be established. Nothing re-run.")
            exit_code = 3
        else:
            print("\nThe published numbers still stand. Nothing re-run.")
            exit_code = 0

    except Exception as exc:
        traceback.print_exc()
        exit_code = 1
        # The row is the only diagnosis a scheduled failure leaves behind, so
        # it carries the exception text and whatever the decision had already
        # established before things broke.
        failure = f"The trigger run failed: {type(exc).__name__}: {exc}"
        if decision is None:
            decision = TriggerDecision(fires=False, undetermined=(failure,))
        else:
            decision = TriggerDecision(
                fires=decision.fires,
                undetermined=decision.undetermined + (failure,),
                reasons=decision.reasons,
                change_ratio=decision.change_ratio,
                changed_urls=decision.changed_urls,
                alerts_open=decision.alerts_open,
                published_snapshot_hash=decision.published_snapshot_hash,
                live_snapshot_hash=decision.live_snapshot_hash,
                detail=decision.detail,
            )

    append_trigger_log(TRIGGER_LOG_PATH, evaluated_at, exit_code, decision)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
