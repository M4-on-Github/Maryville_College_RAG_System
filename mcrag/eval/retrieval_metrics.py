"""Task 14: pure retrieval metrics. No I/O, no model calls -- set arithmetic
over a gold ref list and a ranked retrieved-id list (PLAN Sec 2b).

Every function takes ``gold: Sequence[str]`` and ``retrieved: Sequence[str]``
(already ranked, best first) plus ``k``. None of them know about `Hit`,
`GoldQuestion`, or a retriever -- that wiring lives in `retrieval_harness.py`,
kept separate so these are trivial to hand-verify (T14's own verification
step: hand-compute 3 questions and match this module's output exactly).
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(gold: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    """Fraction of gold refs found anywhere in the top-k retrieved ids.

    Gives partial credit for a conjunctive question (found 1 of 2 golds ->
    0.5) -- which is exactly why `all_golds_retrieved_at_k` exists alongside
    this, not instead of it: partial credit on a conjunctive claim is a wrong
    answer scored as half right.
    """
    if not gold:
        raise ValueError("recall_at_k is undefined for a question with no gold refs")
    top_k = set(retrieved[:k])
    hits = sum(1 for g in gold if g in top_k)
    return hits / len(gold)


def mrr(gold: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    """Reciprocal rank (within the top k) of the first gold ref found. 0 if none."""
    gold_set = set(gold)
    for rank, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in gold_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(gold: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    """Binary-relevance nDCG@k: relevant means "is a gold ref", nothing graded."""
    if not gold:
        raise ValueError("ndcg_at_k is undefined for a question with no gold refs")
    gold_set = set(gold)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved[:k], start=1)
        if chunk_id in gold_set
    )
    ideal_hits = min(len(gold_set), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def all_golds_retrieved_at_k(gold: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    """1.0 iff every gold ref is in the top-k, else 0.0 -- no partial credit.

    The metric a conjunctive question must be scored on (PLAN Phase 3b): a
    cross-silo question needs chunks from finaid AND ISS, and finding only one
    of them is a wrong answer, not a half-right one.
    """
    if not gold:
        raise ValueError("all_golds_retrieved_at_k is undefined for a question with no gold refs")
    top_k = set(retrieved[:k])
    return 1.0 if set(gold) <= top_k else 0.0
