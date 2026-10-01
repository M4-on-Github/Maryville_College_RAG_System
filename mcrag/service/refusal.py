"""T40: service-side refusal classifiers (variants pre-registered in decisions/0016).

The eval classifier `mcrag.eval.tier0_scoring.looks_like_a_refusal` stays frozen so
historical `refusal_correct` numbers remain comparable. Service variants live here.
"""

from __future__ import annotations

import re
from typing import Protocol

from mcrag.eval.tier0_scoring import extract_cited_urls, looks_like_a_refusal
from mcrag.generate.decision_field import ABSTAIN, parse_decision, parse_trailing_decision


class RefusalClassifier(Protocol):
    def is_refusal(self, answer: str) -> bool: ...


_WIDENED = (
    re.compile(r"\bi (?:cannot|can'?t|must|will not|won'?t) (?:comply|refuse|help with)\b", re.I),
    re.compile(r"\bi (?:must|have to) (?:decline|refuse)\b", re.I),
    re.compile(r"\b(?:passages?|provided (?:text|information|context))\b.{0,40}\b(?:do(?:es)? not|don'?t) (?:contain|include|address|mention|provide)\b", re.I),
    re.compile(r"\b(?:out of|outside(?: of)?) (?:the |my )?(?:scope|provided)\b", re.I),
    re.compile(r"\b(?:i am|i'?m) (?:sorry|unable)\b", re.I),
)


class CurrentClassifier:
    """Variant 0: the eval classifier as-is (the control)."""

    def is_refusal(self, answer: str) -> bool:
        return looks_like_a_refusal(answer)


class WidenedPhraseClassifier:
    """Variant 1: current phrases plus the wordings seen in the T39-precursor live check."""

    def is_refusal(self, answer: str) -> bool:
        return looks_like_a_refusal(answer) or any(p.search(answer) for p in _WIDENED)


class CiteNothingClassifier:
    """Variant 2: an answer that cites no source URL is a refusal (the service prompt
    requires a URL for every passage used)."""

    def is_refusal(self, answer: str) -> bool:
        return not extract_cited_urls(answer)


class NarrowPhraseClassifier:
    """Variant 4, **added post-hoc** after the v1 replay (decisions/0016): v1 minus the
    broad "the passages do not contain ..." pattern, which fired on 18 substantive
    answers that merely noted a gap. Catches the 4 live misses via the first-person
    refusal wordings and "I am sorry", and flags nothing new on 635 dev answers."""

    _PATTERNS = tuple(p for i, p in enumerate(_WIDENED) if i != 2)

    def is_refusal(self, answer: str) -> bool:
        return looks_like_a_refusal(answer) or any(p.search(answer) for p in self._PATTERNS)


class CombinedClassifier:
    """Variant 3: variant 1 or variant 2."""

    def __init__(self) -> None:
        self._parts = (WidenedPhraseClassifier(), CiteNothingClassifier())

    def is_refusal(self, answer: str) -> bool:
        return any(p.is_refusal(answer) for p in self._parts)


class DecisionFieldClassifier:
    """T41 (decisions/0017): read the model's own `DECISION:` line instead of
    inferring refusal from prose. Falls back to `fallback` when the line is absent,
    because a protocol violation must not silently become "did not refuse".

    **Wired nowhere, and staying that way.** It is only correct with
    `DECISION_FIELD_SYSTEM_PROMPT`, and that prompt was **rejected** by the T41 dev
    A/B (decisions/0017): the field itself is reliable (0/60 protocol violations,
    12/12 out-of-scope caught against the shipped classifier's 8/12), but the prompt
    that produces it suppresses partial answers. Kept for the record, like the
    rejected v1-v3 classifiers above.
    """

    def __init__(self, fallback: RefusalClassifier | None = None) -> None:
        self._fallback = fallback if fallback is not None else NarrowPhraseClassifier()

    def is_refusal(self, answer: str) -> bool:
        decision, _rest = parse_decision(answer)
        if decision is None:
            return self._fallback.is_refusal(answer)
        return decision == ABSTAIN


class SuffixDecisionFieldClassifier:
    """T41b (decisions/0018): reads a *trailing* `DECISION:` line. Same fallback
    contract as `DecisionFieldClassifier` -- a protocol violation must not silently
    become "did not refuse". Only correct with `SUFFIX_DECISION_FIELD_SYSTEM_PROMPT`.

    **Wired nowhere, and staying that way.** The suffix prompt was also **rejected**
    (decisions/0018). It fixed what T41 broke -- 0 content losses against T41's 5,
    +16 completion tokens rather than -10, cross_silo -0.500 -> -0.143 -- and it never
    answered an out-of-scope question (0/12 against the control's 3/12) with 0/60
    protocol violations. It lost on the pre-registered primary: pooled refusal_correct
    +0.033 [-0.050, +0.133], 2 net question flips in 60. Per the decisions/0011
    stopping rule this was the second and last variant of answer-level labelling, so
    layer 5 ships as `NarrowPhraseClassifier` with its blind spot documented.
    """

    def __init__(self, fallback: RefusalClassifier | None = None) -> None:
        self._fallback = fallback if fallback is not None else NarrowPhraseClassifier()

    def is_refusal(self, answer: str) -> bool:
        decision, _rest = parse_trailing_decision(answer)
        if decision is None:
            return self._fallback.is_refusal(answer)
        return decision == ABSTAIN


VARIANTS: dict[str, RefusalClassifier] = {
    "v0_current": CurrentClassifier(),
    "v1_widened_phrases": WidenedPhraseClassifier(),
    "v2_cite_nothing": CiteNothingClassifier(),
    "v3_combined": CombinedClassifier(),
    "v4_narrow_phrases": NarrowPhraseClassifier(),
}
