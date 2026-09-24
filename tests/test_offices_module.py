"""`mcrag.offices.resolve` -- Task 27's silo-to-contact lookup, distinct from
`tests/test_offices.py` (which checks `data/offices.yaml` and `silos.yaml`
are internally consistent, not any code that reads them)."""

from __future__ import annotations

from pathlib import Path

from mcrag.offices import GENERAL_SILO, resolve

FAKE_YAML = """
offices:
  - silo: financial_aid
    email: financialaid@maryvillecollege.edu
    destination_url: https://www.maryvillecollege.edu/financial-aid/
  - silo: admissions
    email: admissions@maryvillecollege.edu
    destination_url: https://www.maryvillecollege.edu/admissions/apply/
"""


def _fake_path(tmp_path: Path) -> Path:
    path = tmp_path / "offices.yaml"
    path.write_text(FAKE_YAML, encoding="utf-8")
    return path


def test_resolve_returns_the_matching_silos_row(tmp_path):
    contact = resolve("financial_aid", path=_fake_path(tmp_path))
    assert contact.silo == "financial_aid"
    assert contact.email == "financialaid@maryvillecollege.edu"


def test_resolve_falls_back_to_the_general_silo_when_unknown(tmp_path):
    contact = resolve("other", path=_fake_path(tmp_path))
    assert contact.silo == GENERAL_SILO == "admissions"


def test_resolve_falls_back_when_silo_is_none(tmp_path):
    """No chunk retrieved at all -- still never an empty office."""
    contact = resolve(None, path=_fake_path(tmp_path))
    assert contact.silo == GENERAL_SILO


def test_resolve_against_the_real_offices_yaml():
    contact = resolve("admissions")
    assert contact.email == "admissions@maryvillecollege.edu"
    unroutable = resolve("not-a-real-silo")
    assert unroutable.silo == GENERAL_SILO
