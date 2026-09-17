"""The silo-boost query-time factor (PLAN §Phase 4 ablation #7): **soft**
boost, never a hard filter -- "a hard silo filter is precisely how cross-silo
queries, the thesis of this project, break."

No component upstream of retrieval classifies a query's silo (that would be
a new, separate piece of infrastructure -- a query-side silo classifier --
and PLAN never asks for one here). Instead this reranker uses the candidate
list's own consensus: whichever silo already shows up most often among the
fused candidates is treated as the query's likely silo, and hits carrying
that label get a small score bump. This never needs an external classifier,
degrades gracefully on a genuinely cross-silo question (no single silo
dominates, so the boost is small or a wash), and stays strictly additive --
nothing is ever removed from the list, only reordered.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from mcrag.interfaces import Reranker
from mcrag.types import Hit


class SiloBoostReranker(Reranker):
    """Boosts hits sharing the candidate list's most common silo label.

    `boost` is a fraction added to a hit's score (`score * (1 + boost)`) when
    its chunk's silo matches the modal silo among the *whole* candidate list
    passed in (not just the top-k). `boost=0.0` is the 'off' arm and is an
    exact no-op -- order and scores are untouched, which is what lets the
    ablation matrix express "off" as this class with a zero rather than as a
    separate `IdentityReranker` special case.
    """

    def __init__(self, boost: float = 0.0) -> None:
        if boost < 0:
            raise ValueError("boost must be non-negative -- this is a soft boost, not a penalty")
        self.boost = boost

    def rerank(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        if self.boost == 0.0:
            return list(hits[:k])

        labeled = [h for h in hits if h.chunk is not None and h.chunk.silo]
        if not labeled:
            return list(hits[:k])

        silo_counts: Counter[str] = Counter(s for h in labeled for s in h.chunk.silo)
        modal_silo, _ = silo_counts.most_common(1)[0]

        boosted = [
            replace(h, score=h.score * (1 + self.boost))
            if h.chunk is not None and modal_silo in h.chunk.silo
            else h
            for h in hits
        ]
        boosted.sort(key=lambda h: -h.score)
        return [replace(h, rank=rank) for rank, h in enumerate(boosted)][:k]
