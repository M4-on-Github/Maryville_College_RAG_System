"""Task 19, Tier 1: local NLI faithfulness (PLAN Sec 4d).

Faithfulness, not correctness: does the answer say things the retrieved
context actually supports, regardless of whether that context was the right
context to retrieve (that's Phase 3's retrieval metrics' job) or whether the
underlying fact is true (that's what a human or Tier 3 judge assesses).

Same tool class as `mcrag.retrieval.reranker.CrossEncoderReranker` -- a local
`sentence_transformers.CrossEncoder`, lazy-loaded, zero quota, offline once
cached -- because an NLI cross-encoder and a relevance cross-encoder are the
same architecture pointed at a different label space.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mcrag.interfaces import Scorer
from mcrag.types import Score

DEFAULT_NLI_MODEL = "cross-encoder/nli-deberta-v3-base"

# This model's label order (contradiction=0, entailment=1, neutral=2) is the
# sentence-transformers convention for its NLI cross-encoders -- verify
# against the model card again if `model_name` is ever changed.
DEFAULT_ENTAILMENT_INDEX = 1

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def split_sentences(text: str) -> list[str]:
    """A deliberately simple splitter: good enough to separate an LLM
    answer's claims for per-sentence entailment, not a general sentence
    tokenizer. Empty/whitespace-only fragments are dropped."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


@dataclass(frozen=True, slots=True)
class FaithfulnessResult:
    value: float | None  # None when there's nothing to score (no sentences or no context)
    n_sentences: int
    n_entailed: int
    per_sentence: tuple[bool, ...]


class NLIFaithfulnessScorer(Scorer):
    """`score()` implements `mcrag.interfaces.Scorer`; `score_answer()` below
    returns the richer `FaithfulnessResult` most callers actually want
    (per-sentence detail, and a `None` rather than a misleading 0.0 when the
    answer or the context is empty)."""

    tier = 1

    def __init__(self, model_name: str = DEFAULT_NLI_MODEL, entailment_index: int = DEFAULT_ENTAILMENT_INDEX) -> None:
        self.model_name = model_name
        self.entailment_index = entailment_index
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def score_answer(self, answer: str, context: list[str]) -> FaithfulnessResult:
        sentences = split_sentences(answer)
        premise = " ".join(context).strip()
        if not sentences or not premise:
            return FaithfulnessResult(value=None, n_sentences=len(sentences), n_entailed=0, per_sentence=())

        model = self._load()
        logits = model.predict([(premise, s) for s in sentences])
        per_sentence = tuple(int(row.argmax()) == self.entailment_index for row in logits)
        n_entailed = sum(per_sentence)
        return FaithfulnessResult(
            value=n_entailed / len(sentences),
            n_sentences=len(sentences),
            n_entailed=n_entailed,
            per_sentence=per_sentence,
        )

    def score(self, answer: str, gold: dict) -> Score:
        result = self.score_answer(answer, gold.get("context", []))
        return Score(
            metric="faithfulness",
            value=result.value if result.value is not None else 0.0,
            tier=self.tier,
            components={
                "n_sentences": result.n_sentences,
                "n_entailed": result.n_entailed,
                "undefined": result.value is None,
            },
        )
