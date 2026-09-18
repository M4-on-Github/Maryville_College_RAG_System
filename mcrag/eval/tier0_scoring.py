"""Task 19, Tier 0: deterministic generation-quality checks (PLAN Sec 4d).

Free, and "does more work than it looks" -- published RAG citation accuracy
runs 65-70% without attribution training, so these four checks alone already
discriminate between configs, before a single model call scores anything.

The naive prompt (`mcrag.generate.prompting`) never forces a citation
syntax -- that's ablation #8's job (Task 22), not this one's -- so citation
extraction here is deliberately format-agnostic: any bare URL the answer
happens to contain, exactly as Task 16's real hand-scored answers already
show (a "Source: ... (https://...)" line, unprompted). A metric that only
worked once a citation format existed would be unusable until Task 22.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mcrag.eval.nli_faithfulness import split_sentences
from mcrag.retrieval.literal import detect_entities

_URL = re.compile(r"https?://[^\s)>\]\"']+")
_TRAILING_PUNCT = ".,;:!?"

_REFUSAL_PATTERNS = (
    re.compile(r"\bi (?:can'?t|cannot|don'?t|do not) (?:tell|answer|find|provide|help)", re.I),
    re.compile(r"\b(?:no information|(?:not|don'?t) (?:contain|have) (?:any )?information)\b", re.I),
    re.compile(r"\bi'?m not able to\b", re.I),
    re.compile(r"\b(?:please )?contact\b.{0,40}\b(?:office|department)\b", re.I),
    re.compile(r"\bunable to (?:answer|determine|find)\b", re.I),
)


@dataclass(frozen=True, slots=True)
class Tier0Result:
    """Every field is `None` when the check is undefined for this answer --
    e.g. an answer that cites nothing has no citation accuracy to report,
    which is a different fact from citing everything wrong (0.0)."""

    citation_accuracy: float | None
    citation_validity: float | None
    refused: bool
    refusal_correct: bool
    exact_match_presence: float | None


def extract_cited_urls(answer: str) -> list[str]:
    """Every bare URL in `answer`, trailing sentence punctuation stripped."""
    return [u.rstrip(_TRAILING_PUNCT) for u in _URL.findall(answer)]


def looks_like_a_refusal(answer: str) -> bool:
    return any(p.search(answer) for p in _REFUSAL_PATTERNS)


def score_tier0(
    answer: str,
    question: str,
    retrieved_urls: set[str],
    gold_urls: set[str],
    *,
    expects_answer: bool,
) -> Tier0Result:
    """`expects_answer`: does this question have gold refs at all -- i.e.
    should the system answer rather than refuse (an `out_of_scope` question
    has none, and refusing on it is the *correct* outcome, not a failure)."""
    cited = extract_cited_urls(answer)
    citation_accuracy = (sum(1 for u in cited if u in gold_urls) / len(cited)) if cited else None
    citation_validity = (
        (sum(1 for u in cited if u in retrieved_urls) / len(cited)) if cited else None
    )

    refused = looks_like_a_refusal(answer)
    refusal_correct = refused != expects_answer

    entities = detect_entities(question)
    exact_match_presence = (
        (sum(1 for e in entities if e in answer) / len(entities)) if entities else None
    )

    return Tier0Result(
        citation_accuracy=citation_accuracy,
        citation_validity=citation_validity,
        refused=refused,
        refusal_correct=refusal_correct,
        exact_match_presence=exact_match_presence,
    )


# ---- Task 22, ablation #8: citation-marker compliance ----------------------
#
# Separate from `score_tier0` on purpose: `[N]` markers are only meaningful
# once a prompt asks for them (`mcrag.generate.prompting.CITATION_FORCED_SYSTEM_PROMPT`),
# and `score_tier0`'s contract is shared by every arm, forced or not.

_MARKER = re.compile(r"\[(\d+)\]")
_MIN_SENTENCE_WORDS = 3


@dataclass(frozen=True, slots=True)
class CitationMarkerResult:
    """`compliance` is `None`, not 0.0, when the answer has no sentence
    substantial enough to need a citation (e.g. a bare "No.") -- undefined,
    not a failure to comply."""

    compliance: float | None
    n_sentences: int
    n_marked: int
    n_invalid_markers: int  # markers outside 1..n_passages -- a fabricated citation


def extract_citation_markers(sentence: str) -> list[int]:
    return [int(m) for m in _MARKER.findall(sentence)]


def score_citation_markers(answer: str, n_passages: int) -> CitationMarkerResult:
    """Fraction of the answer's factual sentences carrying at least one
    valid `[N]` marker (`1 <= N <= n_passages`). A sentence is "factual"
    here if it has at least three words once its markers are stripped --
    the same bar `answer_claims` (Tier 1) uses to drop bare "No."/"Yes."
    fragments, kept consistent rather than reinvented per metric.
    """
    sentences = [s for s in split_sentences(answer) if len(_MARKER.sub("", s).split()) >= _MIN_SENTENCE_WORDS]
    if not sentences:
        return CitationMarkerResult(compliance=None, n_sentences=0, n_marked=0, n_invalid_markers=0)

    n_marked = 0
    n_invalid = 0
    for sentence in sentences:
        markers = extract_citation_markers(sentence)
        valid = [m for m in markers if 1 <= m <= n_passages]
        n_invalid += len(markers) - len(valid)
        if valid:
            n_marked += 1

    return CitationMarkerResult(
        compliance=n_marked / len(sentences),
        n_sentences=len(sentences),
        n_marked=n_marked,
        n_invalid_markers=n_invalid,
    )
