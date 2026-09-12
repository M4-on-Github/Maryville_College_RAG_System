"""Task 8 step 4: `data/silos.yaml` and `data/offices.yaml` must agree.

Decision 0002: a referral's destination is data, hand-checked, never invented
by the model. These tests are the mechanical half of that check -- that the
two files are internally consistent, not that any human judgment call in them
is correct.
"""

from __future__ import annotations

from pathlib import Path

import yaml

SILOS_PATH = Path("data/silos.yaml")
OFFICES_PATH = Path("data/offices.yaml")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_silo_has_exactly_one_office_row():
    silo_names = {s["name"] for s in _load(SILOS_PATH)["silos"]}
    office_silos = [o["silo"] for o in _load(OFFICES_PATH)["offices"]]
    assert silo_names == set(office_silos)
    assert len(office_silos) == len(set(office_silos)), "duplicate office row for one silo"


def test_other_has_no_office_row():
    office_silos = {o["silo"] for o in _load(OFFICES_PATH)["offices"]}
    assert "other" not in office_silos


def test_every_office_has_an_email_and_a_destination_url():
    for office in _load(OFFICES_PATH)["offices"]:
        assert office["email"], f"{office['silo']} has no contact email"
        dest = office["destination_url"]
        assert dest.startswith("https://www.maryvillecollege.edu/"), office["silo"]


def test_no_path_prefix_is_claimed_by_two_silos():
    seen: dict[str, str] = {}
    for silo in _load(SILOS_PATH)["silos"]:
        for prefix in silo["path_prefixes"]:
            assert prefix not in seen, f"{prefix!r} claimed by both {seen.get(prefix)} and {silo['name']}"
            seen[prefix] = silo["name"]
