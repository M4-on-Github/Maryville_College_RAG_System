"""Task 36: the frozen Checkpoint-E config a maintenance re-run reuses.

A maintenance re-run re-measures; it does not re-tune. Re-tuning is a decision
a human makes, so this module hands back one config and offers no knobs:
- retrieval frozen by `decisions/0007` (boilerplate off, `FixedSizeChunker(512)`,
  RRF fusion, k=5 over 20 candidates)
- generation model by `decisions/0010` (gemma4:31b at temperature 0)
- no query reformulation, by `decisions/0011`

`tests/test_task36_trigger.py` asserts this config field-for-field against
`build_configs()` in `scripts/run_t22b_test_confirmatory.py`, which is the run
that actually spent the test split. That test is the reason this file is safe
to keep: if the two ever drift, it fails here rather than silently publishing a
row measured under a different config than the one it claims.

The test split is not re-spent by maintenance. `split="test"` is refused unless
the caller passes a written reason, and that reason is logged to the standing
test-split access log before the config is handed back.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mcrag.config import Config
from mcrag.eval.gold import load_split_lock

K = 5
CANDIDATE_K = 20
GOLD_PATH = Path("data/gold/gold_v1.jsonl")
SPLIT_LOCK_PATH = Path("data/gold/split.lock")
NOTES_LOG_PATH = Path("notes.md")


def frozen_config(
    split: str = "dev",
    *,
    arm: str = "maintenance_rerun",
    license_test_split: str | None = None,
) -> Config:
    """The frozen Checkpoint-E config.

    Args:
        split: which split to re-measure on. Defaults to "dev"; the
            maintenance path never passes anything else.
        arm: the arm name recorded in the run directory.
        license_test_split: a written reason for spending the test split.
            Required to use `split="test"`, logged before the config is
            returned, and never passed by the maintenance re-run path.

    Raises:
        ValueError: on `split="test"` without a non-blank reason.
    """
    if split == "test":
        if license_test_split is None or not license_test_split.strip():
            # A blank reason is refused along with a missing one: an empty
            # string is not a justification, and accepting it would license
            # the test split while writing an access-log row that says
            # nothing about why.
            raise ValueError(
                "A maintenance re-run may not spend the test split. The test split is "
                "touched once, after Checkpoint E, and every access is logged; pass "
                "license_test_split with a written reason if a human has decided to "
                "spend it, or use split='dev'."
            )
        _log_test_split_access(license_test_split)

    return Config.from_dict(
        {
            "name": "maintenance-frozen-checkpoint-e",
            "arm": arm,
            "chunk": {"max_tokens": 512},
            "retrieval": {"k": K, "candidate_k": CANDIDATE_K},
            "generation": {"model": "gemma4:31b", "temperature": 0.0},
            "eval": {"gold_path": str(GOLD_PATH), "split": split},
            "notes": (
                "Frozen Checkpoint-E config, re-run by Task 36 maintenance: "
                "decisions/0007 retrieval (boilerplate off, FixedSizeChunker(512), "
                "RRF fusion), decisions/0010 generation model gemma4:31b, "
                "decisions/0011 no reformulation. Not a tuning round."
            ),
        }
    )


def _split_lock_hash() -> str:
    """The split.lock hash for the access log, or a sentence saying why not.

    Never returns a bare `None` into the log line. An access row whose hash
    reads `None` does not say whether the lock was unreadable or whether
    nobody looked, and the row is the whole accountability record.
    """
    try:
        return str(load_split_lock(SPLIT_LOCK_PATH)["split_hash"])
    except (OSError, KeyError, ValueError) as exc:
        return f"unresolved ({type(exc).__name__}: {exc})"


def _log_test_split_access(reason: str) -> None:
    """Append one test-split access row, in the format `_log_test_access` writes.

    Appended before the caller gets the config, because the standing rule is
    that an access which was not logged did not happen -- and a crash between
    being handed the config and sending the first question must not leave the
    access unrecorded.
    """
    entry = (
        f"\n## {datetime.now(timezone.utc).isoformat(timespec='seconds')} -- test-split access\n\n"
        f"Task 36 maintenance re-run (frozen Checkpoint-E config, decisions/0007 retrieval, "
        f"decisions/0011 no reformulation, decisions/0010 generation model gemma4:31b). "
        f"Licensed reason: {reason}. split.lock hash: {_split_lock_hash()}.\n"
    )
    if not NOTES_LOG_PATH.exists():
        NOTES_LOG_PATH.write_text(
            "# Test-split access log\n\nPer the standing rule, every access of the 120-question "
            "test split is logged here, at the moment the first question is actually sent to a "
            "generator, not before.\n" + entry,
            encoding="utf-8",
        )
    else:
        with NOTES_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(entry)
