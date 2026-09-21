"""The calibration set must be reproducible, slice-stratified, and blind."""

from __future__ import annotations

import pytest

from mcrag.eval.calibration_set import (
    read_human_labels,
    render_scoring_sheet,
    sample_calibration_items,
    write_calibration_files,
)

SLICES = {"single_silo": 8, "cross_silo": 6, "adversarial": 2, "multi_turn": 1}


def _records(model: str) -> list[dict]:
    recs = []
    for s, count in SLICES.items():
        for i in range(count):
            recs.append({"slice": s, "query_id": f"{s}-{i}", "question": f"q {s} {i}",
                         "answer": f"answer {s} {i}", "retrieved": [{"chunk_id": "c1"}]})
    return recs


CHUNKS = {"c1": {"source_url": "https://x.edu/a", "title": "A", "text": "passage text"}}
POOL = {"gemma": _records("gemma"), "gptoss": _records("gptoss")}


def test_same_seed_gives_the_same_items():
    a = sample_calibration_items(POOL, CHUNKS, n=12, seed=7)
    b = sample_calibration_items(POOL, CHUNKS, n=12, seed=7)
    assert [(i.model, i.query_id) for i in a] == [(i.model, i.query_id) for i in b]


def test_every_slice_is_represented_even_the_rare_ones():
    items = sample_calibration_items(POOL, CHUNKS, n=12, seed=1)
    assert {i.slice for i in items} == set(SLICES)
    assert len(items) == 12


def test_asking_for_more_than_the_pool_raises():
    with pytest.raises(ValueError):
        sample_calibration_items(POOL, CHUNKS, n=999, seed=1)


def test_sheet_is_blind_no_model_name_anywhere():
    items = sample_calibration_items(POOL, CHUNKS, n=12, seed=1)
    sheet = render_scoring_sheet(items)
    assert not any(model in sheet for model in POOL)
    assert "passage text" in sheet


def test_blank_or_invalid_scores_are_rejected(tmp_path):
    items = sample_calibration_items(POOL, CHUNKS, n=12, seed=1)
    write_calibration_files(items, tmp_path)
    with pytest.raises(ValueError):
        read_human_labels(tmp_path / "labels.csv")  # freshly written template is all-blank


def test_filled_labels_round_trip(tmp_path):
    items = sample_calibration_items(POOL, CHUNKS, n=12, seed=1)
    write_calibration_files(items, tmp_path)
    (tmp_path / "labels.csv").write_text(
        "item_id,score\n" + "\n".join(f"{i.item_id},2" for i in items), encoding="utf-8")
    labels = read_human_labels(tmp_path / "labels.csv")
    assert len(labels) == 12 and set(labels.values()) == {2}
