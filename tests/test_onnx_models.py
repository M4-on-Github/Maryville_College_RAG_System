"""The ONNX opt-in: environment switch and the one-at-a-time release.

The int8 numerics are measured against torch by hand (see docs/deploy.md); these
tests cover only the behavior that needs no model files.
"""

from pathlib import Path

from mcrag.retrieval import onnx_models
from mcrag.retrieval.onnx_models import ENV_VAR, ONE_AT_A_TIME_VAR, _Session, onnx_dir


def test_onnx_is_opt_in(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert onnx_dir() is None
    monkeypatch.setenv(ENV_VAR, "  ")
    assert onnx_dir() is None
    monkeypatch.setenv(ENV_VAR, "onnx_models")
    assert onnx_dir() == Path("onnx_models")


def test_held_releases_the_model_in_one_at_a_time_mode(monkeypatch):
    monkeypatch.setenv(ONE_AT_A_TIME_VAR, "1")
    session = _Session(Path("."), "bge")
    session._session, session._tokenizer = object(), object()
    with session.held():
        assert session._session is not None  # still loaded while the call runs
    assert session._session is None and session._tokenizer is None


def test_held_keeps_the_model_by_default(monkeypatch):
    monkeypatch.delenv(ONE_AT_A_TIME_VAR, raising=False)
    session = _Session(Path("."), "bge")
    session._session, session._tokenizer = object(), object()
    with session.held():
        pass
    assert session._session is not None


def test_held_releases_even_when_the_call_fails(monkeypatch):
    monkeypatch.setenv(ONE_AT_A_TIME_VAR, "1")
    session = _Session(Path("."), "ce")
    session._session = object()
    try:
        with session.held():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert session._session is None
    assert onnx_models._ONE_AT_A_TIME_LOCK.acquire(blocking=False)  # lock was freed
    onnx_models._ONE_AT_A_TIME_LOCK.release()
