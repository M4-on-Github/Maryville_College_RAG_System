"""Value objects passed between pipeline stages.

Every type here is a frozen dataclass. Nothing downstream mutates what it was
handed: a `Reranker` that reorders hits returns a new list, it does not rewrite
the `Hit` objects a `Retriever` produced. This is what makes an ablation a
substitution rather than an archaeology problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# --------------------------------------------------------------------------
# Corpus side
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawPage:
    """Bytes as fetched, before any extraction. The snapshot store's unit."""

    url: str
    http_status: int
    content_hash: str
    fetched_at: datetime
    html: str
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def bytes_len(self) -> int:
        return len(self.html.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class Document:
    """Main content extracted from a RawPage, chrome removed."""

    url: str
    title: str
    text: str
    content_hash: str
    fetched_at: datetime
    breadcrumb: tuple[str, ...] = ()
    silo: tuple[str, ...] = ()
    catalog_year: str | None = None
    lastmod: str | None = None  # recorded, never trusted -- see PLAN 1

    @property
    def char_len(self) -> int:
        return len(self.text)


@dataclass(frozen=True, slots=True)
class Chunk:
    """The unit of retrieval. Metadata is stamped here and never re-derived."""

    chunk_id: str
    source_url: str
    title: str
    text: str
    heading_path: tuple[str, ...]
    breadcrumb: tuple[str, ...]
    silo: tuple[str, ...]
    content_hash: str
    crawled_at: datetime
    token_count: int
    catalog_year: str | None = None


# --------------------------------------------------------------------------
# Query side
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hit:
    """One retrieved chunk with the score that retrieved it.

    `leg` names which retriever produced it, so fusion can weight by source and
    per-leg recall stays measurable after fusion has run.
    """

    chunk_id: str
    score: float
    leg: str
    rank: int
    chunk: Chunk | None = None

    def with_score(self, score: float, leg: str | None = None) -> Hit:
        """Return a copy carrying a new score. Fusion and reranking use this."""
        from dataclasses import replace

        return replace(self, score=score, leg=leg or self.leg)


@dataclass(frozen=True, slots=True)
class Pin:
    """Content-hash pin for a gold reference (Task 35).

    Records the hash of the page a gold reference was read from, along with
    how that pin was established. This lets the eval detect when a page has
    changed since the gold answer was authored or last re-verified.

    `origin` is one of:
    - "authored": the pin was established at authoring time (rare; pre-existing pins)
    - "backfill": resolved from the current corpus (most pins initially)
    - "reverified": re-established by a human re-read and re-verification

    The origin matters for accountability: a pin asserts "this is what the page
    looks like [as of when the origin says]", not "this is what the author read
    at authoring time" unless origin is "authored".
    """

    gold_ref: str  # chunk ID like "6f879be008729f80-5"
    content_hash: str  # sha256 of page the chunk came from
    origin: str  # "authored" | "backfill" | "reverified"


@dataclass(frozen=True, slots=True)
class GoldQuestion:
    """One hand-authored gold-set record (Task 12).

    `gold` holds heading/chunk-level refs, never bare page URLs (PLAN Phase 2)
    -- a page-level ref can't tell a correct retrieval from a lucky one.
    `expected_referral` is decision 0002's field: the office/contact/destination
    a correct answer or refusal should route to, where one applies. Empty for
    slices that don't reach a silo (e.g. most `out_of_scope` questions).

    `provenance` is decision 0004's field: `"synthetic"` for a question drafted
    from the corpus (v1 of this gold set, in the absence of real user queries),
    `"real"` for one promoted from a logged, human-reviewed real query. Lets
    eval reports split synthetic-set performance from real-traffic performance
    once the latter exists, instead of silently mixing the two.

    `history` holds prior user turns for the `multi_turn` slice only -- the
    de-contextualization test needs `question` to be an under-specified
    follow-up ("what about for international students?") that only resolves
    against `history`. Assistant turns are not scripted here: the pipeline
    generates its own prior answers live during eval, so scripting them would
    test the pipeline against canned text it never produced. Empty for every
    other slice.

    `pins` carries content-hash pins for each gold ref (Task 35). Maps each
    ref to the hash of the page it was read from, along with how that pin was
    established (authored/backfill/reverified). Absent or empty before Task 35;
    progressively filled by backfill and re-verification. A pin exists when the
    gold ref is not out-of-scope and the ref's chunk was successfully resolved.
    """

    qid: str
    slice: str
    question: str
    gold: tuple[str, ...]
    conjunctive: bool
    notes: str = ""
    expected_referral: str | None = None
    split: str | None = None  # filled in by the splitter, absent before that
    provenance: str = "synthetic"
    history: tuple[str, ...] = ()
    pins: tuple[Pin, ...] = ()


@dataclass(frozen=True, slots=True)
class Score:
    """A graded judgement of one answer against one gold record.

    `value` is the headline number; `components` carries the sub-scores so a
    scoring-ladder tier can be audited rather than trusted.
    """

    metric: str
    value: float
    tier: int
    components: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Event:
    """One item on the answer stream (PLAN Phase 5).

    The wire contract is versioned; this is its in-process form. `type` is one
    of: sources, token, citation, refusal, done.
    """

    type: str
    data: dict[str, Any]
    schema_version: str = "v1"

    _TYPES = ("sources", "token", "citation", "refusal", "done")

    def __post_init__(self) -> None:
        if self.type not in self._TYPES:
            raise ValueError(f"unknown event type {self.type!r}; expected one of {self._TYPES}")
