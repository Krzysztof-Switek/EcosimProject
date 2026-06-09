"""Parser tests against real sample files under DataEcosim/."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecosim.ingestion.parsers.ecosim_csv import parse_ecosim_csv
from ecosim.ingestion.parsers.group_map import parse_group_map

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "DataEcosim"
ECOSIM = RAW / "output/Baseline_cumulative/ecosim_Baltic_Ecosim"

pytestmark = pytest.mark.skipif(not RAW.exists(), reason="DataEcosim/ not present")


@pytest.fixture(scope="module")
def dicts():
    return parse_group_map(RAW / "Mapa_grupy_fleets.xlsx")


def test_group_dictionary(dicts):
    assert len(dicts.groups) == 50
    assert len(dicts.fleets) == 9
    assert dicts.group_name(19) == "Cod adult"
    assert dicts.group_id_by_name("cod adult") == 19


def test_wide_by_id(dicts):
    meta, df = parse_ecosim_csv(ECOSIM / "biomass_annual.csv", dicts, scenario="baseline")
    assert meta.variable == "biomass" and meta.freq == "annual"
    assert df["group_id"].nunique() == 50
    assert df["fleet_id"].isna().all()
    row = df[(df.year == 1998) & (df.group_id == 1)].iloc[0]
    assert row["group_name"] == "Ringed seal"
    assert row["value"] == pytest.approx(0.001336367, rel=1e-6)


def test_monthly_timestep_to_date(dicts):
    meta, df = parse_ecosim_csv(ECOSIM / "biomass_monthly.csv", dicts, scenario="baseline")
    assert meta.freq == "monthly"
    assert {df.month.min(), df.month.max()} == {1, 12}
    assert df.year.min() == 1998


def test_long_fleet_group(dicts):
    meta, df = parse_ecosim_csv(ECOSIM / "catch-fleet-group_annual.csv", dicts, scenario="baseline")
    assert meta.variable == "catch_fleet_group"
    assert df["fleet_id"].notna().all() and df["group_id"].notna().all()
    assert df[df.fleet_id == 1]["fleet_name"].iloc[0] == "Traps and pots"


def test_single_series(dicts):
    meta, df = parse_ecosim_csv(ECOSIM / "fib_annual.csv", dicts, scenario="baseline")
    assert meta.variable == "fib"
    assert df["group_id"].isna().all() and df["fleet_id"].isna().all()


def test_predation_wide_by_name(dicts):
    meta, df = parse_ecosim_csv(ECOSIM / "predation_cod adult_annual.csv", dicts, scenario="baseline")
    assert meta.variable == "predation"
    assert (df["group_name"] == "Cod adult").all()
    assert df["partner_name"].notna().all()


def test_prey_consolidated_owner_is_predator(dicts):
    # prey_<predator> = diet/consumption: owner (predator) -> group, columns -> prey.
    meta, df = parse_ecosim_csv(ECOSIM / "prey_cod adult_annual.csv", dicts, scenario="baseline")
    assert meta.variable == "prey"
    assert (df["group_name"] == "Cod adult").all()
    assert df["partner_name"].notna().all()
