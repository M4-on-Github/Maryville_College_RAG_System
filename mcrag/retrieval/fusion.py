"""Reciprocal rank fusion — the baseline fuser PLAN §4c names before rule-routed
weights or MoR: "RRF weights every retriever equally on every query."

Score by rank, not by raw score. Dense cosine similarity, BM25's unbounded
term-weight sum, and literal's integer hit count are not comparable numbers --
averaging them directly would let whichever leg happens to produce the largest
raw scores dominate fusion regardless of how good its ranking actually is.
RRF sidesteps that by only ever looking at each leg's own rank order.
"""

from __future__ import annotations

from mcrag.interfaces import Fuser
from mcrag.types import Hit


class RRFFuser(Fuser):
    """`score(chunk) = sum over legs of 1 / (k_constant + rank)`.

    `k_constant` (60 is the value from the original RRF paper and TREC
    practice) damps the contribution of low ranks so a chunk retrieved at
    rank 1 by one leg isn't trivially outweighed by a chunk at rank 2 by
    three legs -- without it, fusion degenerates into "how many legs found
    this at all," which is exactly the leg-count artifact RRF exists to avoid.
    """

    def __init__(self, k_constant: int = 60) -> None:
        if k_constant <= 0:
            raise ValueError("k_constant must be positive")
        self.k_constant = k_constant

    def fuse(self, leg_results: list[list[Hit]], k: int) -> list[Hit]:
        scores: dict[str, float] = {}
        legs_hit: dict[str, list[str]] = {}
        best_hit: dict[str, Hit] = {}
        for leg_hits in leg_results:
            for hit in leg_hits:
                contribution = 1.0 / (self.k_constant + hit.rank)
                scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + contribution
                legs_hit.setdefault(hit.chunk_id, []).append(hit.leg)
                # Keep whichever leg's Hit ranked this chunk_id highest, so a
                # fused Hit's `.chunk`/`.leg` still point at real provenance.
                if hit.chunk_id not in best_hit or hit.rank < best_hit[hit.chunk_id].rank:
                    best_hit[hit.chunk_id] = hit

        ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
        fused: list[Hit] = []
        for rank, (chunk_id, score) in enumerate(ranked[:k]):
            source = best_hit[chunk_id]
            fused.append(
                Hit(
                    chunk_id=chunk_id,
                    score=score,
                    leg="+".join(sorted(set(legs_hit[chunk_id]))),
                    rank=rank,
                    chunk=source.chunk,
                )
            )
        return fused
