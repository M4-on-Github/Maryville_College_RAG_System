"""Nav parsing against synthetic markup, so these tests don't need a live snapshot."""

from __future__ import annotations

from scripts.harvest_nav import harvest_main_nav, harvest_utility_nav

_DESKTOP_NAVBAR = """
<nav class="navbar navbar-expand-lg">
  <a class="dropdown-toggle" href="#">Academics</a>
  <a href="/academics/">Academics Overview</a>
  <a href="/academics/catalog/">Catalog</a>
  <a class="dropdown-toggle" href="#">Admissions</a>
  <a href="/admissions/">Admissions Overview</a>
</nav>
"""

_WITH_MOBILE_DUPLICATE = _DESKTOP_NAVBAR + """
<nav class="navbar navbar-expand">
  <a class="dropdown-toggle" href="#">Academics</a>
  <a href="/academics/">Academics Overview (mobile copy)</a>
</nav>
"""

_UTILITY_BAR = """
<a href="/alumni/" aria-label="Open Alumni section">Alumni</a>
<a href="/families" aria-label="Open Families section">Families</a>
"""


def test_harvest_main_nav_groups_children_under_their_dropdown():
    groups = harvest_main_nav(_DESKTOP_NAVBAR)
    assert list(groups) == ["Academics", "Admissions"]
    assert groups["Academics"] == [
        ("/academics/", "Academics Overview"),
        ("/academics/catalog/", "Catalog"),
    ]
    assert groups["Admissions"] == [("/admissions/", "Admissions Overview")]


def test_harvest_main_nav_stops_at_the_mobile_duplicate():
    groups = harvest_main_nav(_WITH_MOBILE_DUPLICATE)
    # The mobile navbar repeats "Academics" -- its children must not be
    # merged into (or replace) the desktop group already harvested.
    assert groups["Academics"] == [
        ("/academics/", "Academics Overview"),
        ("/academics/catalog/", "Catalog"),
    ]


def test_harvest_main_nav_missing_navbar_returns_empty():
    assert harvest_main_nav("<html><body>no nav here</body></html>") == {}


def test_harvest_utility_nav_finds_audience_links():
    items = harvest_utility_nav(_UTILITY_BAR)
    assert items == [("/alumni/", "Alumni"), ("/families", "Families")]
