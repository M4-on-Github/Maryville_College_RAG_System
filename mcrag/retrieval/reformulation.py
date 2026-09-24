"""Ablation #6: the query-reformulation ladder (PLAN Sec4c), cheapest first.

Each rung is a `Reformulator` (mcrag.interfaces). `ChainedReformulator`
composes rungs in order: `reform()` returns one or more query strings, and a
later rung runs over every query the rung before it produced, so a rung that
fans out (decomposition, multi-query, step-back) composes correctly with
rungs before and after it without special-casing.

Steps 1-2 are free and deterministic -- no model call, no network. Steps 3-7
(decomposition, multi-query, de-contextualization, step-back, HyDE) each cost
a cloud generation call and were **not built for ablation #6**: rung 1 failed
its pre-registered bar and the ladder stopped there (`decisions/0011`).

**Step 5 (de-contextualization) is built anyway, by a different warrant.**
PLAN Sec4c calls it "mandatory for multi-turn", and it is the mechanism the
~15-question `multi_turn` gold slice exists to measure (Task 28) -- not an
optional rung of ablation #6's pooled-dev ladder. The distinction matters and
is not a loophole: on the pooled 60-question dev set the ladder scored, ~45
questions carry no `history` at all, so de-contextualization is a structural
no-op for them and the pooled metric is arithmetically incapable of detecting
its effect. `decisions/0011` declined to *spend quota* on rungs 3-7; it never
measured this one, and its finding ("reformulation doesn't help this corpus
at the frozen retrieval config") is a statement about single-turn retrieval
that the multi-turn slice does not fall under. Task 28 measures it on the
population where it can act, and reports the result either way
(`decisions/0015`).

Both step-5 arms below share one property worth stating plainly: **with no
`history` they return the query unchanged**, so a single-turn request costs
exactly what it costs today -- zero extra calls, zero extra latency.

`DEFAULT_DICTIONARY` is seeded from real term frequency in
`corpus/chunks.jsonl`, not PLAN's illustrative example list -- `SEVIS`,
standalone `ISS`, and `CRN` all have zero occurrences in the actual corpus
(verified 2026-09-17; see decisions/0011). Every entry below was confirmed
against real corpus context before inclusion.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from mcrag.interfaces import Generator, Reformulator

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

    def reform(self, query: str, history: Sequence[str] | None = None) -> list[str]:
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

    def reform(self, query: str, history: Sequence[str] | None = None) -> list[str]:
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

    def reform(self, query: str, history: Sequence[str] | None = None) -> list[str]:
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

    def reform(self, query: str, history: Sequence[str] | None = None) -> list[str]:
        text = query
        for _wrong, pattern, right in self._patterns:
            text = pattern.sub(right, text)
        return [text]


# ---- step 5: conversational de-contextualization (Task 28) -----------------


class HistoryConcatenationReformulator(Reformulator):
    """Step 5's **free control**: append the prior user turns' text to the
    follow-up, oldest first.

    This is deliberately *not* de-contextualization -- it produces no
    standalone question, it just drags the missing entity terms ("standard
    double room", "counseling center") into the query string so the BM25 and
    literal legs can match on them and the dense leg embeds something less
    ambiguous than "What if I wanted a single instead?".

    It exists because PLAN Sec4c's whole doctrine is cheapest-first: a
    metered rewrite has to beat the free thing that captures most of the same
    signal, not merely beat the raw follow-up. Free, deterministic, single
    query out, no model call.
    """

    name = "history_concat"

    def __init__(self, max_turns: int | None = None) -> None:
        # `None` = use every prior turn. A cap exists because query length is
        # not free for BM25 (extra token mass competes for the fixed
        # CANDIDATE_K slots -- decisions/0011's own explanation for why rung
        # 1 plausibly *hurt*), but no value is measured, so the default
        # declines to guess.
        self.max_turns = max_turns

    def reform(self, query: str, history: Sequence[str] | None = None) -> list[str]:
        if not history:
            return [query]
        turns = list(history)
        if self.max_turns is not None:
            turns = turns[-self.max_turns :]
        return [" ".join([*turns, query])]


DECONTEXTUALIZE_SYSTEM_PROMPT = """You rewrite a follow-up question into a standalone one.

You are given earlier questions from the same conversation, then the latest
follow-up. Rewrite ONLY the follow-up so it can be understood with no
conversation history: replace pronouns and ellipsis ("it", "that", "a single
instead") with the actual subject from the earlier turns.

Rules:
- Output the rewritten question and nothing else. No preamble, no quotes, no
  explanation.
- Keep it one question, in the student's own register. Do not answer it.
- Do not invent details that appear in neither the history nor the follow-up.
- If the follow-up already stands alone, output it unchanged."""


class LlmDecontextualizer(Reformulator):
    """Step 5 proper (PLAN Sec4c, "mandatory for multi-turn"): one metered
    generation call rewrites an under-specified follow-up into a standalone
    question, which is what retrieval then runs on.

    **Cost shape.** No history means no call at all, so single-turn traffic
    is untouched; a follow-up costs exactly one extra short completion (the
    output is one question, not an answer).

    **Failure policy: fall back to the raw query, never to a guess.** An
    empty reply, a multi-line essay, or any exception from the generator
    (timeout, quota) returns the original follow-up unchanged -- degrading to
    today's behavior, which is a known quantity, rather than retrieving on
    text the model improvised. `last_error` records why, so a caller can log
    it instead of silently seeing a no-op.

    Drives `Generator.generate()`, the actual interface seam, rather than
    `OllamaCloudGenerator.complete()` -- `complete()` is a convenience on one
    concrete class, not on the ABC, and this rung has to run against a stub
    generator in tests and a cached replay in reruns.
    """

    name = "llm_decontext"

    # A rewrite is one question. Anything much longer than the longest gold
    # question is the model explaining itself or answering, not rewriting.
    MAX_CHARS = 300

    def __init__(
        self,
        generator: Generator,
        system_prompt: str = DECONTEXTUALIZE_SYSTEM_PROMPT,
        temperature: float = 0.0,
    ) -> None:
        self.generator = generator
        self.system_prompt = system_prompt
        # Greedy: a rewrite is a mechanical transformation, and this rung has
        # to be re-runnable for a noise floor. Sampling here would put
        # variance into the *retrieval* arm, where the ablation cannot tell it
        # apart from a real effect.
        self.temperature = temperature
        self.last_error: str | None = None
        self.calls = 0
        # Metered work is accounted for, not just performed -- the project
        # reports quota spent per arm.
        self.usage: list[dict] = []

    def _complete(self, prompt: str) -> str:
        """One call, drained to the visible answer text."""
        done: dict = {}
        tokens: list[str] = []
        for event in self.generator.generate(
            prompt, system=self.system_prompt, temperature=self.temperature
        ):
            if event.type == "token":
                tokens.append(event.data.get("text", ""))
            elif event.type == "done":
                done = event.data
        if done.get("usage"):
            self.usage.append(dict(done["usage"]))
        return done.get("text") or "".join(tokens)

    @staticmethod
    def _build_prompt(query: str, turns: Sequence[str]) -> str:
        earlier = "\n".join(f"{i}. {t}" for i, t in enumerate(turns, start=1))
        return f"Earlier questions in this conversation:\n{earlier}\n\nFollow-up to rewrite:\n{query}"

    @staticmethod
    def _clean(text: str) -> str:
        # Models like to wrap a rewrite in quotes or prefix it with a label,
        # both of which would otherwise be retrieved on as literal text.
        cleaned = text.strip().strip("`").strip()
        for prefix in ("standalone question:", "rewritten question:", "rewrite:", "question:"):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()
        if len(cleaned) >= 2 and cleaned[0] in "\"'" and cleaned[-1] == cleaned[0]:
            cleaned = cleaned[1:-1].strip()
        return cleaned

    def reform(self, query: str, history: Sequence[str] | None = None) -> list[str]:
        self.last_error = None
        if not history:
            return [query]  # single-turn: no call, no cost

        prompt = self._build_prompt(query, list(history))
        try:
            self.calls += 1
            rewritten = self._clean(self._complete(prompt))
        except Exception as exc:  # timeout, quota, transport -- all the same here
            self.last_error = f"{type(exc).__name__}: {exc}"
            return [query]

        if not rewritten:
            self.last_error = "empty rewrite"
            return [query]
        if len(rewritten) > self.MAX_CHARS:
            self.last_error = f"rewrite too long ({len(rewritten)} chars)"
            return [query]
        if "\n" in rewritten.strip():
            self.last_error = "rewrite spans multiple lines"
            return [query]
        return [rewritten]
