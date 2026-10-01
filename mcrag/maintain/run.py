"""Orchestrate a maintenance run: crawl, extract, reindex, then check for decay.

Exit codes:
- 0: chain completed and no alert fired (silence)
- 1: ingest chain failed (exception or non-zero return)
- 2: chain completed but one or more alerts fired

This module wires the ingestion chain (crawl, extract, reindex) and the alert
checks together. All real I/O happens here; the alert checks are pure functions
of a MaintenanceContext assembled once before checking.

To make verification possible (force a condition and assert it fires
independently), the ingest chain is injectable. Tests pass a stub; production
uses the default that calls the real scripts.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from mcrag.crawl.manifest import Manifest
from mcrag.eval.gold import load_gold_questions
from mcrag.extract.trafilatura_extractor import TrafilaturaExtractor
from mcrag.maintain.alerts import (
    Alert,
    CorpusShapeDriftCheck,
    ExtractionRegressionCheck,
    MaintenanceContext,
    StaleGoldCheck,
    VolumeAnomalyCheck,
)
from mcrag.maintain.log import append_maintenance_log


def _default_ingest_chain() -> dict[str, Any]:
    """Run the real crawl → extract → reindex chain.

    Returns:
        dict with "pages_fetched": number of pages fetched in this run
    """
    # Import here to avoid circular dependencies
    from mcrag.chunk.paragraph_chunker import ParagraphChunker
    from mcrag.chunk.tokenizer import HuggingFaceTokenCounter
    from mcrag.crawl.fetcher import CrawlPass, Fetcher, SnapshotStore
    from mcrag.crawl.ratelimit import RateLimiter
    from mcrag.crawl.robots import RobotsPolicy, build_user_agent
    from mcrag.crawl.sitemap import fetch_queue
    from mcrag.extract.boilerplate import BoilerplateFilter
    from mcrag.extract.pipeline import ExtractedCorpus, extract_all
    from mcrag.index_pipeline import incremental_reindex
    from mcrag.retrieval.bge_embedder import BgeEmbedder
    from mcrag.retrieval.bm25 import BM25Index
    from mcrag.retrieval.dense import DenseIndex
    from mcrag.retrieval.embedding_cache import EmbeddingCache
    from mcrag.retrieval.literal import LiteralIndex
    from mcrag.types import Document

    BASE = "https://www.maryvillecollege.edu"

    # Paths
    manifest_path = Path("corpus/manifest.jsonl")
    raw_path = Path("corpus/raw")
    extracted_path = Path("corpus/extracted/documents.jsonl")
    chunks_path = Path("corpus/chunks.jsonl")
    index_dir = Path("indexes")
    lock_path = index_dir / "corpus.lock"

    # --- Stage 1: Crawl ---
    user_agent = build_user_agent("MaryvilleCollegeRAG-maintenance", "0.1", "maintenance@example.edu")
    robots = RobotsPolicy.fetch(BASE, user_agent)
    limiter = RateLimiter(1.0)
    limiter.respect_crawl_delay(robots.crawl_delay())

    manifest = Manifest.load(manifest_path)
    queue = fetch_queue(manifest)
    state = CrawlPass(Path("corpus/.crawl_pass.json"))
    unvisited = [u for u in queue if not state.visited(u)]

    fetcher = Fetcher(user_agent, robots, limiter, SnapshotStore(raw_path))
    stats = fetcher.crawl(
        manifest,
        unvisited,
        pass_state=state,
        on_progress=None,
        close_pass=True,
    )
    manifest.save()
    fetcher.store.save_index()
    state.save()

    pages_fetched = stats["fetched"]

    # --- Stage 2: Extract ---
    manifest = Manifest.load(manifest_path)
    store = SnapshotStore(raw_path)

    documents, _ = extract_all(
        manifest,
        store,
        TrafilaturaExtractor(min_chars=200),
        ExtractedCorpus(extracted_path),
        BoilerplateFilter(min_chars=200),
    )

    # --- Stage 3: Chunk ---
    #
    # Re-chunked with the production `ParagraphChunker`, and `corpus/chunks.jsonl`
    # rewritten, which is the step the first implementation left out. It fed
    # `incremental_reindex` a chunker that replayed the *existing* chunks.jsonl --
    # the arrangement `scripts/build_indexes.py` uses, where it is right, because
    # that script rebuilds indexes from an already-canonical chunk set. Here it
    # inverted the job: `incremental_reindex` deletes the index rows for every
    # changed url and re-inserts `chunker.chunk(doc)`, so a page whose text had
    # changed got its fresh rows replaced by its pre-change ones, and a page
    # fetched for the first time chunked to `[]` and was dropped from the index
    # entirely. A maintenance pass that quietly reverts the corpus it just
    # crawled is worse than one that never runs.
    #
    # It also silently disarmed Alert 4: stale-gold compares each pin against
    # the content hash in chunks.jsonl, and nothing ever rewrote that file, so
    # no pin could ever go stale no matter what the college published.
    #
    # The chunker choice is `ParagraphChunker(HuggingFaceTokenCounter())`,
    # matching `scripts/chunk_corpus.py`. `FixedSizeChunker(512)` is the
    # baseline *ablation* arm, not production, and a maintenance job exists to
    # reproduce production.
    def load_documents(path: Path) -> list[Document]:
        docs = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                raw = json.loads(line)
                docs.append(
                    Document(
                        url=raw["url"],
                        title=raw.get("title", ""),
                        text=raw["text"],
                        content_hash=raw["content_hash"],
                        fetched_at=datetime.fromisoformat(raw["fetched_at"]),
                        breadcrumb=tuple(raw.get("breadcrumb") or ()),
                        silo=tuple(raw.get("silo") or ()),
                        catalog_year=raw.get("catalog_year"),
                        lastmod=raw.get("lastmod"),
                    )
                )
        return docs

    documents = load_documents(extracted_path)
    chunker = ParagraphChunker(HuggingFaceTokenCounter())

    chunks_written = 0
    tmp_chunks_path = chunks_path.with_suffix(".jsonl.partial")
    with tmp_chunks_path.open("w", encoding="utf-8") as f:
        for doc in documents:
            for chunk in chunker.chunk(doc):
                row = asdict(chunk)
                row["crawled_at"] = chunk.crawled_at.isoformat()
                f.write(json.dumps(row) + "\n")
                chunks_written += 1
    # Written aside and moved into place: a crash mid-write would otherwise
    # leave a truncated chunks.jsonl, and the next run's Alert 4 would read the
    # missing chunks as pages that had changed and report the whole gold set
    # stale. The corpus is the one artifact here that other tasks read.
    tmp_chunks_path.replace(chunks_path)

    # --- Stage 4: Reindex ---
    index_dir.mkdir(exist_ok=True)
    dense = DenseIndex(
        db_path=index_dir / "dense",
        embedder=BgeEmbedder(),
        cache=EmbeddingCache(index_dir / "embedding_cache.jsonl"),
        model_name="bge-small-en-v1.5",
    )
    bm25 = BM25Index()
    literal = LiteralIndex()

    # The same chunker instance, so the rows that reach the indexes are the
    # rows that reached chunks.jsonl. It re-chunks each changed document a
    # second time -- `incremental_reindex` only touches changed urls, while the
    # persisted file has to hold all of them -- which is cheap next to the
    # embedding pass it feeds.
    result = incremental_reindex(documents, [dense, bm25, literal], chunker, lock_path)

    return {
        "pages_fetched": pages_fetched,
        "chunks_written": chunks_written,
        "reindexed_urls": len(result.changed_urls),
        "deindexed_urls": len(result.removed_urls),
    }


def _fixture_url(expected_file: Path) -> str | None:
    """The URL a T6 fixture was pinned from, read from its `.meta.txt` sibling.

    Read rather than reconstructed. `scripts/pin_extraction_fixtures.py` names
    fixtures with `slug()`, which flattens the URL path with `__`
    (`/about/downtown-center/rentals/` -> `about__downtown-center__rentals`),
    and writes the real URL into `<name>.meta.txt` as a `url:` line. Rebuilding
    the URL from the filename instead was wrong for every multi-segment page --
    12 of the 17 pinned fixtures -- and wrong in the quiet direction: both the
    expected text and the snapshot lookup used the same bad key, so the lookup
    missed, the page counted as "not fetched", and Alert 1 reported stability
    over pages it had never once compared.

    Returns None when the meta file is missing or carries no `url:` line; the
    caller counts those rather than guessing.
    """
    meta_file = expected_file.with_name(
        expected_file.name.replace(".expected.txt", ".meta.txt")
    )
    if not meta_file.exists():
        return None
    for line in meta_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("url:"):
            url = line[len("url:") :].strip()
            return url or None
    return None


def _load_pinned_extractions(fixtures_dir: Path) -> tuple[dict[str, str], list[Path]]:
    """Load expected extractions from T6 pinned fixtures.

    Returns the URL -> expected-text map, and the fixtures whose URL could not
    be established -- returned rather than swallowed so the caller can say how
    many pinned pages dropped out before any comparison was attempted.
    """
    result: dict[str, str] = {}
    unresolved: list[Path] = []
    for expected_file in sorted(fixtures_dir.glob("*.expected.txt")):
        url = _fixture_url(expected_file)
        if url is None:
            unresolved.append(expected_file)
            continue
        result[url] = expected_file.read_text(encoding="utf-8").rstrip("\n")
    return result, unresolved


def _load_pinned_http_status_and_extractions(
    raw_store_path: Path, urls: Iterable[str]
) -> tuple[dict[str, int], dict[str, str]]:
    """Re-extract each pinned URL from this run's raw snapshot.

    Takes the URLs resolved by `_load_pinned_extractions` rather than
    re-deriving them from the fixture directory: one derivation, used by both
    sides of the comparison, so the two maps cannot silently disagree on a key.
    """
    from mcrag.crawl.fetcher import SnapshotStore

    store = SnapshotStore(raw_store_path)
    pinned_http_status: dict[str, int] = {}
    pinned_extractions: dict[str, str] = {}

    extractor = TrafilaturaExtractor()

    for url in urls:
        try:
            raw_page = store.load(url)
        except (FileNotFoundError, gzip.BadGzipFile, json.JSONDecodeError):
            # Snapshot absent or corrupt: this URL was not fetched this run.
            continue
        if not raw_page:
            continue
        pinned_http_status[url] = raw_page.http_status
        doc = extractor.extract(raw_page)
        pinned_extractions[url] = doc.text if doc else ""

    return pinned_http_status, pinned_extractions


def main(
    ingest_chain: Callable[[], dict[str, Any]] | None = None,
) -> int:
    """Run one maintenance cycle: crawl, extract, reindex, check for decay.

    Args:
        ingest_chain: optional callable that performs the crawl/extract/reindex
                      and returns {"pages_fetched": int}. Defaults to the real
                      chain if not provided.

    Returns:
        0 if the chain completed and no alert fired (silence)
        1 if the chain failed
        2 if the chain completed but one or more alerts fired
    """
    started_at = datetime.now(timezone.utc)
    run_id = started_at.isoformat()

    if ingest_chain is None:
        ingest_chain = _default_ingest_chain

    # Run the ingest chain
    try:
        chain_result = ingest_chain()
    except Exception as exc:
        finished_at = datetime.now(timezone.utc)
        append_maintenance_log(
            Path("data/maintenance/maintenance_log.jsonl"),
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=1,
            # `None`, not 0: the chain blew up, so how many pages it fetched
            # before dying is unknown. Writing 0 would put "fetched nothing"
            # in the log on the strength of nobody knowing -- and the row a
            # human reads after a 3 a.m. cron failure is the whole product here.
            pages_fetched=None,
            alerts=[],
            # The exception is the only diagnosis the row will ever carry: the
            # traceback dies with the process, and an exit-1 row that does not
            # say what broke sends the reader back to re-run it to find out.
            error=f"{type(exc).__name__}: {exc}",
        )
        return 1

    # Same rule: a chain that answered without the key did not report zero.
    pages_fetched = chain_result.get("pages_fetched")

    # Assemble MaintenanceContext
    fixtures_dir = Path("tests/fixtures/extraction")
    raw_store_path = Path("corpus/raw")

    # Load manifests
    previous_manifest_path = Path("corpus/.previous_manifest.jsonl")
    current_manifest = Manifest.load(Path("corpus/manifest.jsonl"))

    if previous_manifest_path.exists():
        previous_manifest = Manifest.load(previous_manifest_path)
        previous_records = list(previous_manifest.records.values())
    else:
        previous_records = []

    # Load expected extractions (from T6 fixtures), then re-extract exactly
    # those URLs from this run's snapshots.
    expected_extractions, unresolved = _load_pinned_extractions(fixtures_dir)
    for path in unresolved:
        print(f"pinned fixture has no resolvable url, not compared: {path.name}")
    pinned_http_status, pinned_extractions = _load_pinned_http_status_and_extractions(
        raw_store_path, expected_extractions
    )

    # Load gold questions and chunks (for Alert 4)
    gold_path = Path("data/gold/gold_v1.jsonl")
    chunks_path = Path("corpus/chunks.jsonl")

    gold_questions = []
    if gold_path.exists():
        gold_questions = load_gold_questions(gold_path)

    chunks = {}
    if chunks_path.exists():
        with chunks_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    chunk = json.loads(line)
                    chunks[chunk["chunk_id"]] = chunk

    context = MaintenanceContext(
        previous_manifest=previous_records,
        current_manifest=list(current_manifest.records.values()),
        pinned_extractions=pinned_extractions,
        expected_extractions=expected_extractions,
        pinned_http_status=pinned_http_status,
        gold_questions=gold_questions,
        chunks=chunks,
    )

    # Run all four alert checks
    checks = [
        ExtractionRegressionCheck(),
        CorpusShapeDriftCheck(),
        VolumeAnomalyCheck(),
        StaleGoldCheck(),
    ]

    alerts: list[Alert] = []
    any_fired = False
    for check in checks:
        alert = check.check(context)
        alerts.append(alert)
        if alert.fired:
            any_fired = True

    # Write the log
    finished_at = datetime.now(timezone.utc)
    exit_code = 2 if any_fired else 0
    append_maintenance_log(
        Path("data/maintenance/maintenance_log.jsonl"),
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        pages_fetched=pages_fetched,
        alerts=alerts,
    )

    # Advance the drift baseline only once the log row is durable, and by
    # building a second Manifest rather than repointing the loaded one's path:
    # rotating first would mean a crash between here and the log write loses
    # the comparison forever, since the next run would measure this run's
    # corpus against itself and find, correctly and uselessly, no drift.
    Manifest(path=previous_manifest_path, records=current_manifest.records).save()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
