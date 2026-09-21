"""Task 22b prerequisite: the human-scored calibration set a Tier 3 judge must
be checked against before its scores may be reported (PLAN Sec 4d,
`mcrag.eval.judge_calibration`).

Two decisions here are deliberate and easy to undo by accident:

- **Dev answers only.** The set is drawn from answers already generated on the
  dev split, so building and hand-scoring it never touches test (decisions/0006).
- **The human scores blind.** PLAN Sec 4d's "pipeline proposes, human accepts"
  workflow is right for *production* labelling and wrong here: a rater shown the
  judge's proposed 0/1/2 anchors on it, and kappa then measures how easily the
  human is talked into the judge's answer rather than whether they agree. So the
  sheet carries no judge score, no NLI score, and no model name -- the model
  behind each item lives only in the key file.
"""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CalibrationItem:
    item_id: str
    model: str
    query_id: str
    slice: str
    question: str
    answer: str
    passages: tuple[dict, ...] = field(default_factory=tuple)  # {url, title, text}


def _allocate(pool_sizes: Mapping[str, int], n: int) -> dict[str, int]:
    """Proportional allocation across slices by largest remainder, at least one
    item per non-empty slice so the rare slices (multi_turn, adversarial) are
    represented at all, never more than a slice holds."""
    total = sum(pool_sizes.values())
    if n > total:
        raise ValueError(f"asked for {n} items but the pool only holds {total}")
    if n < len(pool_sizes):
        raise ValueError(f"n={n} cannot cover {len(pool_sizes)} slices at one item each")
    alloc = {s: 1 for s in pool_sizes}
    remaining = n - len(pool_sizes)
    quotas = {s: (pool_sizes[s] - 1) / max(total - len(pool_sizes), 1) * remaining for s in pool_sizes}
    for s, q in quotas.items():
        alloc[s] += int(q)
    leftover = n - sum(alloc.values())
    by_remainder = sorted(quotas, key=lambda s: quotas[s] - int(quotas[s]), reverse=True)
    for s in by_remainder:
        if leftover == 0:
            break
        if alloc[s] < pool_sizes[s]:
            alloc[s] += 1
            leftover -= 1
    return alloc


def sample_calibration_items(
    records_by_model: Mapping[str, Sequence[dict]],
    chunks: Mapping[str, dict],
    n: int,
    seed: int,
) -> list[CalibrationItem]:
    """Seeded, slice-stratified sample over every model's answers.

    Item order is shuffled and ids are assigned after the shuffle, so neither
    the item number nor its neighbours reveal slice or model to the rater.
    """
    rng = random.Random(seed)
    pool: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for model in sorted(records_by_model):
        for rec in records_by_model[model]:
            pool[rec["slice"]].append((model, rec))

    alloc = _allocate({s: len(v) for s, v in pool.items()}, n)
    picked: list[tuple[str, dict]] = []
    for s in sorted(pool):
        members = sorted(pool[s], key=lambda mr: (mr[1]["query_id"], mr[0]))
        rng.shuffle(members)
        picked.extend(members[: alloc[s]])
    rng.shuffle(picked)

    items = []
    for i, (model, rec) in enumerate(picked, start=1):
        passages = tuple(
            {"url": chunks[h["chunk_id"]]["source_url"], "title": chunks[h["chunk_id"]]["title"],
             "text": chunks[h["chunk_id"]]["text"]}
            for h in rec["retrieved"]
        )
        items.append(
            CalibrationItem(
                item_id=f"cal-{i:03d}", model=model, query_id=rec["query_id"], slice=rec["slice"],
                question=rec["question"], answer=rec["answer"], passages=passages,
            )
        )
    return items


RUBRIC = """\
Score each answer 0, 1 or 2, judging it against the passages shown -- not
against what you happen to know about the college.

- **2** correct and grounded in the passages. A correct refusal (the passages
  really don't answer it, or the question rests on a false premise and the
  answer says so) is a 2.
- **1** substantially correct but flawed: partial, or a minor grounding slip.
- **0** wrong or hallucinated: a claim the passages don't support, or a
  refusal when the passages did contain the answer.
"""


def render_scoring_sheet(items: Sequence[CalibrationItem]) -> str:
    parts = ["# Judge calibration set -- score blind\n", RUBRIC,
             "Write your scores in `labels.csv` (item_id, score). Nothing on this sheet "
             "shows a model name or a machine score, on purpose.\n"]
    for it in items:
        parts.append(f"\n---\n\n## {it.item_id}\n\n**Question:** {it.question}\n\n**Answer:**\n\n> "
                     + it.answer.replace("\n", "\n> ") + "\n\n<details><summary><b>Passages the system was given</b></summary>\n")
        for j, p in enumerate(it.passages, start=1):
            parts.append(f"\n[{j}] *{p['title']}* -- {p['url']}\n\n{p['text']}\n")
        parts.append("\n</details>\n")
    return "\n".join(parts)


def write_calibration_files(items: Sequence[CalibrationItem], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scoring_sheet.md").write_text(render_scoring_sheet(items), encoding="utf-8")
    with (out_dir / "labels.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["item_id", "score"])
        writer.writerows([[it.item_id, ""] for it in items])
    key = [{"item_id": it.item_id, "model": it.model, "query_id": it.query_id, "slice": it.slice}
           for it in items]
    (out_dir / "key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    (out_dir / "items.json").write_text(
        json.dumps([asdict(it) for it in items], indent=2),
        encoding="utf-8",
    )


def read_human_labels(path: Path) -> dict[str, int]:
    """Blank or non-0/1/2 cells raise: a half-filled sheet must not silently
    become a smaller calibration set."""
    labels: dict[str, int] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = (row["score"] or "").strip()
            if raw not in {"0", "1", "2"}:
                raise ValueError(f"{row['item_id']}: score must be 0, 1 or 2, got {raw!r}")
            labels[row["item_id"]] = int(raw)
    return labels
