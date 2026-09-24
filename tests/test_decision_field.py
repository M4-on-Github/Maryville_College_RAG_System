"""T41: the `DECISION:` parse rule (decisions/0017), fixed before the arm ran."""

from __future__ import annotations

import pytest

from mcrag.generate.decision_field import ABSTAIN, ANSWER, parse_decision, strip_decision_line
from mcrag.service.refusal import DecisionFieldClassifier, NarrowPhraseClassifier


def test_answer_line_is_parsed_and_stripped():
    decision, rest = parse_decision("DECISION: ANSWER\n\nThe deposit is $300. https://x.edu/a")
    assert decision == ANSWER
    assert rest == "The deposit is $300. https://x.edu/a"


def test_abstain_line_is_parsed_and_stripped():
    decision, rest = parse_decision("DECISION: ABSTAIN\n\nThe passages do not cover parking.")
    assert decision == ABSTAIN
    assert rest == "The passages do not cover parking."


@pytest.mark.parametrize(
    "text",
    [
        "decision: answer\n\nbody",  # case is not part of the protocol
        "  DECISION:ANSWER\nbody",  # leading space, no space after the colon
        "DECISION: ANSWER\r\n\r\nbody",  # CRLF
    ],
)
def test_tolerated_spellings(text):
    assert parse_decision(text)[0] == ANSWER
    assert parse_decision(text)[1] == "body"


@pytest.mark.parametrize(
    "text",
    [
        "The deposit is $300.",  # no line at all
        "DECISION: MAYBE\n\nbody",  # not one of the two values
        "Here is my reply.\nDECISION: ABSTAIN\n",  # not the first line
        "**DECISION: ABSTAIN**\n\nbody",  # decorated
    ],
)
def test_protocol_violations_report_none_and_change_nothing(text):
    decision, rest = parse_decision(text)
    assert decision is None
    assert rest == text


def test_only_one_blank_line_is_consumed():
    assert strip_decision_line("DECISION: ANSWER\n\n\nbody") == "\nbody"


def test_classifier_reads_the_field_not_the_prose():
    clf = DecisionFieldClassifier()
    # Prose that the phrase classifier would call a refusal, but the field says answer.
    text = "DECISION: ANSWER\n\nI am sorry, the hours are 9-5. https://x.edu/a"
    assert NarrowPhraseClassifier().is_refusal(text) is True
    assert clf.is_refusal(text) is False


def test_classifier_falls_back_when_the_field_is_missing():
    clf = DecisionFieldClassifier()
    assert clf.is_refusal("I must decline that request.") is True
    assert clf.is_refusal("The deposit is $300. https://x.edu/a") is False


def test_abstain_is_a_refusal_even_when_the_prose_reads_like_an_answer():
    assert DecisionFieldClassifier().is_refusal("DECISION: ABSTAIN\n\nThe deposit is $300.") is True
