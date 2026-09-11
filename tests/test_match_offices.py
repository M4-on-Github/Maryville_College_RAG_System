"""Office-contact parsing: pure functions over synthetic text, no live corpus needed."""

from __future__ import annotations

from scripts.match_offices import find_prefix_contact, parse_division_offices

_DEPT_PAGE = """- Filter:
- Alphabetically
- Department | Division
Division of Humanities and Languages & Literature - Office
Wendy Specter, Administrative Assistant
Anderson Hall
865-981-8224 wendy.specter@maryvillecollege.edu
Division of Behavioral Sciences - Office
Gayle Gould, Administrative Assistant
Sutton Science Center
865-981-8274 gayle.gould@maryvillecollege.edu
Rachel Acuff
Adjunct Instructor of Music, Piano/Keyboard and Oboe
Clayton Center for the Arts
865-981-8520 rachel.acuff@maryvillecollege.edu View More
"""


def test_parse_division_offices_stops_before_the_personnel_flood():
    rows = parse_division_offices(_DEPT_PAGE)
    assert len(rows) == 2
    assert rows[0] == {
        "silo": "Division of Humanities and Languages & Literature",
        "contact_name": "Wendy Specter",
        "contact_title": "Administrative Assistant",
        "building": "Anderson Hall",
        "phone": "865-981-8224",
        "email": "wendy.specter@maryvillecollege.edu",
        "source": "directories/department (division-office block)",
        "confidence": "high",
    }
    assert all("Rachel Acuff" not in str(r.values()) for r in rows)


def test_find_prefix_contact_pairs_email_with_nearby_phone():
    text = "Contact the Registrar\n865-981-8212 registrar@maryvillecollege.edu"
    assert find_prefix_contact(text) == ("registrar@maryvillecollege.edu", "865-981-8212")


def test_find_prefix_contact_handles_missing_phone():
    text = "Reach out any time: alumni@maryvillecollege.edu"
    assert find_prefix_contact(text) == ("alumni@maryvillecollege.edu", "")


def test_find_prefix_contact_returns_none_without_an_email():
    assert find_prefix_contact("No contact info on this page.") is None
