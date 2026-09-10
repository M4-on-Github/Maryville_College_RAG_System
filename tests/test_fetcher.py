"""Fetcher and snapshot-store tests.

Everything here runs against a local ``http.server`` on a loopback port. No test
in this file touches maryvillecollege.edu: a test suite that hits a live
institutional site is one CI misconfiguration away from being a load generator.
"""

from __future__ import annotations

import gzip
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mcrag.crawl.fetcher import CrawlPass, Fetcher, SnapshotStore, content_hash
from mcrag.crawl.manifest import Manifest, Status
from mcrag.crawl.ratelimit import RateLimiter
from mcrag.crawl.robots import RobotsPolicy

UA = "MaryvilleCollegeRAG/0.1 (+test@example.edu)"

ROBOTS = """
User-agent: *
Disallow: /private/
"""


class _Handler(BaseHTTPRequestHandler):
    pages: dict[str, tuple[int, str]] = {}
    hits: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).hits.append(self.path)
        if self.path == "/robots.txt":
            body = ROBOTS.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/redirect/"):
            self.send_response(301)
            self.send_header("Location", self.path.replace("/redirect/", "/page/"))
            self.end_headers()
            return
        status, html = type(self).pages.get(self.path, (404, "<h1>gone</h1>"))
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep pytest output readable
        pass


@pytest.fixture
def site():
    _Handler.pages = {
        "/page/a": (200, "<html><body><h1>Alpha</h1><p>one</p></body></html>"),
        "/page/b": (200, "<html><body><h1>Beta</h1><p>two</p></body></html>"),
        "/page/c": (200, "<html><body><h1>Gamma</h1><p>three</p></body></html>"),
        "/boom": (500, "<html>server error</html>"),
        "/private/secret": (200, "<html>should never be fetched</html>"),
    }
    _Handler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()
    server.server_close()


def build(tmp_path, base, rps: float = 1000.0) -> tuple[Fetcher, Manifest]:
    robots = RobotsPolicy(ROBOTS, user_agent=UA)
    fetcher = Fetcher(
        user_agent=UA,
        robots=robots,
        limiter=RateLimiter(rps),
        store=SnapshotStore(tmp_path / "raw"),
    )
    return fetcher, Manifest(path=tmp_path / "manifest.jsonl")


def queue(manifest: Manifest, base: str, paths: list[str]) -> list[str]:
    urls = [base + p for p in paths]
    for url in urls:
        manifest.consider(url, source="posts-page")
    return urls


# ---- content hashing ---------------------------------------------------


def test_hash_ignores_whitespace_reflow():
    a = "<html>  <p>hello</p>\n</html>"
    b = "<html><p>hello</p>    </html>"
    assert content_hash(a) == content_hash(b)


def test_hash_changes_with_content():
    assert content_hash("<p>a</p>") != content_hash("<p>b</p>")


# ---- snapshot store ----------------------------------------------------


def test_store_round_trips(tmp_path):
    store = SnapshotStore(tmp_path)
    html = "<html><body>hi</body></html>"
    assert store.put("http://x/1", html, content_hash(html)) is True
    assert store.get("http://x/1") == html


def test_store_deduplicates_identical_content(tmp_path):
    store = SnapshotStore(tmp_path)
    html = "<html>same</html>"
    digest = content_hash(html)
    assert store.put("http://x/1", html, digest) is True
    assert store.put("http://x/2", html, digest) is False  # no second file
    assert len(list(tmp_path.rglob("*.html.gz"))) == 1


def test_store_index_survives_reopen(tmp_path):
    store = SnapshotStore(tmp_path)
    html = "<html>persisted</html>"
    store.put("http://x/1", html, content_hash(html))
    store.save_index()
    assert SnapshotStore(tmp_path).get("http://x/1") == html


def test_store_is_gzipped_on_disk(tmp_path):
    store = SnapshotStore(tmp_path)
    html = "<html>" + "padding " * 500 + "</html>"
    store.put("http://x/1", html, content_hash(html))
    path = next(tmp_path.rglob("*.html.gz"))
    assert gzip.decompress(path.read_bytes()).decode() == html
    assert path.stat().st_size < len(html) / 2


# ---- fetching ----------------------------------------------------------


def test_fetches_and_records(tmp_path, site):
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/page/a", "/page/b"])
    stats = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))

    assert stats["fetched"] == 2
    assert stats["new_snapshots"] == 2
    for url in urls:
        record = manifest.records[url]
        assert record.status == Status.FETCHED
        assert record.http == 200
        assert record.content_hash and record.bytes


def test_404_does_not_abort_the_run(tmp_path, site):
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/page/a", "/missing", "/page/b"])
    stats = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))

    assert stats["fetched"] == 2
    assert stats["failed"] == 1
    assert manifest.records[site + "/missing"].status == Status.FAILED
    assert manifest.records[site + "/missing"].http == 404


def test_404_is_not_retried(tmp_path, site):
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/missing"])
    fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    assert _Handler.hits.count("/missing") == 1


def test_5xx_is_retried_then_recorded_as_failed(tmp_path, site):
    fetcher, manifest = build(tmp_path, site)
    fetcher.max_retries = 3
    urls = queue(manifest, site, ["/boom"])
    stats = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    assert stats["failed"] == 1
    assert _Handler.hits.count("/boom") == 3


def test_robots_forbidden_url_is_never_requested(tmp_path, site):
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/private/secret"])
    stats = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))

    assert stats["forbidden"] == 1
    assert "/private/secret" not in _Handler.hits
    record = manifest.records[urls[0]]
    assert record.reason_class == "robots_disallow"


def test_redirect_records_both_urls(tmp_path, site):
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/redirect/a"])
    fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    record = manifest.records[urls[0]]
    assert record.url.endswith("/redirect/a")
    assert record.final_url.endswith("/page/a")
    assert record.canonical_url == record.final_url


def test_rate_limit_is_applied(tmp_path, site):
    """Two requests at 4/s cannot complete in under one interval."""
    import time

    fetcher, manifest = build(tmp_path, site, rps=4.0)
    urls = queue(manifest, site, ["/page/a", "/page/b", "/page/c"])
    start = time.monotonic()
    fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    assert time.monotonic() - start >= 0.5  # two waits of 0.25s at minimum


# ---- the acceptance criteria -------------------------------------------


def test_second_full_run_writes_no_new_snapshots(tmp_path, site):
    """Task 5 verification: two consecutive full runs, ~0 new snapshots."""
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/page/a", "/page/b", "/page/c"])

    first = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    assert first["new_snapshots"] == 3

    second = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    assert second["new_snapshots"] == 0
    assert second["unchanged"] == 3
    assert second["fetched"] == 0


def test_changed_page_writes_a_new_snapshot(tmp_path, site):
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/page/a"])
    fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    before = manifest.records[urls[0]].content_hash

    _Handler.pages["/page/a"] = (200, "<html><body><h1>Alpha</h1><p>rewritten</p></body></html>")
    stats = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))

    assert stats["new_snapshots"] == 1
    assert stats["fetched"] == 1
    assert manifest.records[urls[0]].content_hash != before


def test_interrupted_run_resumes_without_refetching(tmp_path, site):
    """Kill a pass halfway; the restart requests only what is left."""
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/page/a", "/page/b", "/page/c"])

    state = CrawlPass(tmp_path / "pass.json")
    with pytest.raises(RuntimeError):
        def die(i, total, url, stats):
            if i == 2:
                state.save()
                raise RuntimeError("interrupted")

        fetcher.crawl(manifest, urls, pass_state=state, save_every=1, on_progress=die)

    assert _Handler.hits.count("/page/a") == 1
    _Handler.hits = []

    resumed = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    assert resumed["resumed"] == 2  # a and b were already done
    assert _Handler.hits.count("/page/a") == 0
    assert _Handler.hits.count("/page/c") == 1


def test_finished_pass_starts_a_fresh_one(tmp_path, site):
    """A completed pass must not block the next re-crawl."""
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/page/a"])
    fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))

    reopened = CrawlPass(tmp_path / "pass.json")
    assert reopened.done == set()  # finished pass -> clean slate
    stats = fetcher.crawl(manifest, urls, pass_state=reopened)
    assert stats["resumed"] == 0
    assert stats["unchanged"] == 1


def test_partial_run_leaves_the_pass_open(tmp_path, site):
    """A rehearsal over part of the queue must not look like a finished pass."""
    fetcher, manifest = build(tmp_path, site)
    urls = queue(manifest, site, ["/page/a", "/page/b", "/page/c"])

    fetcher.crawl(
        manifest, urls[:1], pass_state=CrawlPass(tmp_path / "pass.json"), close_pass=False
    )
    _Handler.hits = []

    stats = fetcher.crawl(manifest, urls, pass_state=CrawlPass(tmp_path / "pass.json"))
    assert stats["resumed"] == 1
    assert _Handler.hits.count("/page/a") == 0


def test_failed_url_is_retried_on_the_next_pass(tmp_path, site):
    """A transient failure must not be mistaken for completed work."""
    fetcher, manifest = build(tmp_path, site)
    fetcher.max_retries = 1
    urls = queue(manifest, site, ["/boom"])
    state = CrawlPass(tmp_path / "pass.json")
    fetcher.crawl(manifest, urls, pass_state=state)
    assert not state.visited(urls[0])
