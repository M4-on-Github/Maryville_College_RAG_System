"""Fetch the manifest's work queue politely, and store what comes back.

Two properties the rest of the pipeline depends on:

**Resumable.** The manifest is the checkpoint. A URL already marked ``fetched``
with its snapshot on disk is not fetched again, so an interrupted crawl restarts
where it stopped rather than from the beginning. At one request per second over
2,400 pages, restarting from the beginning is forty minutes of someone else's
bandwidth spent on nothing.

**Content-addressed.** A snapshot is stored under its own content hash, so
re-fetching an unchanged page writes no new file and the incremental reindex has
a cheap, reliable change signal. ``lastmod`` cannot serve that role on this site:
a 2017 news post carries a 2026 ``lastmod``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mcrag.crawl.manifest import Manifest
from mcrag.crawl.ratelimit import RateLimiter
from mcrag.crawl.robots import RobotsPolicy, require_identified

_CHARSET = re.compile(rb'charset=["\']?\s*([\w-]+)', re.I)


def content_hash(html: str) -> str:
    """Hash of the *normalized* body.

    Whitespace is collapsed before hashing. Without that, a template that emits
    a different amount of indentation on each render makes every page look
    changed on every crawl, and the incremental reindex becomes a full reindex.
    """
    collapsed = re.sub(r"\s+", " ", html)
    normalized = re.sub(r">\s+<", "><", collapsed).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    html: str
    hash: str
    from_cache: bool = False


class SnapshotStore:
    """Raw HTML on disk, addressed by content hash.

    Gzipped, because raw WordPress pages are 30-180 KB of mostly repeated
    template and compress to roughly a tenth of that. The index file maps a URL
    to the hash it currently resolves to.
    """

    def __init__(self, root: str | Path = "corpus/raw") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "index.json"
        self._index: dict[str, str] = {}
        if self._index_path.exists():
            self._index = json.loads(self._index_path.read_text(encoding="utf-8"))

    def _path_for(self, digest: str) -> Path:
        # Two-level fan-out: 2,400 files in one directory is slow to list on
        # Windows and unpleasant to inspect by hand.
        return self.root / digest[:2] / f"{digest}.html.gz"

    def has(self, digest: str) -> bool:
        return self._path_for(digest).exists()

    def put(self, url: str, html: str, digest: str) -> bool:
        """Store a snapshot. Returns False when the content was already held."""
        path = self._path_for(digest)
        already = path.exists()
        if not already:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(html.encode("utf-8")))
        self._index[url] = digest
        return not already

    def get(self, url: str) -> str | None:
        digest = self._index.get(url)
        if not digest:
            return None
        path = self._path_for(digest)
        return gzip.decompress(path.read_bytes()).decode("utf-8") if path.exists() else None

    def digest_for(self, url: str) -> str | None:
        return self._index.get(url)

    def save_index(self) -> None:
        self._index_path.write_text(
            json.dumps(self._index, sort_keys=True, indent=0), encoding="utf-8"
        )

    def __len__(self) -> int:
        return len(self._index)


class CrawlPass:
    """Which URLs the *current* pass has already visited.

    The manifest alone cannot answer this. A page marked ``fetched`` in March is
    done for that pass and due for a re-check in September, so "already fetched"
    and "already visited this pass" are different questions. Conflating them
    makes a crawl either unresumable or unable to ever re-crawl.

    A pass ends when the queue is exhausted; the next run then opens a new one.
    """

    def __init__(self, path: str | Path = "corpus/.crawl_pass.json") -> None:
        self.path = Path(path)
        self.started_at: str = datetime.now(timezone.utc).isoformat()
        self.done: set[str] = set()
        self.finished: bool = False
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not state.get("finished"):
                self.started_at = state["started_at"]
                self.done = set(state["done"])

    def visited(self, url: str) -> bool:
        return url in self.done

    def mark(self, url: str) -> None:
        self.done.add(url)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "started_at": self.started_at,
                    "finished": self.finished,
                    "done": sorted(self.done),
                }
            ),
            encoding="utf-8",
        )

    def finish(self) -> None:
        self.finished = True
        self.save()


class Fetcher:
    """Rate-limited, robots-checked, resumable HTTP fetching."""

    def __init__(
        self,
        user_agent: str,
        robots: RobotsPolicy,
        limiter: RateLimiter,
        store: SnapshotStore,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.user_agent = require_identified(user_agent)
        self.robots = robots
        self.limiter = limiter
        self.store = store
        self.timeout = timeout
        self.max_retries = max_retries

    def fetch_one(self, url: str) -> FetchResult:
        """Fetch a single URL, retrying transient failures only.

        A 404 is not retried: the page is gone and asking twice more just
        wastes the site's time. A 5xx or a timeout is retried, because those
        are the failures that resolve on their own.
        """
        decision = self.robots.decide(url, self.user_agent)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self.limiter.acquire()
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Encoding": "gzip",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    charset = _CHARSET.search(body[:4096])
                    encoding = (
                        charset.group(1).decode("ascii", "replace") if charset else "utf-8"
                    )
                    try:
                        html = body.decode(encoding, "replace")
                    except LookupError:
                        html = body.decode("utf-8", "replace")
                    final_url = response.geturl()

                # A redirect can land somewhere robots forbids. The check on the
                # requested URL does not cover where we actually ended up.
                if final_url != url:
                    landing = self.robots.decide(final_url, self.user_agent)
                    if not landing.allowed:
                        raise PermissionError(landing.reason)

                return FetchResult(
                    url=url,
                    final_url=final_url,
                    status=response.status,
                    html=html,
                    hash=content_hash(html),
                )
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    raise  # 404 and friends are final answers
                last_error = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
            if attempt < self.max_retries:
                self.limiter.acquire()  # back off by one more interval

        raise last_error or RuntimeError(f"{url}: exhausted retries")

    # ---- the crawl pass -------------------------------------------------

    def crawl(
        self,
        manifest: Manifest,
        urls: list[str],
        pass_state: CrawlPass | None = None,
        save_every: int = 25,
        on_progress=None,
        close_pass: bool = True,
    ) -> dict[str, int]:
        """Fetch each URL, checkpointing after every ``save_every`` of them.

        A single 404 does not abort the run. Failing a whole crawl because one
        page was retired would mean never completing one.
        """
        stats = {
            "fetched": 0,
            "unchanged": 0,
            "failed": 0,
            "forbidden": 0,
            "new_snapshots": 0,
            "resumed": 0,
        }
        state = pass_state or CrawlPass()

        for i, url in enumerate(urls, start=1):
            if state.visited(url):
                stats["resumed"] += 1
                continue

            try:
                result = self.fetch_one(url)
            except PermissionError as exc:
                manifest.mark_excluded(url, str(exc))
                state.mark(url)
                stats["forbidden"] += 1
                continue
            except urllib.error.HTTPError as exc:
                manifest.mark_failed(url, http=exc.code, attempts=1)
                # A 4xx is a settled answer, so the pass is done with it. A 5xx
                # that survived every retry is still the server having a bad
                # day, and the next pass should ask again.
                if exc.code < 500:
                    state.mark(url)
                stats["failed"] += 1
                continue
            except Exception:
                # A URL that failed for a transient reason is *not* marked done
                # for this pass, so a rerun retries it while leaving the pages
                # that already succeeded alone.
                manifest.mark_failed(url, http=None, attempts=self.max_retries)
                stats["failed"] += 1
                continue

            previous = self.store.digest_for(url)
            is_new = self.store.put(url, result.html, result.hash)
            stats["new_snapshots"] += int(is_new)

            # The record says ``fetched`` whether or not the bytes changed: the
            # status answers "do we hold this page", and we do. Whether it
            # changed is what the content hash is for, and re-crawling a stable
            # site must not empty out the fetched count in the coverage report.
            manifest.mark_fetched(
                url,
                http=result.status,
                content_hash=result.hash,
                bytes_len=len(result.html.encode("utf-8")),
                final_url=result.final_url if result.final_url != url else None,
                fetched_at=datetime.now(timezone.utc),
            )
            stats["unchanged" if previous == result.hash else "fetched"] += 1

            state.mark(url)
            if i % save_every == 0:
                manifest.save()
                self.store.save_index()
                state.save()
            if on_progress:
                on_progress(i, len(urls), url, stats)

        manifest.save()
        self.store.save_index()
        # Only a run that drained the whole queue closes the pass. A partial
        # run -- a rehearsal with --limit, say -- leaves it open, so the next
        # run continues it instead of re-fetching what was just fetched.
        state.finish() if close_pass else state.save()
        return stats
