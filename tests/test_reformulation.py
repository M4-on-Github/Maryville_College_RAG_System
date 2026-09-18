"""Ablation #6, steps 1-2: acronym dictionary and spelling normalization,
plus the `ChainedReformulator` composition that later, metered rungs will
also use.
"""

from __future__ import annotations

from mcrag.retrieval.reformulation import (
    AcronymDictionaryReformulator,
    ChainedReformulator,
    IdentityReformulator,
    SpellingNormalizer,
)


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
