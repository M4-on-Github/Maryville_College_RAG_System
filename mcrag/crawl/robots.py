"""Robots enforcement, and the sitemap discovery that comes with it for free.

Python's stdlib ``urllib.robotparser`` answers yes or no. That is not enough
here: the crawl manifest records *why* a URL was skipped, and
``robots_disallow:<rule>`` needs the rule text that matched. So this parser
keeps the rules and returns the winning one.

Matching follows RFC 9309:

- ``*`` matches any run of characters, ``$`` anchors the end of the path.
- The **longest matching rule wins**, and ``Allow`` beats ``Disallow`` on a tie.
  That precedence is why maryvillecollege.edu's ``Allow: /orientation/`` is not
  decoration -- without it, a future broader Disallow would silently swallow
  orientation pages.
- A group with a matching ``User-agent`` beats the ``*`` group entirely; groups
  are not merged.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Rule:
    """One Allow or Disallow line, kept verbatim for the manifest."""

    allow: bool
    pattern: str

    @property
    def text(self) -> str:
        return f"{'Allow' if self.allow else 'Disallow'}: {self.pattern}"

    @property
    def specificity(self) -> int:
        """Length of the pattern, ignoring wildcards. RFC 9309 tie-break."""
        return len(self.pattern.replace("*", "").replace("$", ""))

    def matches(self, path: str) -> bool:
        return _compile(self.pattern).match(path) is not None


@dataclass(frozen=True, slots=True)
class Decision:
    """The verdict plus the evidence for it."""

    allowed: bool
    rule: Rule | None = None

    @property
    def reason(self) -> str | None:
        """Manifest-ready reason string, or None when the URL is allowed."""
        if self.allowed:
            return None
        return f"robots_disallow:{self.rule.text}" if self.rule else "robots_disallow:unspecified"


class RobotsPolicy:
    """Parsed robots.txt for one host.

    Construct from text for tests, or with :meth:`fetch` for the live file.
    """

    def __init__(self, text: str, user_agent: str = "*") -> None:
        self.user_agent = user_agent
        self.sitemaps: list[str] = []
        self._groups: dict[str, list[Rule]] = {}
        self._crawl_delay: dict[str, float] = {}
        self._parse(text)

    # ---- construction --------------------------------------------------

    @classmethod
    def fetch(cls, base_url: str, user_agent: str, timeout: float = 30.0) -> RobotsPolicy:
        parts = urlsplit(base_url)
        url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", "replace")
        return cls(text, user_agent=user_agent)

    def _parse(self, text: str) -> None:
        current: list[str] = []
        expecting_agent = True
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field_name, _, value = line.partition(":")
            field_name = field_name.strip().lower()
            value = value.strip()

            if field_name == "user-agent":
                if not expecting_agent:
                    current = []
                    expecting_agent = True
                current.append(value.lower())
                self._groups.setdefault(value.lower(), [])
            elif field_name in ("allow", "disallow"):
                expecting_agent = False
                if not value and field_name == "disallow":
                    continue  # "Disallow:" with no path means allow everything
                for agent in current or ["*"]:
                    self._groups.setdefault(agent, []).append(
                        Rule(allow=(field_name == "allow"), pattern=value)
                    )
            elif field_name == "sitemap":
                self.sitemaps.append(value)
            elif field_name == "crawl-delay":
                try:
                    for agent in current or ["*"]:
                        self._crawl_delay[agent] = float(value)
                except ValueError:
                    continue

    # ---- querying ------------------------------------------------------

    def _rules_for(self, user_agent: str | None) -> list[Rule]:
        agent = (user_agent or self.user_agent or "*").lower()
        for known in self._groups:
            if known != "*" and known in agent:
                return self._groups[known]
        return self._groups.get("*", [])

    def crawl_delay(self, user_agent: str | None = None) -> float | None:
        agent = (user_agent or self.user_agent or "*").lower()
        for known, delay in self._crawl_delay.items():
            if known != "*" and known in agent:
                return delay
        return self._crawl_delay.get("*")

    def decide(self, url: str, user_agent: str | None = None) -> Decision:
        """Allow or refuse, naming the rule that decided it."""
        path = urlsplit(url).path or "/"
        if urlsplit(url).query:
            path = f"{path}?{urlsplit(url).query}"

        best: Rule | None = None
        for rule in self._rules_for(user_agent):
            if not rule.matches(path):
                continue
            if best is None:
                best = rule
            elif rule.specificity > best.specificity:
                best = rule
            elif rule.specificity == best.specificity and rule.allow and not best.allow:
                best = rule  # Allow wins ties

        if best is None:
            return Decision(allowed=True)
        return Decision(allowed=best.allow, rule=None if best.allow else best)

    def allows(self, url: str, user_agent: str | None = None) -> bool:
        return self.decide(url, user_agent).allowed


_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _compile(pattern: str) -> re.Pattern[str]:
    cached = _PATTERN_CACHE.get(pattern)
    if cached is not None:
        return cached
    anchored_end = pattern.endswith("$")
    body = pattern[:-1] if anchored_end else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    compiled = re.compile(regex + ("$" if anchored_end else ""))
    _PATTERN_CACHE[pattern] = compiled
    return compiled


class UserAgentError(ValueError):
    """Raised when a crawl is attempted without an identifying user agent."""


_CONTACT = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+|https?://\S+")


def build_user_agent(name: str, version: str, contact: str) -> str:
    """Build the crawl UA, refusing one that nobody can be reached through.

    An anonymous crawler gives a site operator no way to ask you to stop except
    by blocking the address. Failing loudly here is cheaper than being blocked.
    """
    if not contact or not _CONTACT.search(contact):
        raise UserAgentError(
            f"user agent needs a reachable contact (email or URL), got {contact!r} -- "
            "an anonymous crawler leaves the site operator no recourse but a block"
        )
    return f"{name}/{version} (+{contact})"


def require_identified(user_agent: str) -> str:
    """Guard for the fetch path. Raises rather than crawling anonymously."""
    if not user_agent or not _CONTACT.search(user_agent):
        raise UserAgentError(
            f"refusing to crawl with user agent {user_agent!r}: no contact address in it"
        )
    return user_agent
