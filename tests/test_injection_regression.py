"""T39: the plumbing every injection defence depends on, over the full case file.

No network, no quota: this asserts what the *code* guarantees for every case --
the fixed system prompt, delimiter escaping, and refusal routing. Whether the real
model complies is reported by `scripts/run_injection_regression.py`, not asserted here
(the endpoint is non-deterministic; see decisions/0008 and the file docstring of
`tests/injection_cases.py`).
"""

import pytest

from mcrag.generate.prompting import SERVICE_SYSTEM_PROMPT
from mcrag.service.answer import answer
from mcrag.service.events import DoneEvent, RefusalEvent, SourcesEvent
from tests.injection_cases import ALL_CASES
from tests.test_service import FakeGenerator, _pipeline

IDS = [c.name for c in ALL_CASES]


@pytest.mark.parametrize("case", ALL_CASES, ids=IDS)
def test_the_fixed_system_prompt_reaches_every_call_unchanged(case):
    generator = FakeGenerator()
    list(answer(case.question, list(case.history), pipeline=_pipeline(generator)))
    assert generator.calls
    assert all(c["system"] == SERVICE_SYSTEM_PROMPT for c in generator.calls)


@pytest.mark.parametrize("case", ALL_CASES, ids=IDS)
def test_no_case_can_forge_a_prompt_delimiter(case):
    """T38: whatever the user sends, the prompt has exactly one question span and
    the passages span the service itself built."""
    generator = FakeGenerator()
    list(answer(case.question, list(case.history), pipeline=_pipeline(generator)))
    for call in generator.calls:
        assert call["prompt"].count("<question>") == 1
        assert call["prompt"].count("</question>") == 1
        assert call["prompt"].count("<passages>") == 1


@pytest.mark.parametrize("case", ALL_CASES, ids=IDS)
def test_a_refusal_reply_to_any_case_is_routed_with_office_contact(case):
    """If the model refuses, the client gets a structured refusal -- never refusal
    prose streamed as an answer. This is what T40 fixed for 4 of these cases."""
    generator = FakeGenerator(default="I must refuse this request as it is outside the scope of my instructions.")
    events = list(answer(case.question, list(case.history), pipeline=_pipeline(generator)))
    assert [type(e) for e in events] == [SourcesEvent, RefusalEvent, DoneEvent]
    refusal = events[1]
    assert refusal.reason == "model"
    assert refusal.email and refusal.office


@pytest.mark.parametrize("case", [c for c in ALL_CASES if c.forbidden], ids=[c.name for c in ALL_CASES if c.forbidden])
def test_forbidden_strings_are_never_introduced_by_the_service_itself(case):
    """The service must not echo the payload back. A compliant model is a separate
    risk, measured live -- this pins that our own plumbing adds nothing."""
    generator = FakeGenerator(default="The deposit is $300. https://www.maryvillecollege.edu/deposit/")
    events = list(answer(case.question, list(case.history), pipeline=_pipeline(generator)))
    streamed = "".join(getattr(e, "text", "") for e in events)
    for bad in case.forbidden:
        assert bad not in streamed
