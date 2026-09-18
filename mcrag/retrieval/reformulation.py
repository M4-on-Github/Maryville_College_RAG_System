"""Ablation #6: the query-reformulation ladder (PLAN Sec4c), cheapest first.

Each rung is a `Reformulator` (mcrag.interfaces). `ChainedReformulator`
composes rungs in order: `reform()` returns one or more query strings, and a
later rung runs over every query the rung before it produced, so a rung that
fans out (decomposition, multi-query, step-back) composes correctly with
rungs before and after it without special-casing.

Steps 1-2 (this module, so far) are free and deterministic -- no model call,
no network. Steps 3-7 (decomposition, multi-query, de-contextualization,
step-back, HyDE) each cost a cloud generation call and are built once the
noise-floor-relative stopping rule (decisions/0011) says the ladder hasn't
flattened yet.

`DEFAULT_DICTIONARY` is seeded from real term frequency in
`corpus/chunks.jsonl`, not PLAN's illustrative example list -- `SEVIS`,
standalone `ISS`, and `CRN` all have zero occurrences in the actual corpus
(verified 2026-09-17; see decisions/0011). Every entry below was confirmed
against real corpus context before inclusion.
"""

from __future__ import annotations

import re

from mcrag.interfaces import Reformulator

# term -> expansions to append when the term is found in the query.
# Short-form -> long-form is the direction the real corpus rewards: MC's
# pages spell "ISEP", "NSO", "MCAA", etc. out in full near the acronym, but
# a student's query is more likely to carry only the acronym, or only the
# long form, not both. "MC" is the one genuinely bidirectional pair (both
# forms are common in both queries and corpus, 2101 raw occurrences).
DEFAULT_DICTIONARY: dict[str, tuple[str, ...]] = {
    "MC": ("Maryville College",),
    "Maryville College": ("MC",),
    "FAFSA": ("Free Application for Federal Student Aid",),
    "GPA": ("Grade Point Average",),
    "ISEP": ("International Student Exchange Program",),
    "NSO": ("New Scots Orientation",),
    "MCAA": ("Maryville College Alumni Association",),
    "SGA": ("Student Government Association",),
    "GI Bill": ("Post-9/11 GI Bill", "veterans benefits"),
    "I-20": ("Form I-20", "Certificate of Eligibility", "international student"),
    "F-1": ("F-1 visa", "international student status"),
    "STEM": ("Science Technology Engineering Math",),
}

# Hand-authored, not mined from logged real queries -- none exist yet
# (every gold question's `provenance` is "synthetic" today, decisions/0004).
# Treat this as a seed to grow once real traffic exists, not a claim of
# completeness.
DEFAULT_CORRECTIONS: dict[str, str] = {
    "FASFA": "FAFSA",
    "Marysville": "Maryville",
    "Maryvile": "Maryville",
    "transcirpt": "transcript",
    "scholarhip": "scholarship",
    "scholarhsip": "scholarship",
    "admisssion": "admission",
    "recieve": "receive",
    "seperate": "separate",
}


def _word_pattern(term: str) -> re.Pattern[str]:
    return re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)


class IdentityReformulator(Reformulator):
    """No-op control: query in, same query out. The ladder's rung zero."""

    name = "identity"

    def reform(self, query: str, history: list[tuple[str, str]] | None = None) -> list[str]:
        return [query]


class ChainedReformulator(Reformulator):
    """Compose ladder rungs in order. Fans out through later rungs.

    A rung that returns multiple queries (decomposition, multi-query,
    step-back) causes every later rung to run once per query it produced --
    e.g. spelling normalization after decomposition normalizes each
    sub-query independently, not just the original.
    """

    def __init__(self, stages: list[Reformulator]) -> None:
        if not stages:
            raise ValueError("ChainedReformulator needs at least one stage")
        self.stages = list(stages)
        self.name = "+".join(s.name for s in self.stages)

    def reform(self, query: str, history: list[tuple[str, str]] | None = None) -> list[str]:
        queries = [query]
        for stage in self.stages:
            expanded: list[str] = []
            for q in queries:
                expanded.extend(stage.reform(q, history))
            seen: set[str] = set()
            deduped = []
            for q in expanded:
                if q not in seen:
                    seen.add(q)
                    deduped.append(q)
            queries = deduped
        return queries


class AcronymDictionaryReformulator(Reformulator):
    """Step 1: bidirectional acronym/synonym expansion.

    Augments rather than replaces -- appends recognized counterpart forms to
    the query text so BM25/literal legs gain the extra surface form without
    losing the student's own phrasing. Free, deterministic, single query out.
    """

    name = "acronym_dict"

    def __init__(self, dictionary: dict[str, tuple[str, ...]] | None = None) -> None:
        self.dictionary = dictionary if dictionary is not None else DEFAULT_DICTIONARY
        self._patterns = [(term, _word_pattern(term), exps) for term, exps in self.dictionary.items()]

    def reform(self, query: str, history: list[tuple[str, str]] | None = None) -> list[str]:
        lowered = query.lower()
        added: list[str] = []
        for _term, pattern, expansions in self._patterns:
            if not pattern.search(query):
                continue
            for exp in expansions:
                if exp.lower() not in lowered and exp not in added:
                    added.append(exp)
        if not added:
            return [query]
        return [query + " " + " ".join(added)]


class SpellingNormalizer(Reformulator):
    """Step 2: fix known institutional-jargon misspellings.

    Free, deterministic, single query out. See `DEFAULT_CORRECTIONS` for the
    provenance caveat -- this is a seed list, not a mined one.
    """

    name = "spelling_norm"

    def __init__(self, corrections: dict[str, str] | None = None) -> None:
        self.corrections = corrections if corrections is not None else DEFAULT_CORRECTIONS
        self._patterns = [(wrong, _word_pattern(wrong), right) for wrong, right in self.corrections.items()]

    def reform(self, query: str, history: list[tuple[str, str]] | None = None) -> list[str]:
        text = query
        for _wrong, pattern, right in self._patterns:
            text = pattern.sub(right, text)
        return [text]
