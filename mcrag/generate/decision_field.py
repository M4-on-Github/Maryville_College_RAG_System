"""Parser for the `DECISION:` protocol line (T41, decisions/0017).

Fixed before the arm ran, so the parse rule could not be loosened after seeing
which replies failed it. A reply that does not start with the line is a
**protocol violation**: this module reports that, it does not go hunting for the
field elsewhere in the text, and it never guesses a decision from the prose --
guessing from prose is the thing the field exists to replace.
"""

from __future__ import annotations

import re

ANSWER = "ANSWER"
ABSTAIN = "ABSTAIN"

# Anchored at the start: only the first line counts. A model that buries
# `DECISION: ABSTAIN` in the middle of a paragraph has not followed the protocol.
_DECISION_LINE = re.compile(r"\A[ \t]*DECISION:[ \t]*(ANSWER|ABSTAIN)[ \t]*(?:\r?\n|\Z)", re.I)


def parse_decision(text: str) -> tuple[str | None, str]:
    """`(decision, text_without_the_line)`.

    `decision` is `"ANSWER"`, `"ABSTAIN"`, or `None` when the line is missing or
    malformed. The returned text is what downstream scoring sees: the protocol
    line and one blank line after it are removed, so an arm is neither rewarded
    nor punished for the scaffolding. When the line is absent the text comes back
    unchanged.
    """
    match = _DECISION_LINE.match(text)
    if match is None:
        return None, text
    rest = text[match.end() :]
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    return match.group(1).upper(), rest


def strip_decision_line(text: str) -> str:
    """`parse_decision(text)[1]`, for callers that only want the scoreable text."""
    return parse_decision(text)[1]
