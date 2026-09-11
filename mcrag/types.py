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
class GoldQuestion:
    """One hand-authored gold-set record (Task 12).

    `gold` holds heading/chunk-level refs, never bare page URLs (PLAN Phase 2)
    -- a page-level ref can't tell a correct retrieval from a lucky one.
    `expected_referral` is decision 0002's field: the office/contact/destination
    a correct answer or refusal should route to, where one applies. Empty for
    slices that don't reach a silo (e.g. most `out_of_scope` questions).
    """

    qid: str
    slice: str
    question: str
    gold: tuple[str, ...]
    conjunctive: bool
    notes: str = ""
    expected_referral: str | None = None
    split: str | None = None  # filled in by the splitter, absent before that


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
