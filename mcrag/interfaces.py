"""The swappable seams.

One abstract base per pipeline stage that an ablation varies. The config names a
concrete class per seam; the runner instantiates it. Adding an ablation arm means
adding a class and a config value -- never a branch inside the runner.

Bases that currently have one implementation and no planned ablation are
deliberately absent. Extract the interface when the second implementation
arrives, not before.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator

from mcrag.types import Chunk, Document, Event, Hit, RawPage, Score


class Extractor(ABC):
    """RawPage -> Document. Chrome removal lives here."""

    @abstractmethod
    def extract(self, page: RawPage) -> Document | None:
        """Return None when nothing usable was extracted.

        None is a signal, not a failure: it drives the manifest's
        `extraction_empty` status, which exists because HTTP 200 with empty text
        is the extraction-regression signature.
        """


class Chunker(ABC):
    """Document -> chunks. Chunk size and overlap are config, not constants."""

    @abstractmethod
    def chunk(self, doc: Document) -> list[Chunk]: ...


class Retriever(ABC):
    """One retrieval leg. Dense, BM25 and literal all satisfy this."""

    name: str = "retriever"

    @abstractmethod
    def search(self, query: str, k: int) -> list[Hit]: ...


class Fuser(ABC):
    """Combine per-leg result lists into one ranked list."""

    @abstractmethod
    def fuse(self, leg_results: list[list[Hit]], k: int) -> list[Hit]: ...


class Reranker(ABC):
    """Reorder a candidate list. `IdentityReranker` is the 'off' arm."""

    @abstractmethod
    def rerank(self, query: str, hits: list[Hit], k: int) -> list[Hit]: ...


class Reformulator(ABC):
    """Query in, one or more queries out. Each rung of the ladder is a class."""

    @abstractmethod
    def reform(self, query: str, history: list[tuple[str, str]] | None = None) -> list[str]: ...


class Generator(ABC):
    """Prompt -> event stream. The cloud model, a stub, and a cached replay."""

    @abstractmethod
    def generate(self, prompt: str, **kwargs: object) -> Iterator[Event]: ...


class Scorer(ABC):
    """One tier of the generation scoring ladder."""

    tier: int = 0

    @abstractmethod
    def score(self, answer: str, gold: dict) -> Score: ...


class Indexer(ABC):
    """Build and update a retrieval index over chunks."""

    @abstractmethod
    def build(self, chunks: Iterable[Chunk]) -> None: ...

    @abstractmethod
    def delete_by_source_url(self, url: str) -> int:
        """Return the number of chunks removed. Incremental reindex needs this."""

    @abstractmethod
    def upsert(self, chunks: Iterable[Chunk]) -> None:
        """Add or replace chunks by `chunk_id`, without rebuilding the whole index.

        Incremental reindex (T10) is delete-by-source_url then upsert -- never a
        full `build()` -- so an unchanged corpus is a true no-op.
        """


class Embedder(ABC):
    """Text -> dense vectors. The only seam a dense index needs swapped out.

    No I/O in `__init__` -- a concrete embedder loads its model lazily, on
    first call to `embed`, so constructing one in a test doesn't require a
    network fetch or a GPU.
    """

    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...
