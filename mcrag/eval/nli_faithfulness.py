"""Task 19, Tier 1: local NLI faithfulness (PLAN Sec 4d).

Faithfulness, not correctness: does the answer say things the retrieved
context actually supports, regardless of whether that context was the right
context to retrieve (that's Phase 3's retrieval metrics' job) or whether the
underlying fact is true (that's what a human or Tier 3 judge assesses).

Same tool class as `mcrag.retrieval.reranker.CrossEncoderReranker` -- a local
`sentence_transformers.CrossEncoder`, lazy-loaded, zero quota, offline once
cached -- because an NLI cross-encoder and a relevance cross-encoder are the
same architecture pointed at a different label space.

**Why the context is windowed, not concatenated.** DeBERTa takes 512 tokens
per (premise, hypothesis) pair. Five retrieved 512-token chunks joined into
one premise is 1,500-2,500 tokens, and the tokenizer silently drops
everything past the limit -- the first version of this scorer did exactly
that, saw ~20% of the context, and reported a faithfulness of 0.013 on the
Task 20 baseline. That number measured the truncation, not the answers. So
each chunk is cut into overlapping windows small enough to fit beside a
claim, every claim is checked against every window, and a claim counts as
supported if any window entails it (the max-over-premises approach). Pairs
that still overflow are counted in `n_truncated_pairs` rather than trusted.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from mcrag.interfaces import Scorer
from mcrag.types import Score

DEFAULT_NLI_MODEL = "cross-encoder/nli-deberta-v3-base"
SCORER_VERSION = "3-windowed-max-normalized"

# Verified against the downloaded model's own config.id2label on 2026-09-16:
# {0: contradiction, 1: entailment, 2: neutral}. Re-check if `model_name` changes.
DEFAULT_ENTAILMENT_INDEX = 1

# ~1000 chars is ~250-300 DeBERTa tokens of English prose, leaving room for a
# claim beside it under the 512-token pair limit. `n_truncated_pairs` is what
# verifies this holds on real data, not this comment.
DEFAULT_WINDOW_CHARS = 1000

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_CITATION_MARKER = re.compile(r"【\d+】|\[\d+\]")
# "According to the Fine Arts page, <claim>" / "MC's policy states that <claim>":
# the attribution is unverifiable against a passage, so NLI calls the whole
# sentence neutral even when <claim> is a verbatim quote. Worse, a
# citation-forced prompt (ablation #8) emits more of these by design, so left
# in, this would bias the pre-registered #8 comparison against attributing.
_ATTRIBUTION_LEAD = re.compile(
    r"^(?:according to|as (?:stated|noted|described|explained) (?:on|in|by))\b[^,]{0,120},\s*", re.I
)
_ATTRIBUTION_VERB = re.compile(
    r"^[^,.]{0,120}?\b(?:states?|notes?|says?|explains?|indicates?|confirms?|specifies?)\s+that\s+", re.I
)
_UNICODE_PUNCT = str.maketrans(
    {
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
        "‘": "'", "’": "'", "“": '"', "”": '"',
        " ": " ", " ": " ", " ": " ", "​": "",
    }
)


def normalize_text(text: str) -> str:
    """NFKC plus ASCII punctuation. LLM output uses non-breaking hyphens and
    narrow no-break spaces the scraped corpus mostly doesn't, and the NLI
    tokenizer treats `per‑year` and `per-year` as different strings."""
    return unicodedata.normalize("NFKC", text).translate(_UNICODE_PUNCT)


def strip_attribution(claim: str) -> str:
    stripped = _ATTRIBUTION_VERB.sub("", _ATTRIBUTION_LEAD.sub("", claim)).strip()
    stripped = stripped.strip("\"'").strip()
    if len(stripped.split()) < _MIN_CLAIM_WORDS:
        return claim  # the wrapper *was* the content; don't reduce it to nothing
    return stripped[0].upper() + stripped[1:]
_SOURCE_PAREN = re.compile(r"\(\s*sources?:[^)]*\)", re.I)
_URL = re.compile(r"https?://\S+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_MIN_CLAIM_WORDS = 3


def split_sentences(text: str) -> list[str]:
    """A deliberately simple splitter. Empty fragments are dropped."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def answer_claims(answer: str) -> list[str]:
    """The checkable claims in an LLM answer.

    Strips what isn't a claim about the world -- markdown emphasis, citation
    markers, "(Source: ...)" asides, bare URLs, "Source:" lines -- splits on
    line breaks (bulleted answers put one claim per line) and then on
    sentence boundaries, and drops fragments under three words ("No.",
    "Yes."), which carry no content an entailment model can check alone.
    """
    text = normalize_text(answer).replace("**", "").replace("__", "")
    text = _SOURCE_PAREN.sub("", text)
    text = _CITATION_MARKER.sub("", text)
    text = _URL.sub("", text)

    claims: list[str] = []
    for line in text.splitlines():
        line = _BULLET.sub("", line).strip()
        if not line or line.lower().startswith("source"):
            continue
        for sentence in split_sentences(line):
            if len(sentence.split()) >= _MIN_CLAIM_WORDS:
                claims.append(strip_attribution(sentence))
    return claims


def premise_windows(text: str, max_chars: int = DEFAULT_WINDOW_CHARS) -> list[str]:
    """Overlapping windows of whole sentences, each at most `max_chars`.

    A sentence longer than `max_chars` is hard-split, so every window is
    guaranteed to fit. Consecutive windows overlap by about half, so a fact
    spanning a window boundary still appears whole in one of them.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    pieces: list[str] = []
    for sentence in split_sentences(normalize_text(text)):
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if sentence:
            pieces.append(sentence)

    windows: list[str] = []
    start = 0
    while start < len(pieces):
        end, size = start, 0
        while end < len(pieces):
            added = len(pieces[end]) + (1 if end > start else 0)
            if size + added > max_chars:
                break
            size += added
            end += 1
        windows.append(" ".join(pieces[start:end]))
        if end >= len(pieces):
            break
        start = max(start + 1, (start + end) // 2)
    return windows


@dataclass(frozen=True, slots=True)
class FaithfulnessResult:
    value: float | None  # None when there's nothing to score (no claims or no context)
    n_claims: int
    n_entailed: int
    per_claim: tuple[bool, ...]
    n_pairs: int = 0
    n_truncated_pairs: int = 0


class NLIFaithfulnessScorer(Scorer):
    """`score()` implements `mcrag.interfaces.Scorer`; `score_answer()` returns
    the richer `FaithfulnessResult` (per-claim detail, a truncation count,
    and `None` rather than a misleading 0.0 when there's nothing to score)."""

    tier = 1

    def __init__(
        self,
        model_name: str = DEFAULT_NLI_MODEL,
        entailment_index: int = DEFAULT_ENTAILMENT_INDEX,
        window_chars: int = DEFAULT_WINDOW_CHARS,
    ) -> None:
        self.model_name = model_name
        self.entailment_index = entailment_index
        self.window_chars = window_chars
        self._model = None
        self._tokenizer = None
        self._max_length: int | None = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
            self._tokenizer = getattr(self._model, "tokenizer", None)
            self._max_length = getattr(self._tokenizer, "model_max_length", None)
        return self._model

    def _count_truncated(self, pairs: list[tuple[str, str]]) -> int:
        if self._tokenizer is None or not self._max_length:
            return 0
        return sum(
            1 for premise, claim in pairs
            if len(self._tokenizer(premise, claim)["input_ids"]) > self._max_length
        )

    def score_answer(self, answer: str, context: list[str]) -> FaithfulnessResult:
        claims = answer_claims(answer)
        windows = [w for chunk in context for w in premise_windows(chunk, self.window_chars)]
        if not claims or not windows:
            return FaithfulnessResult(value=None, n_claims=len(claims), n_entailed=0, per_claim=())

        model = self._load()
        pairs = [(window, claim) for claim in claims for window in windows]
        logits = model.predict(pairs)

        per_claim = []
        for i in range(len(claims)):
            rows = logits[i * len(windows) : (i + 1) * len(windows)]
            per_claim.append(any(int(row.argmax()) == self.entailment_index for row in rows))
        n_entailed = sum(per_claim)
        return FaithfulnessResult(
            value=n_entailed / len(claims),
            n_claims=len(claims),
            n_entailed=n_entailed,
            per_claim=tuple(per_claim),
            n_pairs=len(pairs),
            n_truncated_pairs=self._count_truncated(pairs),
        )

    def score(self, answer: str, gold: dict) -> Score:
        result = self.score_answer(answer, gold.get("context", []))
        return Score(
            metric="faithfulness",
            value=result.value if result.value is not None else 0.0,
            tier=self.tier,
            components={
                "n_claims": result.n_claims,
                "n_entailed": result.n_entailed,
                "n_truncated_pairs": result.n_truncated_pairs,
                "undefined": result.value is None,
                "scorer_version": SCORER_VERSION,
            },
        )
