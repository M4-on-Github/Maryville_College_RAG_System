"""Task 8 step 4: the silo mapper's path-prefix matching."""

from __future__ import annotations

from mcrag.silo_mapper import SiloMapper

BASE = "https://example.edu"


def test_exact_prefix_match():
    mapper = SiloMapper([("finaid", "finaid")])
    assert mapper.assign(f"{BASE}/finaid/", BASE) == ("finaid",)
    assert mapper.assign(f"{BASE}/finaid/apply/", BASE) == ("finaid",)


def test_no_match_is_other():
    mapper = SiloMapper([("finaid", "finaid")])
    assert mapper.assign(f"{BASE}/news/story/", BASE) == ("other",)


def test_longest_prefix_wins():
    mapper = SiloMapper([("about/inside", "governance"), ("about/inside/titleix", "title_ix")])
    assert mapper.assign(f"{BASE}/about/inside/titleix/", BASE) == ("title_ix",)
    assert mapper.assign(f"{BASE}/about/inside/woods/", BASE) == ("governance",)


def test_prefix_does_not_match_a_different_sibling_path():
    """`admissions` must not swallow `admissionsfoo` -- a boundary, not a substring."""
    mapper = SiloMapper([("admissions", "admissions")])
    assert mapper.assign(f"{BASE}/admissionsfoo/", BASE) == ("other",)


def test_root_page_matches_its_own_prefix():
    mapper = SiloMapper([("admissions", "admissions")])
    assert mapper.assign(f"{BASE}/admissions/", BASE) == ("admissions",)


def test_from_yaml_loads_the_real_taxonomy():
    mapper = SiloMapper.from_yaml("data/silos.yaml")
    names = mapper.silo_names()
    assert "finaid" in names
    assert "other" not in names  # other is the default, never a declared rule
    assert mapper.assign(f"{BASE}/admissions/finaid/apply/", BASE) == ("finaid",)
