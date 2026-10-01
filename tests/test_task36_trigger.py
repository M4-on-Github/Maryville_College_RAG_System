"""Task 36: Verification of the trigger mechanism and re-run execution.

The trigger fires when >10% of corpus URLs have changed, or when any T34 alert
is open. A fired trigger re-runs the frozen Checkpoint-E config. Both the
trigger decision logic and the result-table versioning are tested.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcrag.maintain.frozen import frozen_config
from mcrag.maintain.trigger import (
    TriggerDecision,
    append_trigger_log,
    compute_trigger_decision,
)
import scripts.run_rerun_trigger as trigger_module
from scripts.run_rerun_trigger import _default_rerun_fn


# ============================================================================
# Helper function
# ============================================================================


def write_lock(path: Path, urls: dict[str, str]):
    """Write a corpus.lock file with the given URLs."""
    canonical = json.dumps(dict(sorted(urls.items())), sort_keys=True)
    snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    path.write_text(json.dumps({"snapshot_hash": snapshot_hash, "urls": urls}), encoding="utf-8")


# ============================================================================
# Acceptance Criterion 1: 12% corpus change fires the trigger
# ============================================================================


def test_trigger_fires_on_12_percent_change(tmp_path: Path):
    """A 12% corpus change fires the trigger."""
    published_urls = {f"https://example.com/{i:03d}": f"hash_{i}" for i in range(100)}
    live_urls = {f"https://example.com/{i:03d}": f"hash_{i}" for i in range(100)}
    for i in range(12):
        live_urls[f"https://example.com/{i:03d}"] = f"hash_changed_{i}"

    published_lock = tmp_path / "published.lock"
    live_lock = tmp_path / "live.lock"

    write_lock(published_lock, published_urls)
    write_lock(live_lock, live_urls)

    decision = compute_trigger_decision(
        published_lock_path=published_lock,
        live_lock_path=live_lock,
        maintenance_log_path=tmp_path / "maintenance_log.jsonl",
    )

    assert decision.fires is True
    assert decision.change_ratio == 0.12
    assert "12.0%" in decision.reasons[0] or "12%" in decision.reasons[0]


def test_trigger_fires_at_threshold_strictly_greater(tmp_path: Path):
    """The threshold is strictly greater than 10%, so 10% exactly does not fire."""
    published_urls = {f"https://example.com/{i:03d}": f"hash_{i}" for i in range(100)}
    live_urls = {f"https://example.com/{i:03d}": f"hash_{i}" for i in range(100)}
    for i in range(10):
        live_urls[f"https://example.com/{i:03d}"] = f"hash_changed_{i}"

    published_lock = tmp_path / "published.lock"
    live_lock = tmp_path / "live.lock"

    write_lock(published_lock, published_urls)
    write_lock(live_lock, live_urls)

    decision = compute_trigger_decision(
        published_lock_path=published_lock,
        live_lock_path=live_lock,
        maintenance_log_path=tmp_path / "maintenance_log.jsonl",
    )

    assert decision.fires is False
    assert decision.change_ratio == 0.10


def test_trigger_does_not_fire_on_9_percent_change(tmp_path: Path):
    """9% change does not fire the trigger."""
    published_urls = {f"https://example.com/{i:03d}": f"hash_{i}" for i in range(100)}
    live_urls = {f"https://example.com/{i:03d}": f"hash_{i}" for i in range(100)}
    for i in range(9):
        live_urls[f"https://example.com/{i:03d}"] = f"hash_changed_{i}"

    published_lock = tmp_path / "published.lock"
    live_lock = tmp_path / "live.lock"

    write_lock(published_lock, published_urls)
    write_lock(live_lock, live_urls)

    decision = compute_trigger_decision(
        published_lock_path=published_lock,
        live_lock_path=live_lock,
        maintenance_log_path=tmp_path / "maintenance_log.jsonl",
    )

    assert decision.fires is False
    assert decision.change_ratio == 0.09


# ============================================================================
# Acceptance Criterion 2: Open T34 alert makes the trigger fire
# ============================================================================


def test_trigger_fires_on_open_alert(tmp_path: Path):
    """An open T34 alert (exit_code 2) makes the trigger fire."""
    log_path = tmp_path / "maintenance_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "run_id": "test-run",
        "started_at": "2026-10-01T00:00:00+00:00",
        "finished_at": "2026-10-01T00:01:00+00:00",
        "exit_code": 2,
        "pages_fetched": 10,
        "alerts": [
            {"name": "extraction_regression", "fired": False},
            {"name": "corpus_shape_drift", "fired": False},
            {"name": "volume_anomaly", "fired": True},
            {"name": "stale_gold", "fired": False},
        ],
        "error": None,
    }

    log_path.write_text(json.dumps(log_entry) + "\n", encoding="utf-8")

    published_lock = tmp_path / "published.lock"
    live_lock = tmp_path / "live.lock"
    published_lock.write_text(json.dumps({"snapshot_hash": "aaa", "urls": {}}), encoding="utf-8")
    live_lock.write_text(json.dumps({"snapshot_hash": "bbb", "urls": {}}), encoding="utf-8")

    decision = compute_trigger_decision(
        published_lock_path=published_lock,
        live_lock_path=live_lock,
        maintenance_log_path=log_path,
    )

    assert decision.fires is True
    assert decision.alerts_open is True


# ============================================================================
# Acceptance Criterion 3: Exit-1 last maintenance row yields None and undetermined
# ============================================================================


def test_undetermined_on_exit_1_log_row(tmp_path: Path):
    """An exit-1 last maintenance row sets alerts_open=None and adds undetermined."""
    log_path = tmp_path / "maintenance_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "run_id": "test-run",
        "started_at": "2026-10-01T00:00:00+00:00",
        "finished_at": "2026-10-01T00:01:00+00:00",
        "exit_code": 1,
        "pages_fetched": None,
        "alerts": [],
        "error": "Chain failed during fetch",
    }

    log_path.write_text(json.dumps(log_entry) + "\n", encoding="utf-8")

    published_lock = tmp_path / "published.lock"
    live_lock = tmp_path / "live.lock"
    published_lock.write_text(json.dumps({"snapshot_hash": "aaa", "urls": {}}), encoding="utf-8")
    live_lock.write_text(json.dumps({"snapshot_hash": "bbb", "urls": {}}), encoding="utf-8")

    decision = compute_trigger_decision(
        published_lock_path=published_lock,
        live_lock_path=live_lock,
        maintenance_log_path=log_path,
    )

    assert decision.fires is False
    assert decision.alerts_open is None
    # Not just "unknown": the row has to say the chain died, because that is a
    # different thing to fix than an unreadable row, and the sentence in the
    # log is the only diagnosis the reader gets.
    assert any("ingest chain failed" in s for s in decision.undetermined)
    assert any("never ran" in s for s in decision.undetermined)


# ============================================================================
# Acceptance Criterion 4: Missing published lock yields None and undetermined
# ============================================================================


def test_undetermined_on_missing_published_lock(tmp_path: Path):
    """A missing published lock sets change_ratio=None and adds undetermined."""
    published_lock = tmp_path / "published.lock"
    live_lock = tmp_path / "live.lock"

    live_lock.write_text(json.dumps({"snapshot_hash": "aaa", "urls": {"https://example.com": "hash"}}), encoding="utf-8")

    decision = compute_trigger_decision(
        published_lock_path=published_lock,
        live_lock_path=live_lock,
        maintenance_log_path=tmp_path / "maintenance_log.jsonl",
    )

    assert decision.fires is False
    assert decision.change_ratio is None
    assert len(decision.undetermined) > 0


# ============================================================================
# Acceptance Criterion 5: Fired trigger re-runs with frozen config
# ============================================================================


def test_a_fired_trigger_reruns_the_frozen_config_and_nothing_else(tmp_path, monkeypatch):
    """The injected executor is handed exactly one config, equal to frozen_config().

    The point of the criterion is that maintenance re-measures instead of
    re-tuning, so what matters is the config the executor actually receives --
    not that `frozen_config()` has the right fields, which is a different
    claim and was all this test used to check.
    """
    monkeypatch.chdir(tmp_path)
    _repo(tmp_path, published=_urls(100), live=_urls(100, changed=12), maintenance_row=_clean_row())

    received = []
    exit_code = trigger_module.main(rerun_fn=received.append)

    assert exit_code == 2
    assert len(received) == 1
    assert received[0] == frozen_config()
    # Maintenance never re-spends the test split.
    assert received[0].eval.split == "dev"


def test_the_default_rerun_executor_refuses_rather_than_reporting_success(tmp_path, monkeypatch):
    """With no executor wired, a fired trigger fails loudly instead of exiting 2.

    A no-op default would print "re-running" and exit 2 having re-run nothing.
    That is the `decisions/0021` failure exactly: the step that would have
    failed never ran, so the run reported success.
    """
    monkeypatch.chdir(tmp_path)
    _repo(tmp_path, published=_urls(100), live=_urls(100, changed=12), maintenance_row=_clean_row())

    with pytest.raises(NotImplementedError, match="no re-run executor is wired"):
        _default_rerun_fn(frozen_config())

    # And through main: the failure becomes exit 1, not a silent exit 2.
    assert trigger_module.main() == 1
    row = _trigger_rows(tmp_path)[-1]
    assert row["exit_code"] == 1
    assert any("NotImplementedError" in s for s in row["decision"]["undetermined"])


# ============================================================================
# Acceptance Criterion 6: Test split restrictions
# ============================================================================


def test_frozen_config_rejects_test_split_without_license(tmp_path: Path, monkeypatch):
    """frozen_config(split="test") without license_test_split raises ValueError."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="may not spend the test split"):
        frozen_config(split="test")


def test_frozen_config_accepts_test_split_with_license(tmp_path: Path, monkeypatch):
    """frozen_config(split="test", license_test_split="reason") succeeds and logs."""
    monkeypatch.chdir(tmp_path)

    config = frozen_config(split="test", license_test_split="reverification after corpus change")

    # Verify the config was built
    assert config.eval.split == "test"

    # Verify notes.md was written
    notes_path = tmp_path / "notes.md"
    assert notes_path.exists()
    content = notes_path.read_text(encoding="utf-8")
    assert "test-split access" in content
    assert "reverification" in content

    # Write again with a different reason and verify both entries are there
    config2 = frozen_config(split="test", license_test_split="another reason")
    content2 = notes_path.read_text(encoding="utf-8")
    assert "another reason" in content2
    assert "reverification" in content2


# ============================================================================
# Acceptance Criterion 7: Result versioning and regeneration
# ============================================================================


def test_corpus_column_in_results_table(tmp_path: Path):
    """The corpus column appears in regenerated RESULTS.md with corpus digest."""
    run_dir = tmp_path / "runs" / "20260915T120000Z_abcd1234"
    run_dir.mkdir(parents=True)

    (run_dir / "config.yaml").write_text("name: test\neval:\n  split: dev\n", encoding="utf-8")
    (run_dir / "metrics.json").write_text(
        json.dumps({
            "run": {"n_scored": 10, "n_stale": 0},
            "recall@k": {"value": 0.8, "ci_low": 0.7, "ci_high": 0.9, "n": 10},
            "mrr": {"value": 0.9, "ci_low": 0.8, "ci_high": 1.0, "n": 10},
            "ndcg@k": {"value": 0.85, "ci_low": 0.75, "ci_high": 0.95, "n": 10},
            "all_golds_retrieved@k": {"value": 0.8, "ci_low": 0.7, "ci_high": 0.9, "n": 10},
            "faithfulness": {"value": 0.75, "ci_low": 0.65, "ci_high": 0.85, "n": 10},
        }),
        encoding="utf-8",
    )

    (run_dir / "corpus.lock").write_text(
        json.dumps({
            "kind": "corpus",
            "digest": "e67d77fe16bafd93",
            "detail": {"corpus": "corpus/extracted/documents.jsonl", "documents": 46},
        }),
        encoding="utf-8",
    )

    from mcrag.eval.results_table import collect_runs, render_markdown

    runs = collect_runs(tmp_path / "runs")
    assert len(runs) == 1

    markdown = render_markdown(runs)
    # Verify the corpus digest is in the output (not just "?" or empty)
    assert "e67d77fe16bafd93" in markdown, f"Digest not found in markdown:\n{markdown}"
    # Verify the header contains "corpus"
    lines = markdown.split("\n")
    header_line = lines[6]
    assert "corpus" in header_line.lower(), f"'corpus' not in header:\n{header_line}"


def test_results_regeneration_is_idempotent(tmp_path: Path):
    """Regenerating the results table twice produces identical output."""
    run_dir = tmp_path / "runs" / "20260915T120000Z_abcd1234"
    run_dir.mkdir(parents=True)

    (run_dir / "config.yaml").write_text("name: test\neval:\n  split: dev\n", encoding="utf-8")
    (run_dir / "metrics.json").write_text(
        json.dumps({
            "run": {"n_scored": 10, "n_stale": 0},
            "recall@k": {"value": 0.8, "ci_low": 0.7, "ci_high": 0.9, "n": 10},
            "mrr": {"value": 0.9, "ci_low": 0.8, "ci_high": 1.0, "n": 10},
            "ndcg@k": {"value": 0.85, "ci_low": 0.75, "ci_high": 0.95, "n": 10},
            "all_golds_retrieved@k": {"value": 0.8, "ci_low": 0.7, "ci_high": 0.9, "n": 10},
            "faithfulness": {"value": 0.75, "ci_low": 0.65, "ci_high": 0.85, "n": 10},
        }),
        encoding="utf-8",
    )

    (run_dir / "corpus.lock").write_text(
        json.dumps({
            "kind": "corpus",
            "digest": "e67d77fe16bafd93",
            "detail": {"corpus": "corpus/extracted/documents.jsonl", "documents": 46},
        }),
        encoding="utf-8",
    )

    from mcrag.eval.results_table import write_results_md

    out_path = tmp_path / "RESULTS.md"
    first = write_results_md(runs_root=tmp_path / "runs", out_path=out_path)
    second = write_results_md(runs_root=tmp_path / "runs", out_path=out_path)

    assert first == second


# ============================================================================
# Acceptance Criterion 8: Exit codes
# ============================================================================


def test_exit_code_0_on_no_trigger(tmp_path: Path, monkeypatch):
    """Exit code 0 when published numbers still stand."""
    monkeypatch.chdir(tmp_path)

    (tmp_path / "data" / "maintenance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    urls = {f"https://example.com/{i:03d}": f"hash_{i}" for i in range(100)}
    write_lock(tmp_path / "data" / "maintenance" / "published_corpus.lock", urls)
    write_lock(tmp_path / "indexes" / "corpus.lock", urls)

    # Create a maintenance log with no alerts
    log_path = tmp_path / "data" / "maintenance" / "maintenance_log.jsonl"
    log_entry = {
        "run_id": "test-run",
        "started_at": "2026-10-01T00:00:00+00:00",
        "finished_at": "2026-10-01T00:01:00+00:00",
        "exit_code": 0,
        "pages_fetched": 10,
        "alerts": [
            {"name": "extraction_regression", "fired": False},
            {"name": "corpus_shape_drift", "fired": False},
            {"name": "volume_anomaly", "fired": False},
            {"name": "stale_gold", "fired": False},
        ],
        "error": None,
    }
    log_path.write_text(json.dumps(log_entry) + "\n", encoding="utf-8")

    exit_code = trigger_module.main()

    assert exit_code == 0


def test_exit_code_2_when_trigger_fires(tmp_path: Path, monkeypatch):
    """Exit 2 on a measured corpus change, with the executor injected."""
    monkeypatch.chdir(tmp_path)
    _repo(tmp_path, published=_urls(100), live=_urls(100, changed=12), maintenance_row=_clean_row())

    assert trigger_module.main(rerun_fn=lambda config: None) == 2


def test_exit_code_1_when_the_rerun_executor_raises(tmp_path: Path, monkeypatch):
    """Exit 1 when the re-run itself fails, with the reason in the log row.

    The row is the only diagnosis a 3 a.m. scheduled failure leaves behind:
    the traceback dies with the process.
    """
    monkeypatch.chdir(tmp_path)
    _repo(tmp_path, published=_urls(100), live=_urls(100, changed=12), maintenance_row=_clean_row())

    def boom(config):
        raise RuntimeError("ollama endpoint refused the connection")

    assert trigger_module.main(rerun_fn=boom) == 1

    row = _trigger_rows(tmp_path)[-1]
    assert row["exit_code"] == 1
    assert any("ollama endpoint refused" in s for s in row["decision"]["undetermined"])
    # What it had already established survives into the failure row.
    assert row["decision"]["change_ratio"] == 0.12


def test_exit_code_3_when_undetermined(tmp_path: Path, monkeypatch):
    """Exit code 3 when something could not be determined."""
    monkeypatch.chdir(tmp_path)

    (tmp_path / "data" / "maintenance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    exit_code = trigger_module.main()

    assert exit_code == 3


# ============================================================================
# Acceptance Criterion 9: Trigger log is append-only
# ============================================================================


def test_trigger_log_is_append_only(tmp_path: Path):
    """Multiple trigger evaluations produce multiple rows in order."""
    log_path = tmp_path / "trigger_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    decision1 = TriggerDecision(fires=False, reasons=())
    append_trigger_log(
        log_path,
        datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc),
        0,
        decision1,
    )

    decision2 = TriggerDecision(fires=True, reasons=("Test change",))
    append_trigger_log(
        log_path,
        datetime(2026, 10, 1, 11, 0, 0, tzinfo=timezone.utc),
        2,
        decision2,
    )

    decision3 = TriggerDecision(fires=False, undetermined=("Missing lock",))
    append_trigger_log(
        log_path,
        datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc),
        3,
        decision3,
    )

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3

    row1 = json.loads(lines[0])
    assert row1["exit_code"] == 0

    row2 = json.loads(lines[1])
    assert row2["exit_code"] == 2

    row3 = json.loads(lines[2])
    assert row3["exit_code"] == 3


# ============================================================================
# Frozen config matches task 22b config
# ============================================================================


def test_frozen_config_matches_t22b_config():
    """The frozen config matches build_configs() from run_t22b_test_confirmatory.py."""
    from scripts.run_t22b_test_confirmatory import build_configs

    frozen = frozen_config()
    t22b_configs = build_configs()

    primary = None
    for cfg in t22b_configs:
        if cfg.arm == "t22b_frozen_gemma4_31b":
            primary = cfg
            break

    assert primary is not None

    assert frozen.chunk.max_tokens == primary.chunk.max_tokens == 512
    assert frozen.retrieval.k == primary.retrieval.k == 5
    assert frozen.retrieval.candidate_k == primary.retrieval.candidate_k == 20
    assert frozen.generation.model == primary.generation.model == "gemma4:31b"
    assert frozen.generation.temperature == primary.generation.temperature == 0.0
    assert frozen.eval.gold_path == primary.eval.gold_path


# ============================================================================
# Helpers for the end-to-end paths, and the fixes reviewed in decisions/0022
# ============================================================================


def _urls(n: int, *, changed: int = 0, added: int = 0, removed: int = 0) -> dict[str, str]:
    """`n` pages, of which the first `changed` carry a different hash."""
    urls = {f"https://example.com/{i:03d}": f"hash_{i}" for i in range(n)}
    for i in range(changed):
        urls[f"https://example.com/{i:03d}"] = f"hash_changed_{i}"
    for i in range(removed):
        del urls[f"https://example.com/{n - 1 - i:03d}"]
    for i in range(added):
        urls[f"https://example.com/new_{i:03d}"] = f"hash_new_{i}"
    return urls


def _clean_row(**overrides) -> dict:
    """A T34 log row for a run where all four checks ran and none fired."""
    row = {
        "run_id": "20261001T000000Z",
        "started_at": "2026-10-01T00:00:00+00:00",
        "finished_at": "2026-10-01T00:01:00+00:00",
        "exit_code": 0,
        "pages_fetched": 100,
        "alerts": [
            {"name": "extraction_regression", "fired": False},
            {"name": "corpus_shape_drift", "fired": False},
            {"name": "volume_anomaly", "fired": False},
            {"name": "stale_gold", "fired": False},
        ],
        "error": None,
    }
    row.update(overrides)
    return row


def _repo(tmp_path: Path, *, published=None, live=None, maintenance_row=None) -> None:
    """Lay out the paths `main` reads, at the cwd it reads them from."""
    (tmp_path / "data" / "maintenance").mkdir(parents=True, exist_ok=True)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)
    if published is not None:
        write_lock(tmp_path / "data" / "maintenance" / "published_corpus.lock", published)
    if live is not None:
        write_lock(tmp_path / "indexes" / "corpus.lock", live)
    if maintenance_row is not None:
        (tmp_path / "data" / "maintenance" / "maintenance_log.jsonl").write_text(
            json.dumps(maintenance_row) + "\n", encoding="utf-8"
        )


def _trigger_rows(tmp_path: Path) -> list[dict]:
    path = tmp_path / "data" / "maintenance" / "trigger_log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_changed_count_is_the_true_count_not_the_capped_sample(tmp_path: Path):
    """`changed_urls` is a capped sample; `detail` must carry the real count.

    Reporting `len(changed_urls)` would under-report at exactly 50 -- that is,
    it would under-report precisely when the news is worst.
    """
    published = _urls(200)
    live = _urls(200, changed=60)
    write_lock(tmp_path / "published.lock", published)
    write_lock(tmp_path / "live.lock", live)

    decision = compute_trigger_decision(
        published_lock_path=tmp_path / "published.lock",
        live_lock_path=tmp_path / "live.lock",
        maintenance_log_path=tmp_path / "missing.jsonl",
    )

    assert decision.detail["changed_count"] == 60
    assert decision.detail["modified_count"] == 60
    assert len(decision.changed_urls) == 50
    assert decision.change_ratio == 0.30


def test_added_and_removed_pages_count_as_changed(tmp_path: Path):
    """New content changes retrieval, so additions are in the numerator too."""
    write_lock(tmp_path / "published.lock", _urls(100))
    write_lock(tmp_path / "live.lock", _urls(100, changed=4, added=5, removed=3))

    decision = compute_trigger_decision(
        published_lock_path=tmp_path / "published.lock",
        live_lock_path=tmp_path / "live.lock",
        maintenance_log_path=tmp_path / "missing.jsonl",
    )

    assert decision.detail["modified_count"] == 4
    assert decision.detail["added_count"] == 5
    assert decision.detail["removed_count"] == 3
    assert decision.detail["changed_count"] == 12
    # Denominator is the published count, not the live one.
    assert decision.detail["published_url_count"] == 100
    assert decision.change_ratio == 0.12
    assert decision.fires is True


def test_url_counts_are_unknown_not_zero_when_a_lock_is_missing(tmp_path: Path):
    """A lock nobody could read has an unknown url count, not an empty one."""
    write_lock(tmp_path / "live.lock", _urls(40))

    decision = compute_trigger_decision(
        published_lock_path=tmp_path / "absent.lock",
        live_lock_path=tmp_path / "live.lock",
        maintenance_log_path=tmp_path / "missing.jsonl",
    )

    assert decision.detail["published_url_count"] is None
    assert decision.detail["changed_count"] is None
    assert decision.detail["published_url_count"] != 0
    assert decision.detail["changed_count"] != 0
    assert decision.live_snapshot_hash is not None
    assert decision.published_snapshot_hash is None


def test_an_unreadable_lock_is_reported_as_unreadable_not_as_empty(tmp_path: Path):
    """Corrupt and absent are different sentences; the log row is all a reader gets."""
    (tmp_path / "published.lock").write_text("{not json", encoding="utf-8")
    write_lock(tmp_path / "live.lock", _urls(10))

    decision = compute_trigger_decision(
        published_lock_path=tmp_path / "published.lock",
        live_lock_path=tmp_path / "live.lock",
        maintenance_log_path=tmp_path / "missing.jsonl",
    )

    assert decision.change_ratio is None
    assert decision.fires is False
    assert any("could not be read" in s for s in decision.undetermined)
    assert not any("does not exist" in s for s in decision.undetermined)


def test_an_exit_2_row_listing_no_fired_alert_is_not_read_as_silence(tmp_path: Path):
    """T34 exits 2 only when something fired; a row disagreeing with itself is unknown."""
    log_path = tmp_path / "maintenance_log.jsonl"
    log_path.write_text(json.dumps(_clean_row(exit_code=2)) + "\n", encoding="utf-8")
    write_lock(tmp_path / "published.lock", _urls(10))
    write_lock(tmp_path / "live.lock", _urls(10))

    decision = compute_trigger_decision(
        published_lock_path=tmp_path / "published.lock",
        live_lock_path=tmp_path / "live.lock",
        maintenance_log_path=log_path,
    )

    assert decision.alerts_open is None
    assert decision.alerts_open is not False
    assert any("disagrees with itself" in s for s in decision.undetermined)


def test_a_maintenance_row_with_no_exit_code_leaves_alert_status_unknown(tmp_path: Path):
    """An unrecognised row does not establish that four checks ran and passed."""
    log_path = tmp_path / "maintenance_log.jsonl"
    row = _clean_row()
    del row["exit_code"]
    log_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    write_lock(tmp_path / "published.lock", _urls(10))
    write_lock(tmp_path / "live.lock", _urls(10))

    decision = compute_trigger_decision(
        published_lock_path=tmp_path / "published.lock",
        live_lock_path=tmp_path / "live.lock",
        maintenance_log_path=log_path,
    )

    assert decision.alerts_open is None
    assert decision.fires is False


def test_a_fired_alert_and_an_unmeasurable_ratio_both_reach_the_reader(tmp_path: Path, monkeypatch):
    """Firing must not hide that the other condition could not be measured."""
    monkeypatch.chdir(tmp_path)
    _repo(tmp_path, live=_urls(10), maintenance_row=_clean_row(
        exit_code=2,
        alerts=[{"name": "stale_gold", "fired": True}],
    ))

    assert trigger_module.main(rerun_fn=lambda config: None) == 2

    row = _trigger_rows(tmp_path)[-1]
    assert row["decision"]["reasons"]
    assert row["decision"]["undetermined"]
    assert row["decision"]["change_ratio"] is None


def test_a_blank_license_does_not_unlock_the_test_split(tmp_path: Path, monkeypatch):
    """An empty reason is not a justification, and must not write an empty log row."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="may not spend the test split"):
        frozen_config(split="test", license_test_split="")
    with pytest.raises(ValueError, match="may not spend the test split"):
        frozen_config(split="test", license_test_split="   ")

    assert not (tmp_path / "notes.md").exists()


def test_the_access_log_records_the_real_split_lock_hash(tmp_path: Path, monkeypatch):
    """The hash is read from the lock, the way the test-split run reads it.

    `load_split_lock` returns a plain dict, so an attribute access on it
    raises -- and a swallowed raise wrote "hash: None" on every row.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "gold").mkdir(parents=True)
    (tmp_path / "data" / "gold" / "split.lock").write_text(
        json.dumps({"seed": 7, "split_hash": "feedfacecafe1234", "assignment": {}}),
        encoding="utf-8",
    )

    frozen_config(split="test", license_test_split="corpus moved 12%, human licensed a re-measure")

    content = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert "feedfacecafe1234" in content
    assert "unresolved" not in content
    assert "hash: None" not in content


def test_an_unreadable_split_lock_says_so_instead_of_logging_none(tmp_path: Path, monkeypatch):
    """No split.lock is still a logged access -- named as unresolved, not as None."""
    monkeypatch.chdir(tmp_path)

    frozen_config(split="test", license_test_split="licensed re-measure")

    content = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert "unresolved" in content
    assert "hash: None" not in content


def test_the_access_log_is_appended_never_rewritten(tmp_path: Path, monkeypatch):
    """An existing notes.md keeps everything already in it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").write_text("# Test-split access log\n\nearlier entry here\n", encoding="utf-8")

    frozen_config(split="test", license_test_split="first licensed re-measure")
    frozen_config(split="test", license_test_split="second licensed re-measure")

    content = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert "earlier entry here" in content
    assert "first licensed re-measure" in content
    assert "second licensed re-measure" in content
    assert content.count("-- test-split access") == 2


def test_a_naive_timestamp_is_refused_by_the_trigger_log(tmp_path: Path):
    """A naive datetime renders without an offset and would misdate the row."""
    log_path = tmp_path / "nested" / "trigger_log.jsonl"

    with pytest.raises(ValueError, match="timezone-aware"):
        append_trigger_log(log_path, datetime(2026, 10, 1, 12, 0, 0), 0, TriggerDecision(fires=False))

    # Refused before the mkdir: a rejected call leaves nothing behind.
    assert not log_path.parent.exists()


def test_the_default_executor_names_what_production_must_supply():
    """The refusal has to tell a reader what is missing, not just fail."""
    with pytest.raises(NotImplementedError) as exc:
        _default_rerun_fn(frozen_config())

    message = str(exc.value)
    assert "rerun_fn" in message
    assert "RESULTS.md is unchanged" in message


def test_a_run_without_a_corpus_lock_renders_a_question_mark(tmp_path: Path):
    """An unattributable row shows `?`, never a blank or a dash.

    Every run directory in the repo happens to carry a corpus.lock, so this
    branch has no production row exercising it -- which is exactly why it
    needs a test. A blank cell reads as "no corpus", and `--` is what the
    table already uses for "this run made no generation calls"; neither says
    "nobody recorded which snapshot this was measured on".
    """
    from mcrag.eval.results_table import collect_runs, render_markdown

    run_dir = tmp_path / "runs" / "20260915T120000Z_nolock00"
    run_dir.mkdir(parents=True)
    (run_dir / "config.yaml").write_text(
        "name: t\narm: no_lock_arm\neval:\n  split: dev\n", encoding="utf-8"
    )
    (run_dir / "metrics.json").write_text(
        json.dumps({"run": {"n_scored": 48, "n_stale": 0}}), encoding="utf-8"
    )

    runs = collect_runs(tmp_path / "runs")
    assert len(runs) == 1
    assert runs[0]["corpus_digest"] == "?"

    markdown = render_markdown(runs)
    row = [line for line in markdown.splitlines() if "no_lock_arm" in line][0]
    cells = [c.strip() for c in row.split("|")]
    assert cells[5] == "?", f"corpus cell was {cells[5]!r} in row: {row}"
    assert cells[5] != ""
    assert cells[5] != "--"


def _run_dir(root: Path, run_id: str, *, arm: str, digest: str | None) -> Path:
    """A minimal run directory the results table will load."""
    d = root / "runs" / run_id
    d.mkdir(parents=True)
    (d / "config.yaml").write_text(
        f"name: t\narm: {arm}\neval:\n  split: dev\n", encoding="utf-8"
    )
    (d / "metrics.json").write_text(
        json.dumps({"run": {"n_scored": 48, "n_stale": 0}}), encoding="utf-8"
    )
    if digest is not None:
        (d / "corpus.lock").write_text(
            json.dumps({"kind": "corpus", "digest": digest, "detail": {}}), encoding="utf-8"
        )
    return d


def test_an_old_row_and_a_maintenance_rerun_row_both_survive_regeneration(tmp_path: Path):
    """A re-run adds a row; it does not replace the one already published.

    This is the "old rows stay" half of the criterion. The table is
    regenerated wholesale from `runs/`, so survival is a property of both run
    directories still being there and each carrying its own corpus cell --
    a re-run against a moved corpus must not silently restate the old numbers
    as if they had been measured on the new one.
    """
    from mcrag.eval.results_table import collect_runs, render_markdown, write_results_md

    _run_dir(tmp_path, "20260916T220036Z_oldrow0001", arm="bp_off-fixed512", digest="aaaaaaaaaaaaaaaa1111")
    _run_dir(tmp_path, "20261001T090000Z_rerun00001", arm="maintenance_rerun", digest="bbbbbbbbbbbbbbbb2222")

    runs = collect_runs(tmp_path / "runs")
    assert len(runs) == 2

    markdown = render_markdown(runs)
    rows = {
        "bp_off-fixed512": None,
        "maintenance_rerun": None,
    }
    for line in markdown.splitlines():
        for arm in rows:
            if f"| {arm} |" in line:
                rows[arm] = [c.strip() for c in line.split("|")]

    assert rows["bp_off-fixed512"] is not None, f"old row gone:\n{markdown}"
    assert rows["maintenance_rerun"] is not None, f"re-run row missing:\n{markdown}"

    # Each row is attributable to its own snapshot, truncated to 16 chars.
    assert rows["bp_off-fixed512"][5] == "aaaaaaaaaaaaaaaa"
    assert rows["maintenance_rerun"][5] == "bbbbbbbbbbbbbbbb"
    assert rows["bp_off-fixed512"][5] != rows["maintenance_rerun"][5]

    # And the same holds through the real writer, twice over.
    out = tmp_path / "RESULTS.md"
    first = write_results_md(runs_root=tmp_path / "runs", out_path=out)
    second = write_results_md(runs_root=tmp_path / "runs", out_path=out)
    assert first == second
    written = out.read_text(encoding="utf-8")
    assert "bp_off-fixed512" in written
    assert "maintenance_rerun" in written
