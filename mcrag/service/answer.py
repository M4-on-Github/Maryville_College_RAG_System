"""Task 24: `answer(question, history) -> Iterator[AnyEvent]` -- the callable
Task 25's API is a thin transport shell over.

**No web framework import anywhere below this line, or in anything it
imports.** That is the whole point: this module is importable and callable
from a script, a test, or a notebook with no server running, which is what
keeps the API optional infrastructure rather than the product itself.

Runs the frozen Checkpoint-E config end to end, the same frozen retrieval
build the eval scripts use (`mcrag.retrieval.frozen_pipeline`,
`decisions/0007`), model `gemma4:31b` (`decisions/0010`, confirmed on test in
T22b), `SERVICE_SYSTEM_PROMPT` (`mcrag.generate.prompting` -- the adopted
rung 1 scope-strict prompt, `decisions/0014`, extended with user-turn
injection resistance), and `build_user_prompt(passage_chars=None)` so no
retrieved text is silently cut (`decisions/0008`).

**Task 27 -- refusal routing, two of the three named pathways.** `reason`
can be `threshold`, `gate`, or `model` (`mcrag.service.events.RefusalEvent`).
This module wires exactly two:

- `threshold`: Task 21's retrieval-score gate (`decisions/0009`) -- raw
  cross-encoder MaxP score over the frozen top-`K` chunks
  (`mcrag.eval.abstention.maxp_scores` + `raw_top`, same functions and
  methodology decisions/0009 was calibrated with, not a reimplementation),
  refuse if the score is below `TAU`. It runs on retrieval output alone, so
  it is checked *before* the generation call -- a request it refuses never
  spends generation quota. Also fires (score reported as `None`) when
  retrieval returns zero chunks at all, since there is then nothing a
  threshold score could even be computed over.
- `model`: the model itself declining in its own generated text
  (`mcrag.eval.tier0_scoring.looks_like_a_refusal`), unchanged from Task 24.
  Only reached when `threshold` did not already fire.

- `gate` is deliberately **not wired**, by explicit human decision (this
  session, recorded in `tasks/plan.md` T27's Resolution). `decisions/0014`
  already built and rejected a dedicated two-step LLM answerability gate
  (rung 3): it closed the out-of-scope gap completely but cost
  `-0.217 [-0.350, -0.083]` refusal_correct -- outside every noise floor
  measured in this project, and worse than rung 2's own rejected cost.
  Re-wiring a gate here without new evidence would re-litigate a settled,
  evidence-backed decision. `RefusalEvent.reason`'s `"gate"` literal stays
  schema-valid for forward compatibility; no code path in this module ever
  constructs one.

Any-signal-wins precedence between the two wired signals is realized by
short-circuit order, not a simultaneous vote: `threshold` is cheap, local,
and needs no generation, so it is always evaluated first; `model` is only
ever reached for a request `threshold` already passed. Both signals (score,
verdict) plus which one -- if either -- won are logged per request (this
module's `logger`), per T27's own acceptance criterion.

A refusal of either wired reason routes to a real per-silo office
(`mcrag.offices.resolve`, `data/offices.yaml`, T8), keyed on the
top-ranked retrieved chunk's silo (or `None` if nothing was retrieved) --
replacing Task 24's hardcoded Admissions placeholder.

**Task 26** added to this module: `sources[].stale` (`_source_events`'s
`staleness_days`/`now`, `DEFAULT_STALENESS_DAYS` below) and a logged
`sources_to_first_token_ms` measurement (this module's `logger`) -- both
additive to Task 24's original shape, not a redesign of it.

**Task 28 -- conversation memory and follow-up rewriting.** `history` was
always accepted per request (Task 24) and this module has never held session
state: everything it keeps between requests is the *pipeline* (indexes,
embedder, generator), all of it rebuildable from the corpus, and every
conversational fact arrives in the call itself. T28 adds the rewriting half
of PLAN §4c step 5: an optional `AnswerPipeline.reformulator` turns an
under-specified follow-up into a standalone query *before* retrieval.

Two rules govern it:

- **Retrieve on the rewrite, generate on the original question.** The
  rewrite exists to fix retrieval, which has no conversation to condition
  on. Generation already sees the real prior turns as chat messages, so
  substituting a rewrite there would risk answering a subtly different
  question than the student asked, and the student would never see the
  substitution.
- **Nothing is rewritten silently.** The query retrieval actually ran on is
  published in `sources.rewritten_query` and logged. `None` there means no
  rewrite happened, so the question the client sent is the query.

The default pipeline configures `LlmDecontextualizer`, adopted on
`decisions/0015`'s measured result: on the 9 dev+train multi-turn questions
it took `all_golds_retrieved@5` from 0.222 to 0.667, +0.444 [+0.111, +0.778],
improving 4 and regressing none, against a noise floor of exactly zero (the
rerun reproduced all 9 rewrites byte-identically at `temperature=0`). The
free control arm (`HistoryConcatenationReformulator`) reached 0.556 but
regressed one question, mt-03, by diluting the query with two concatenated
turns -- the same mechanism `decisions/0011` diagnosed for the acronym rung.
Single-turn traffic pays nothing: with no `history` the rewriter makes no
call and returns the query unchanged.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import date

from mcrag.eval.abstention import maxp_scores, raw_top
from mcrag.eval.tier0_scoring import looks_like_a_refusal
from mcrag.generate.ollama_cloud import OllamaCloudGenerator
from mcrag.generate.prompting import SERVICE_SYSTEM_PROMPT, build_user_prompt
from mcrag.interfaces import Embedder, Reformulator
from mcrag.offices import resolve as resolve_office
from mcrag.retrieval.bm25 import BM25Index
from mcrag.retrieval.dense import DenseIndex
from mcrag.retrieval.frozen_pipeline import CANDIDATE_K, K, build_indexes
from mcrag.retrieval.fusion import RRFFuser
from mcrag.retrieval.literal import LiteralIndex
from mcrag.retrieval.reformulation import LlmDecontextualizer
from mcrag.retrieval.reranker import CrossEncoderReranker
from mcrag.service.events import (
    AnyEvent,
    CitationEvent,
    DoneEvent,
    LatencyMs,
    RefusalEvent,
    ServerNs,
    SourceChunk,
    SourcesEvent,
    TokenEvent,
)
from mcrag.types import Chunk, Hit

MODEL = "gemma4:31b"  # Checkpoint E, decisions/0010

# Task 28's de-contextualization rewrite is one question, not an answer.
# The value decisions/0015's measured run used -- changing it would make the
# shipped default a configuration nothing was measured at.
REWRITE_MAX_TOKENS = 128

# Task 21's calibrated abstention threshold (decisions/0009): refuse if the
# raw cross-encoder MaxP score over the top-K chunks is below this.
TAU = 4.96

# Task 26: a chunk older than this many days is flagged `stale` in `sources`.
# 180 days is a starting default, not a measured or decided value -- no
# staleness/user-trust study backs this number; a caller that needs a
# different policy overrides it via `answer(..., staleness_days=...)`.
DEFAULT_STALENESS_DAYS = 180

logger = logging.getLogger(__name__)

# Task 27 cosmetic decision: `data/offices.yaml`/`data/silos.yaml` carry no
# ready-made human-facing office label (`contact_title` is a person's job
# title on most rows, not an office name), so the display string in a
# `refusal` event is derived from the silo slug -- title-cased, with the
# handful of abbreviations spelled out. Not a source of truth; the routing
# fields (`contact_url`, `email`) come from `mcrag.offices.resolve` alone.
_DISPLAY_NAME_OVERRIDES = {
    "finaid": "Financial Aid",
    "iss": "International Student Services",
    "title_ix": "Title IX",
}


def _office_fields(chunks: list[Chunk]) -> dict[str, str]:
    silo = chunks[0].silo[0] if chunks and chunks[0].silo else None
    contact = resolve_office(silo)
    display = _DISPLAY_NAME_OVERRIDES.get(contact.silo, contact.silo.replace("_", " ").title())
    return {"office": display, "contact_url": contact.destination_url, "email": contact.email}

_URL = re.compile(r"https?://[^\s)>\]\"']+")
_TRAILING_PUNCT = ".,;:!?"
# Sentence boundary = terminal punctuation followed by whitespace. Splitting
# the whole text up front (as `mcrag.eval.nli_faithfulness.split_sentences`
# does) breaks on every period inside a cited URL itself
# ("maryvillecollege.edu"); this pattern doesn't, because a period midway
# through a URL is never followed by whitespace. Used only to find the
# nearest boundary around an already-located URL match, below.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass
class AnswerPipeline:
    """Everything one request needs, built once and reused across requests.

    Standing up the embedder, the LanceDB table, and the two in-memory
    indexes (`BM25Index`, `LiteralIndex`) per call would make every request
    pay a multi-second setup cost for no reason -- `get_default_pipeline`
    builds exactly one of these, lazily, the first time it is needed.
    """

    dense: DenseIndex
    bm25: BM25Index
    literal: LiteralIndex
    chunk_lookup: dict[str, Chunk]
    embedder: Embedder
    generator: OllamaCloudGenerator
    fuser: RRFFuser
    # Task 27's threshold gate: `CrossEncoderReranker.score_pairs`'s exact
    # signature (raw logits over (query, passage) pairs), not the reranker
    # object itself -- `answer()` only ever needs to score, never to
    # reorder. A local, free, quota-free pass (`mcrag/retrieval/reranker.py`).
    score_pairs: Callable[[list[tuple[str, str]]], list[float]]
    # Task 28, PLAN §4c step 5. `None` = retrieve on the question as sent
    # (`decisions/0011`'s rung 0); `get_default_pipeline` configures
    # `LlmDecontextualizer` instead, per `decisions/0015`. Kept optional
    # because every test in `tests/test_service.py` needs a pipeline that
    # spends no quota, and because a caller with no API key must still be
    # able to run retrieval. Only the first query a rung returns is used:
    # `Reformulator.reform` may fan out (decomposition, multi-query,
    # step-back), but this service retrieves once and fuses three legs, not
    # N*3, so a fan-out rung is not wired here. Both step-5 rungs
    # (`mcrag.retrieval.reformulation`) return exactly one query.
    reformulator: Reformulator | None = None

    def search(self, query: str) -> list[Hit]:
        """The same fused-search shape `mcrag.retrieval.frozen_pipeline.build_search`
        returns -- used here for prior-turn retrieval, where per-leg timing
        doesn't matter. The live turn's own retrieval times each leg
        separately instead (see `answer` below) so `latency_ms` can report
        them, and is not routed through this method."""
        leg_results = [
            self.dense.search(query, CANDIDATE_K),
            self.bm25.search(query, CANDIDATE_K),
            self.literal.search(query, CANDIDATE_K),
        ]
        hits = self.fuser.fuse(leg_results, CANDIDATE_K)
        return [replace(h, chunk=self.chunk_lookup.get(h.chunk_id)) if h.chunk is None else h for h in hits]


_default_pipeline: AnswerPipeline | None = None


def get_default_pipeline() -> AnswerPipeline:
    """The process-wide singleton `answer()` uses when no pipeline is passed
    explicitly. A test that wants a fake generator or a fresh index passes
    its own `pipeline=` instead of touching this."""
    global _default_pipeline
    if _default_pipeline is None:
        dense, bm25, literal, chunk_lookup, embedder = build_indexes()
        generator = OllamaCloudGenerator(model=MODEL, temperature=0.0)
        _default_pipeline = AnswerPipeline(
            dense=dense, bm25=bm25, literal=literal, chunk_lookup=chunk_lookup,
            embedder=embedder, generator=generator, fuser=RRFFuser(),
            score_pairs=CrossEncoderReranker().score_pairs,
            # Task 28 / decisions/0015, at the exact configuration measured
            # there. Its own generator rather than the answer generator's:
            # a rewrite is one question, so `max_tokens=1024` would only buy
            # room for the model to start explaining itself -- which
            # `LlmDecontextualizer`'s length guard would then reject.
            reformulator=LlmDecontextualizer(
                OllamaCloudGenerator(model=MODEL, temperature=0.0, max_tokens=REWRITE_MAX_TOKENS)
            ),
        )
    return _default_pipeline


def _as_user_turn(text: str) -> str:
    # Matches the eval harness's own delimiting of a prior turn (decisions/0008):
    # the system prompt names <question> as the only instruction span a prior
    # user turn was actually answered under.
    return f"<question>\n{text}\n</question>"


def _run_prior_turns(pipeline: AnswerPipeline, user_turns: Sequence[str]) -> list[dict[str, str]]:
    """Same policy as the eval harness's `run_prior_turns`
    (`scripts/run_phase3c_baseline.py`): each earlier user turn is answered
    live, retrieval sees only that turn's own text, and the resulting
    exchange becomes chat history for the final turn. A prior turn never
    runs through this module's refusal/citation/event machinery below --
    only the final, live turn is a real request; prior turns are already
    resolved by the time this request exists."""
    messages: list[dict[str, str]] = []
    for turn in user_turns:
        hits = [h for h in pipeline.search(turn)[:K] if h.chunk is not None]
        prompt = build_user_prompt(turn, [h.chunk for h in hits], passage_chars=None)
        completion = pipeline.generator.complete(prompt, system=SERVICE_SYSTEM_PROMPT, history=messages)
        messages += [
            {"role": "user", "content": _as_user_turn(turn)},
            {"role": "assistant", "content": completion.text},
        ]
    return messages


def _sentence_span_around(text: str, start: int, end: int) -> tuple[int, int]:
    """The `[left, right)` span of the sentence containing `text[start:end]`,
    found by looking for the nearest sentence boundary outside the match on
    each side -- never by splitting the whole text, so a period inside the
    match itself (a URL) is never mistaken for one."""
    left = 0
    for m in _SENTENCE_BOUNDARY.finditer(text, 0, start):
        left = m.end()
    boundary = _SENTENCE_BOUNDARY.search(text, end)
    right = boundary.start() if boundary else len(text)
    return left, right


def _citations_for(answer_text: str, chunks: list[Chunk]) -> list[CitationEvent]:
    """One `CitationEvent` per bare URL the answer cites, spanning the whole
    sentence it appears in. `SERVICE_SYSTEM_PROMPT` asks for a free-form
    source URL (rung 1's adopted prompt, `decisions/0014`), not a bracketed
    `[N]` marker (ablation #8, not adopted) -- so a citation here is
    literally the URL text the model wrote, resolved back to whichever
    retrieved chunk carries that `source_url`."""
    by_url: dict[str, Chunk] = {}
    for c in chunks:
        by_url.setdefault(c.source_url, c)  # first (highest-ranked) chunk wins a repeated URL

    events: list[CitationEvent] = []
    for match in _URL.finditer(answer_text):
        url = match.group().rstrip(_TRAILING_PUNCT)
        chunk = by_url.get(url)
        if chunk is None:
            continue  # cites a URL outside the retrieved set -- not a valid citation
        span = _sentence_span_around(answer_text, match.start(), match.end())
        events.append(CitationEvent(claim_span=span, source_url=url, chunk_id=chunk.chunk_id))
    return events


def _source_events(chunks: list[Chunk], *, staleness_days: int, now: date) -> list[SourceChunk]:
    return [
        SourceChunk(
            title=c.title, url=c.source_url, silo=list(c.silo), heading_path=list(c.heading_path),
            rerank_score=None,  # reranker stage off, decisions/0007
            last_verified=c.crawled_at.date().isoformat(),
            stale=(now - c.crawled_at.date()).days > staleness_days,
        )
        for c in chunks
    ]


def answer(
    question: str,
    history: Sequence[str] = (),
    *,
    pipeline: AnswerPipeline | None = None,
    staleness_days: int = DEFAULT_STALENESS_DAYS,
    now: date | None = None,
) -> Iterator[AnyEvent]:
    """`question`: the live user turn. `history`: prior user turns only,
    oldest first (`GoldQuestion.history`'s own shape) -- each is answered
    live against its own retrieval before this turn starts, exactly like the
    eval harness, rather than trusting a client-supplied transcript of what
    the assistant previously said. `staleness_days`/`now`: Task 26's
    `sources[].stale` policy and its reference date, overridable per call
    (a test passes a fixed `now`; a real caller never needs to).

    Every conversational input is a parameter: this function holds nothing
    between calls, so two requests carrying the same `history` are identical
    requests, and a restarted process loses no conversation it was trusted
    to remember (T28's first acceptance criterion).

    Yields, in contract order: one `sources`, then either one `refusal` or
    interleaved `token`/`citation` events, then always exactly one `done`.
    """
    now = now if now is not None else date.today()
    pipeline = pipeline or get_default_pipeline()
    e2e_start = time.perf_counter()

    # Task 28, step 5: rewrite the follow-up into a standalone query before
    # anything is retrieved. Runs ahead of `_run_prior_turns` because it
    # needs only the prior *user* turns (which arrived with the request),
    # not the regenerated assistant answers -- so a request whose rewrite
    # fails has not yet spent quota regenerating a conversation.
    retrieval_query = question
    rewritten_query: str | None = None
    reform_ms: float | None = None
    if pipeline.reformulator is not None:
        t0 = time.perf_counter()
        candidates = pipeline.reformulator.reform(question, history)
        reform_ms = (time.perf_counter() - t0) * 1000
        candidate = candidates[0] if candidates else question
        if candidate and candidate != question:
            retrieval_query = candidate
            # Reported only when it actually differs: echoing the question
            # back as its own "rewrite" would make every single-turn request
            # look rewritten and train a client to ignore the field.
            rewritten_query = candidate
        logger.info("rewritten_query=%r (from %r)", rewritten_query, question)

    history_messages = _run_prior_turns(pipeline, history)

    # Per-leg retrieval timing for `latency_ms`. Not routed through
    # `AnswerPipeline.search` (which times the whole fused search as one
    # number) because the wire contract wants embed/dense/bm25/literal/fuse
    # reported separately.
    t0 = time.perf_counter()
    # DenseIndex.search embeds the query internally with no seam to inject a
    # precomputed vector, so embedding is timed here as its own call -- a
    # deliberate, documented redundant local (free, non-metered) embedding
    # pass, not a second network/quota cost, purely to get an honest
    # per-stage split instead of folding embed time silently into `dense`.
    pipeline.embedder.embed([retrieval_query])
    embed_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    dense_hits = pipeline.dense.search(retrieval_query, CANDIDATE_K)
    dense_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    bm25_hits = pipeline.bm25.search(retrieval_query, CANDIDATE_K)
    bm25_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    literal_hits = pipeline.literal.search(retrieval_query, CANDIDATE_K)
    literal_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    fused = pipeline.fuser.fuse([dense_hits, bm25_hits, literal_hits], CANDIDATE_K)
    fuse_ms = (time.perf_counter() - t0) * 1000

    hits = [
        replace(h, chunk=pipeline.chunk_lookup.get(h.chunk_id)) if h.chunk is None else h for h in fused
    ][:K]
    found = [h for h in hits if h.chunk is not None]
    chunks = [h.chunk for h in found]

    # Task 27's threshold gate (decisions/0009): a local, free cross-encoder
    # pass over retrieval output alone, so it is evaluated before generation
    # and can skip the generation call entirely when it fires. This is the
    # same cross-encoder model decisions/0007 froze the *retrieval* reranker
    # stage off for -- it is not used to reorder anything here, only to
    # score, so `LatencyMs.rerank` (previously always `None`) now reports
    # this pass's wall time on every request.
    #
    # Scored against `retrieval_query`, not the raw `question`: the gate asks
    # whether the retrieved passages match the information need, and a bare
    # follow-up ("What about for international students?") under-specifies
    # that need badly enough to score low against passages that answer it
    # perfectly well. Caveat worth stating rather than burying: τ was
    # calibrated (decisions/0009) on standalone dev questions, which contain
    # no under-specified follow-ups at all, so neither choice here is a
    # validated one -- the rewrite is simply the closer match to the
    # distribution τ was fitted on.
    t0 = time.perf_counter()
    if chunks:
        threshold_score: float | None = raw_top(
            maxp_scores(pipeline.score_pairs, retrieval_query, [c.text for c in chunks])
        )
        threshold_fired = threshold_score < TAU
    else:
        threshold_score = None  # nothing retrieved -- no score to compute, refuse regardless
        threshold_fired = True
    rerank_ms = (time.perf_counter() - t0) * 1000

    # sources: emitted before generation is even requested, not merely
    # before the first token is yielded (T26's whole point) -- everything
    # above this line is retrieval/reranking; nothing below has started yet.
    # `gen_start` is set the instant control returns from this yield, so the
    # measured gap below covers the true "sources -> first token" window a
    # client itself observes, not just the model's own thinking time.
    yield SourcesEvent(
        chunks=_source_events(chunks, staleness_days=staleness_days, now=now),
        rewritten_query=rewritten_query,
    )
    gen_start = time.perf_counter()

    model_fired = False
    answer_text = ""
    raw_usage: dict = {}
    finish_reason = None
    visible: list[str] = []

    if threshold_fired:
        # Any-signal-wins, threshold first: refused before generation is
        # even requested, so this request spends no generation quota.
        generate_ttft_ms = 0.0
        generate_total_ms = 0.0
    else:
        prompt = build_user_prompt(question, chunks, passage_chars=None)
        ttft_s: float | None = None
        for event in pipeline.generator.generate(prompt, system=SERVICE_SYSTEM_PROMPT, history=history_messages):
            if event.type == "token":
                if ttft_s is None:
                    ttft_s = time.perf_counter() - gen_start
                visible.append(event.data["text"])
            elif event.type == "done":
                raw_usage = (event.data.get("usage") or {}).get("raw") or {}
                finish_reason = event.data.get("finish_reason")
        generate_total_ms = (time.perf_counter() - gen_start) * 1000
        generate_ttft_ms = (ttft_s if ttft_s is not None else time.perf_counter() - gen_start) * 1000
        answer_text = "".join(visible)
        model_fired = looks_like_a_refusal(answer_text)

        # Task 26: the measured gap this whole design exists to shrink,
        # logged regardless of outcome (refused or answered) -- not part of
        # the wire contract itself (a client already observes it as its own
        # sources/token frame timestamps), but the one place the server has
        # it for its own operational visibility.
        logger.info("sources_to_first_token_ms=%.1f", generate_ttft_ms)

    refused = threshold_fired or model_fired
    winner = "threshold" if threshold_fired else ("model" if model_fired else None)
    # Task 27's own acceptance criterion: every signal plus the resolved
    # winner, logged per request. `gate` is never computed -- see module
    # docstring -- so it is logged as a fixed `False`/`None`, not omitted,
    # so a reader of these logs never has to wonder whether it ran silently.
    logger.info(
        "refusal_signals threshold_score=%s threshold_fired=%s gate_fired=False model_fired=%s winner=%s",
        f"{threshold_score:.3f}" if threshold_score is not None else "None",
        threshold_fired, model_fired, winner,
    )

    if refused:
        yield RefusalEvent(reason=winner, **_office_fields(chunks))
    else:
        for token_text in visible:
            yield TokenEvent(text=token_text)
        for citation in _citations_for(answer_text, chunks):
            yield citation

    e2e_ms = (time.perf_counter() - e2e_start) * 1000
    server_ns = ServerNs(
        total=int((raw_usage.get("eval_duration") or 0) + (raw_usage.get("prompt_eval_duration") or 0)),
        prompt_eval=int(raw_usage.get("prompt_eval_duration") or 0),
        eval=int(raw_usage.get("eval_duration") or 0),
    )
    yield DoneEvent(
        latency_ms=LatencyMs(
            embed=embed_ms, dense=dense_ms, bm25=bm25_ms, literal=literal_ms, fuse=fuse_ms,
            reform=reform_ms, rerank=rerank_ms,
            generate_ttft=generate_ttft_ms, generate_total=generate_total_ms, e2e=e2e_ms,
        ),
        server_ns=server_ns,
        refused=refused,
    )
    # `finish_reason` is not part of the wire contract (T23 didn't name it);
    # kept as a local variable rather than discarded silently in case a
    # future task needs it, not surfaced to a client today.
    del finish_reason
