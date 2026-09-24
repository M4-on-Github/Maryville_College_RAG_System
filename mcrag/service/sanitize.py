"""T38: neutralise prompt-delimiter tokens inside user-supplied text.

The generation prompt wraps the user turn in ``<question>`` and the retrieved
passages in ``<passages>``. A user turn that itself contains those tags can close
the span early and pose as instructions. This escapes the four delimiter tags
(any case, optional spaces or attributes) by turning the opening ``<`` into
``&lt;``. It is one defence layer, not a complete control (OWASP): it does not
stop paraphrased instructions, only forgery of the prompt's own structure.
"""

from __future__ import annotations

import re
from typing import Protocol

_DELIMITER = re.compile(r"<(\s*/?\s*(?:question|passages?)\b)", re.I)


class PromptSanitizer(Protocol):
    def sanitize(self, text: str) -> str: ...


class DelimiterEscaper:
    def sanitize(self, text: str) -> str:
        return _DELIMITER.sub(r"&lt;\1", text)


class NoOpSanitizer:
    """The control arm: what the service did before T38."""

    def sanitize(self, text: str) -> str:
        return text
