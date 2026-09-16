"""Generator tests against a local stub of the OpenAI-compatible endpoint.

Nothing here touches Ollama Cloud. Generation is the metered stage, and a test
suite that spends quota is a test suite people stop running -- besides which a
run whose cost depends on how often CI fires is not a run you can budget.

The stub speaks the same wire shape the real endpoint does: `data:` lines, a
usage block on the last chunk, `[DONE]` to close.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mcrag.eval.stats import bootstrap_ci
from mcrag.generate.ollama_cloud import (
    ContextOverflow,
    GenerationError,
    OllamaCloudGenerator,
    ReasoningSplitter,
)
from mcrag.generate.tokens import TokenEstimator

# What the stub will send back, set per test.
SCRIPT: dict[str, object] = {}


class StubHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's spelling
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        SCRIPT.setdefault("requests", []).append(payload)  # type: ignore[union-attr]

        status = SCRIPT.get("status", 200)
        if status >= 400:
            body = json.dumps({"error": SCRIPT.get("error", "nope")}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in SCRIPT.get("chunks", []):  # type: ignore[union-attr]
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def endpoint():
    SCRIPT.clear()
    SCRIPT["requests"] = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


def delta(content: str = "", reasoning: str = "", finish: str | None = None) -> dict:
    piece: dict[str, object] = {}
    if content:
        piece["content"] = content
    if reasoning:
        piece["reasoning"] = reasoning
    return {"choices": [{"delta": piece, "finish_reason": finish}]}


def generator(endpoint: str, **kwargs) -> OllamaCloudGenerator:
    kwargs.setdefault("num_ctx", 8192)
    kwargs.setdefault("max_tokens", 256)
    return OllamaCloudGenerator(
        model="stub-model", base_url=endpoint, api_key="test-key", **kwargs
    )


# ---- the context guard --------------------------------------------------


def test_oversized_prompt_raises_instead_of_being_sent(endpoint):
    gen = generator(endpoint, num_ctx=2048, max_tokens=512)
    with pytest.raises(ContextOverflow):
        list(gen.generate("word " * 20000))
    assert SCRIPT["requests"] == [], "the prompt was sent despite not fitting"


def test_budget_reserves_room_for_the_reply(endpoint):
    gen = generator(endpoint, num_ctx=4096, max_tokens=1024, reserve_tokens=64)
    assert gen.prompt_budget == 4096 - 1024 - 64


def test_a_window_too_small_to_answer_in_is_refused(endpoint):
    gen = generator(endpoint, num_ctx=512, max_tokens=1024)
    with pytest.raises(ValueError, match="no room"):
        gen.prompt_budget


def test_the_guard_can_be_stood_down_for_the_calibration_probe(endpoint):
    """Only the truncation probe sets this, and it must actually send."""
    SCRIPT["chunks"] = [delta(content="ok", finish="stop")]
    gen = generator(endpoint, num_ctx=2048, max_tokens=512, enforce_context=False)
    assert gen.complete("word " * 20000).text == "ok"
    assert len(SCRIPT["requests"]) == 1


class _FakeStreamResponse:
    """A response whose `.encoding` starts unset, like the real Content-Type:
    text/event-stream header (no charset param) -- `requests`' own guess for
    that is Latin-1, not UTF-8, which is the mojibake this class exists to
    reproduce deterministically instead of trusting a live guess to fail."""

    def __init__(self, lines: list[bytes]) -> None:
        self.status_code = 200
        self.encoding: str | None = None
        self._lines = lines

    def iter_lines(self, decode_unicode: bool = False):
        for raw in self._lines:
            yield raw.decode(self.encoding or "ISO-8859-1") if decode_unicode else raw


class _FakeSession:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    def post(self, *args, **kwargs):
        return self._response


def test_multibyte_answer_text_survives_the_stream_intact():
    """`text/event-stream` carries no charset, and `requests`' own guess for
    that is Latin-1, not UTF-8 -- silently mojibake-ing every curly quote,
    en-dash and non-breaking space the model emits. A live server's charset
    guess can vary by payload, so this pins `.encoding` directly rather than
    trusting a real request to reproduce the wrong guess reliably."""
    text = "Maryville College’s café is open. "
    # ensure_ascii=False, matching a real server: raw UTF-8 multi-byte bytes on
    # the wire, not \uXXXX escapes -- json.dumps's default escaping would keep
    # every byte in ASCII and mask the wrong-decode bug entirely.
    chunk = json.dumps(delta(content=text), ensure_ascii=False).encode("utf-8")
    done = json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode("utf-8")
    lines = [b"data: " + chunk, b"data: " + done, b"data: [DONE]"]
    fake_response = _FakeStreamResponse(lines)
    gen = OllamaCloudGenerator(
        model="stub-model",
        base_url="http://fake",
        api_key="test-key",
        num_ctx=8192,
        max_tokens=256,
        session=_FakeSession(fake_response),
    )
    assert gen.complete("hi").text == text


# ---- reasoning separation -----------------------------------------------


def test_reasoning_delta_never_reaches_the_answer(endpoint):
    SCRIPT["chunks"] = [
        delta(reasoning="the user wants a phone number"),
        delta(content="Call 865-981-8000."),
        delta(finish="stop"),
    ]
    gen = generator(endpoint)
    events = list(gen.generate("who do I call?"))
    tokens = [e.data["text"] for e in events if e.type == "token"]
    done = next(e for e in events if e.type == "done")
    assert "".join(tokens) == "Call 865-981-8000."
    assert done.data["reasoning"] == "the user wants a phone number"
    assert "wants a phone number" not in "".join(tokens)


def test_inline_think_tags_are_stripped(endpoint):
    SCRIPT["chunks"] = [
        delta(content="<think>hmm</think>The answer is 12."),
        delta(finish="stop"),
    ]
    completion = generator(endpoint).complete("how many?")
    assert completion.text == "The answer is 12."
    assert completion.reasoning == "hmm"


def test_a_marker_split_across_chunks_still_never_leaks():
    """The stream decides where chunks break, not us."""
    splitter = ReasoningSplitter()
    visible = ""
    reasoning = ""
    for piece in ["Answer: ", "<thi", "nk>secret plan", "</thin", "k>done."]:
        shown, thought = splitter.feed(piece)
        visible += shown
        reasoning += thought
    shown, thought = splitter.flush()
    assert visible + shown == "Answer: done."
    assert reasoning + thought == "secret plan"


def test_unterminated_reasoning_is_reasoning_not_answer():
    """A stream cut off mid-thought must not publish the thought as an answer."""
    splitter = ReasoningSplitter()
    shown, thought = splitter.feed("<think>still working")
    tail_shown, tail_thought = splitter.flush()
    assert shown + tail_shown == ""
    assert thought + tail_thought == "still working"


# ---- usage and timing ---------------------------------------------------


def test_server_token_counts_win_over_our_estimate(endpoint):
    SCRIPT["chunks"] = [
        delta(content="hello", finish="stop"),
        {"choices": [], "usage": {"prompt_tokens": 4321, "completion_tokens": 7}},
    ]
    usage = generator(endpoint).complete("hi").usage
    assert usage.prompt_tokens == 4321
    assert usage.completion_tokens == 7


def test_usage_is_requested_on_the_stream(endpoint):
    """Without stream_options the endpoint sends no usage block at all."""
    SCRIPT["chunks"] = [delta(content="hi", finish="stop")]
    generator(endpoint).complete("hi")
    assert SCRIPT["requests"][0]["stream_options"] == {"include_usage": True}


def test_num_ctx_is_stated_explicitly_in_every_request(endpoint):
    """Left unsent, the server picks its own window and truncates into it."""
    SCRIPT["chunks"] = [delta(content="hi", finish="stop")]
    generator(endpoint, num_ctx=8192).complete("hi")
    assert SCRIPT["requests"][0]["options"]["num_ctx"] == 8192


def test_client_wall_clock_is_the_fallback_and_says_so(endpoint):
    SCRIPT["chunks"] = [delta(content="hi", finish="stop")]
    usage = generator(endpoint).complete("hi").usage
    assert usage.timing_source == "client"
    assert usage.server_s is None
    assert usage.wall_s > 0
    assert usage.seconds == usage.wall_s


def test_server_durations_are_used_when_offered(endpoint):
    SCRIPT["chunks"] = [
        delta(content="hi", finish="stop"),
        {"choices": [], "eval_duration": 2_000_000_000, "prompt_eval_duration": 500_000_000},
    ]
    usage = generator(endpoint).complete("hi").usage
    assert usage.timing_source == "server"
    assert usage.seconds == pytest.approx(2.5)


def test_provider_error_body_survives(endpoint):
    SCRIPT["status"] = 429
    SCRIPT["error"] = "rate limit exceeded"
    with pytest.raises(GenerationError, match="rate limit exceeded"):
        generator(endpoint).complete("hi")


def test_a_torn_stream_chunk_is_an_error_not_a_silent_short_answer(endpoint):
    """Half an answer returned as a whole one is worse than a failure."""

    class TornHandler(StubHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices": [{"delta"\n\n')
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), TornHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        gen = generator(f"http://127.0.0.1:{server.server_address[1]}/v1")
        with pytest.raises(GenerationError, match="unparseable"):
            gen.complete("hi")
    finally:
        server.shutdown()
        server.server_close()


def test_no_key_is_read_until_a_call_is_made(monkeypatch, tmp_path):
    """Config loading and the test suite must work on a machine with no key."""
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here to fall back on
    gen = OllamaCloudGenerator(model="stub-model", base_url="http://127.0.0.1:1/v1")
    with pytest.raises(RuntimeError, match="OLLAMA_API_KEY"):
        gen.resolve_api_key()


def test_an_explicit_key_beats_the_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "from-environment")
    gen = OllamaCloudGenerator(
        model="stub-model", base_url="http://127.0.0.1:1/v1", api_key="explicit"
    )
    assert gen.resolve_api_key() == "explicit"


# ---- the token estimator ------------------------------------------------


def test_estimate_includes_the_chat_template_overhead():
    estimator = TokenEstimator(chars_per_token=4.0, overhead_tokens=70)
    assert estimator.estimate("") == 70
    assert estimator.estimate("x" * 400) == 171


def test_calibration_over_counts_every_sample_it_was_fitted_on():
    """The fitted line must sit above the data, not through it."""
    samples = [("x" * chars, 60 + chars // 4) for chars in (200, 900, 2400, 5000)]
    fitted = TokenEstimator.calibrate(samples)
    assert all(fitted.estimate(text) >= tokens for text, tokens in samples)


def test_calibration_ignores_a_single_dense_pair():
    """Two near-identical lengths must not set the ratio for the whole run."""
    honest = [("x" * chars, 60 + chars // 4) for chars in (200, 900, 2400, 5000)]
    noisy = [*honest, ("x" * 901, 60 + 900 // 4 + 40)]
    assert TokenEstimator.calibrate(noisy).chars_per_token > 2.0


def test_calibration_refuses_to_fit_one_point():
    single = TokenEstimator.calibrate([("x" * 100, 40)])
    assert single == TokenEstimator()


# ---- interval reporting -------------------------------------------------


def test_every_statistic_carries_its_n_and_interval():
    interval = bootstrap_ci([1.0, 2.0, 3.0, 4.0, 9.0])
    assert set(interval.to_dict()) >= {"value", "ci_low", "ci_high", "n"}
    assert interval.n == 5
    assert interval.ci_low <= interval.value <= interval.ci_high


def test_the_interval_is_the_same_every_time():
    values = [1.0, 4.0, 2.0, 8.0, 3.0, 5.0]
    assert bootstrap_ci(values, seed=7) == bootstrap_ci(values, seed=7)
    assert bootstrap_ci(values, seed=7) != bootstrap_ci(values, seed=8)


def test_a_single_observation_reports_rather_than_raises():
    interval = bootstrap_ci([4.2])
    assert (interval.value, interval.ci_low, interval.ci_high, interval.n) == (4.2, 4.2, 4.2, 1)


def test_an_empty_sample_has_nothing_to_report():
    with pytest.raises(ValueError):
        bootstrap_ci([])
