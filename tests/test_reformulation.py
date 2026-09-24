"""Ablation #6, steps 1-2: acronym dictionary and spelling normalization,
plus the `ChainedReformulator` composition that later, metered rungs will
also use.

Task 28 adds step 5's two arms at the bottom: `HistoryConcatenationReformulator`
(free control) and `LlmDecontextualizer` (metered). The latter is tested
against a stub `Generator` only -- nothing here spends quota.
"""

from __future__ import annotations

from mcrag.retrieval.reformulation import (
    AcronymDictionaryReformulator,
    ChainedReformulator,
    HistoryConcatenationReformulator,
    IdentityReformulator,
    LlmDecontextualizer,
    SpellingNormalizer,
)
from mcrag.types import Event


def test_identity_is_a_passthrough():
    r = IdentityReformulator()
    assert r.reform("What is the GPA requirement?") == ["What is the GPA requirement?"]


def test_acronym_dictionary_appends_expansion():
    r = AcronymDictionaryReformulator({"GPA": ("Grade Point Average",)})
    out = r.reform("What is the minimum GPA?")
    assert out == ["What is the minimum GPA? Grade Point Average"]


def test_acronym_dictionary_no_match_is_untouched():
    r = AcronymDictionaryReformulator({"GPA": ("Grade Point Average",)})
    out = r.reform("What is the tuition cost?")
    assert out == ["What is the tuition cost?"]


def test_acronym_dictionary_skips_expansion_already_present():
    r = AcronymDictionaryReformulator({"GPA": ("Grade Point Average",)})
    out = r.reform("What GPA (Grade Point Average) do I need?")
    assert out == ["What GPA (Grade Point Average) do I need?"]


def test_acronym_dictionary_is_word_boundary_matched():
    # "GPAX" must not trigger the "GPA" entry.
    r = AcronymDictionaryReformulator({"GPA": ("Grade Point Average",)})
    out = r.reform("Tell me about GPAX scoring.")
    assert out == ["Tell me about GPAX scoring."]


def test_acronym_dictionary_multiple_terms_all_added():
    r = AcronymDictionaryReformulator({"MC": ("Maryville College",), "GPA": ("Grade Point Average",)})
    out = r.reform("Does MC require a minimum GPA?")
    assert out == ["Does MC require a minimum GPA? Maryville College Grade Point Average"]


def test_acronym_dictionary_case_insensitive_match():
    r = AcronymDictionaryReformulator({"GPA": ("Grade Point Average",)})
    out = r.reform("what is my gpa")
    assert out == ["what is my gpa Grade Point Average"]


def test_spelling_normalizer_fixes_known_misspelling():
    r = SpellingNormalizer({"FASFA": "FAFSA"})
    out = r.reform("How do I file my FASFA?")
    assert out == ["How do I file my FAFSA?"]


def test_spelling_normalizer_untouched_when_no_match():
    r = SpellingNormalizer({"FASFA": "FAFSA"})
    out = r.reform("How do I file my FAFSA?")
    assert out == ["How do I file my FAFSA?"]


def test_spelling_normalizer_word_boundary_matched():
    r = SpellingNormalizer({"recieve": "receive"})
    out = r.reform("misrecieved package")
    assert out == ["misrecieved package"]


def test_chained_reformulator_composes_single_query_stages():
    dict_stage = AcronymDictionaryReformulator({"GPA": ("Grade Point Average",)})
    spell_stage = SpellingNormalizer({"FASFA": "FAFSA"})
    chain = ChainedReformulator([spell_stage, dict_stage])
    out = chain.reform("What GPA do I need for FASFA?")
    assert out == ["What GPA do I need for FAFSA? Grade Point Average"]


def test_chained_reformulator_fans_out_through_later_stages():
    class FanOut:
        name = "fan_out"

        def reform(self, query, history=None):
            return [query + " a", query + " b"]

    spell_stage = SpellingNormalizer({"FASFA": "FAFSA"})
    chain = ChainedReformulator([FanOut(), spell_stage])
    out = chain.reform("FASFA question")
    assert out == ["FAFSA question a", "FAFSA question b"]


def test_chained_reformulator_dedupes_across_fanout():
    class FanOut:
        name = "fan_out"

        def reform(self, query, history=None):
            return [query, query]

    chain = ChainedReformulator([FanOut()])
    out = chain.reform("same query twice")
    assert out == ["same query twice"]


def test_chained_reformulator_requires_at_least_one_stage():
    import pytest

    with pytest.raises(ValueError):
        ChainedReformulator([])


def test_chained_reformulator_name_reflects_stages():
    chain = ChainedReformulator([IdentityReformulator(), IdentityReformulator()])
    assert chain.name == "identity+identity"


# ---- step 5: de-contextualization (Task 28) --------------------------------


class StubGenerator:
    """A `Generator` in the interface's own terms -- yields `token` events
    then one `done`, exactly like `OllamaCloudGenerator.generate`. Not a
    `complete()` stub: `complete()` is a convenience on the concrete cloud
    class, and this rung must work against anything satisfying the ABC."""

    def __init__(self, text: str = "", raises: Exception | None = None) -> None:
        self.text = text
        self.raises = raises
        self.prompts: list[str] = []
        self.kwargs: list[dict] = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        self.kwargs.append(kwargs)
        if self.raises is not None:
            raise self.raises
        yield Event("token", {"text": self.text})
        yield Event("done", {"text": self.text, "usage": {"prompt_tokens": 7, "completion_tokens": 3}})


def test_history_concat_returns_the_query_unchanged_with_no_history():
    r = HistoryConcatenationReformulator()
    assert r.reform("What if I wanted a single instead?") == ["What if I wanted a single instead?"]
    assert r.reform("q", []) == ["q"]


def test_history_concat_prepends_prior_turns_oldest_first():
    r = HistoryConcatenationReformulator()
    out = r.reform("What about a single?", ["How much is a standard double room?"])
    assert out == ["How much is a standard double room? What about a single?"]


def test_history_concat_keeps_only_the_last_n_turns_when_capped():
    r = HistoryConcatenationReformulator(max_turns=1)
    out = r.reform("And a single?", ["first turn", "second turn"])
    assert out == ["second turn And a single?"]


def test_decontextualizer_makes_no_call_without_history():
    gen = StubGenerator("rewritten")
    r = LlmDecontextualizer(gen)
    assert r.reform("Standalone question?") == ["Standalone question?"]
    # The cost criterion, asserted rather than asserted-in-prose: single-turn
    # traffic must not pay for a mechanism it cannot use.
    assert gen.prompts == []
    assert r.calls == 0


def test_decontextualizer_returns_the_models_rewrite():
    gen = StubGenerator("How much does a single room cost at Maryville College?")
    r = LlmDecontextualizer(gen)
    out = r.reform("What about a single?", ["How much is a standard double room?"])
    assert out == ["How much does a single room cost at Maryville College?"]
    assert r.calls == 1
    assert r.last_error is None


def test_decontextualizer_prompt_carries_the_history_and_the_followup():
    gen = StubGenerator("rewritten")
    r = LlmDecontextualizer(gen)
    r.reform("What about a single?", ["How much is a double?", "Is a meal plan included?"])
    prompt = gen.prompts[0]
    assert "How much is a double?" in prompt
    assert "Is a meal plan included?" in prompt
    assert "What about a single?" in prompt


def test_decontextualizer_runs_greedy():
    gen = StubGenerator("rewritten")
    LlmDecontextualizer(gen).reform("follow-up", ["prior"])
    assert gen.kwargs[0]["temperature"] == 0.0


def test_decontextualizer_strips_quotes_and_labels():
    for raw, expected in [
        ('"How much is a single room?"', "How much is a single room?"),
        ("Standalone question: How much is a single room?", "How much is a single room?"),
        ("  How much is a single room?  ", "How much is a single room?"),
    ]:
        r = LlmDecontextualizer(StubGenerator(raw))
        assert r.reform("f", ["p"]) == [expected]


def test_decontextualizer_falls_back_to_the_raw_query_on_empty_output():
    r = LlmDecontextualizer(StubGenerator(""))
    assert r.reform("What about a single?", ["prior"]) == ["What about a single?"]
    assert r.last_error == "empty rewrite"


def test_decontextualizer_falls_back_when_the_model_writes_an_essay():
    r = LlmDecontextualizer(StubGenerator("x" * 400))
    assert r.reform("What about a single?", ["prior"]) == ["What about a single?"]
    assert r.last_error is not None and "too long" in r.last_error


def test_decontextualizer_falls_back_on_a_multi_line_reply():
    r = LlmDecontextualizer(StubGenerator("Here is the rewrite:\nHow much is a single?"))
    assert r.reform("What about a single?", ["prior"]) == ["What about a single?"]
    assert r.last_error == "rewrite spans multiple lines"


def test_decontextualizer_falls_back_when_the_generator_raises():
    r = LlmDecontextualizer(StubGenerator(raises=TimeoutError("read timed out")))
    assert r.reform("What about a single?", ["prior"]) == ["What about a single?"]
    assert r.last_error is not None and "TimeoutError" in r.last_error


def test_decontextualizer_records_usage_for_cost_accounting():
    r = LlmDecontextualizer(StubGenerator("rewritten"))
    r.reform("f", ["p"])
    assert r.usage == [{"prompt_tokens": 7, "completion_tokens": 3}]


def test_decontextualizer_clears_last_error_on_a_later_success():
    gen = StubGenerator("")
    r = LlmDecontextualizer(gen)
    r.reform("f", ["p"])
    assert r.last_error == "empty rewrite"
    gen.text = "A good standalone question?"
    assert r.reform("f", ["p"]) == ["A good standalone question?"]
    assert r.last_error is None
