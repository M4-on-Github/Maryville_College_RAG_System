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
