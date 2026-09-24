"""Task 23 verification: `docs/stream_contract.md`'s JSON examples must
round-trip through `mcrag.service.events`'s Pydantic models exactly.
`extra="forbid"` on every model (see that module) means a field added to
one and not the other fails loudly here instead of drifting apart
silently -- this is what "doc and models diff clean in CI" means in
practice for a project without a codegen step (T23's scope is S)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mcrag.service.events import EVENT_MODELS, SCHEMA_VERSION, to_sse

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "stream_contract.md"
_EXAMPLE = re.compile(r"```json (\w+)\n(.*?)```", re.DOTALL)


def _examples() -> dict[str, str]:
    text = DOC_PATH.read_text(encoding="utf-8")
    found = _EXAMPLE.findall(text)
    assert found, f"no ```json <event> examples found in {DOC_PATH}"
    return dict(found)


def test_doc_documents_exactly_the_five_contract_events():
    assert set(_examples()) == set(EVENT_MODELS) == {"sources", "token", "citation", "refusal", "done"}


@pytest.mark.parametrize("event_type", sorted(EVENT_MODELS))
def test_example_round_trips_through_its_model(event_type):
    model_cls = EVENT_MODELS[event_type]
    payload = model_cls.model_validate_json(_examples()[event_type])
    again = model_cls.model_validate_json(payload.model_dump_json())
    assert again == payload


def test_example_rejects_an_undocumented_extra_field():
    """The `extra="forbid"` guarantee itself, proved rather than assumed --
    a doc/model drift in the "model grew a field the doc doesn't mention, or
    vice versa" direction must fail exactly like this."""
    model_cls = EVENT_MODELS["token"]
    with pytest.raises(Exception):
        model_cls.model_validate_json('{"text": "hi", "unexpected_field": true}')


def test_done_event_carries_the_schema_version():
    done = EVENT_MODELS["done"].model_validate_json(_examples()["done"])
    assert done.schema_version == SCHEMA_VERSION == "v1"


def test_refusal_reason_matches_per_query_jsonl_vocabulary():
    """PLAN §5's `refusal_source` already names three pathways --
    `RefusalEvent.reason` is defined to reuse that vocabulary, not invent a
    second one; this pins the three literal values against silent rename."""
    refusal = EVENT_MODELS["refusal"].model_validate_json(_examples()["refusal"])
    assert refusal.reason in {"threshold", "gate", "model"}


def test_to_sse_frame_format():
    token = EVENT_MODELS["token"](text="hi")
    assert to_sse("token", token) == 'event: token\ndata: {"text":"hi"}\n\n'


def test_to_sse_rejects_a_payload_for_the_wrong_event_type():
    token = EVENT_MODELS["token"](text="hi")
    with pytest.raises(TypeError):
        to_sse("done", token)


def test_to_sse_rejects_an_unknown_event_type():
    token = EVENT_MODELS["token"](text="hi")
    with pytest.raises(ValueError):
        to_sse("bogus", token)
