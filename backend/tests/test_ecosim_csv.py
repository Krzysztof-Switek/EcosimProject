"""Parser tests against real sample files under DataEcosim/."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecosim.ingestion.parsers.ecosim_csv import parse_ecosim_csv
from ecosim.ingestion.parsers.group_map import Dictionaries, parse_group_map

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


def test_wide_by_id_without_dictionary_preserves_ids_but_nulls_names():
    # Regression test (2026-08-27): the dictionary must be optional -- a real
    # output folder without one (e.g. Monte Carlo results kept separately
    # from wherever the modeller's Mapa_grupy_fleets.xlsx lives) must still
    # ingest, just without resolved names. group_id comes straight from the
    # CSV's own column headers, so it's unaffected either way.
    meta, df = parse_ecosim_csv(ECOSIM / "biomass_annual.csv", Dictionaries.empty(), scenario="baseline")
    assert meta.variable == "biomass"
    assert df["group_id"].nunique() == 50  # ids fully resolved from the CSV itself
    assert df["group_name"].isna().all()   # but no dictionary to name them with


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


# EwE's basic auto-save (no Results Extractor Plugin) writes "a single output
# file ... 12 rows of data for each year" with no plugin-style <var>_annual /
# <var>_monthly filename split (docs/ewe-data-formats.md, UG p.289). We have
# no real sample of this -- these tests build a synthetic file matching the
# manual's description (same <HEADER/>/Data block convention every real file
# we do have already uses, just without an _annual/_monthly filename suffix)
# to confirm freq is still correctly detected from the header, not guessed
# wrong from the filename.
_HEADER_BLOCK = (
    '"<HEADER software/>"\n'
    'EwEVersion,"6.7.0.19540"\n'
    '"<HEADER ecopath/>"\n'
    'ModelName,"Baltic Sea_new"\n'
    '"<HEADER ecosim/>"\n'
    "EcosimScenario,Baltic_Ecosim\n"
    "StartYear,1998\n"
    '"<HEADER end/>"\n'
    "\n"
)


def test_no_plugin_file_without_freq_suffix_detects_monthly_from_header(dicts, tmp_path):
    # "Biomass.csv" -- no _annual/_monthly suffix at all, but the header's own
    # time column says "timestep", exactly like our real *_monthly.csv files.
    content = (
        _HEADER_BLOCK
        + "Data,Biomass\n\n"
        + "timestep\\group,1,2\n"
        + "1,0.01,0.02\n"
        + "2,0.011,0.021\n"
    )
    path = tmp_path / "Biomass.csv"
    path.write_text(content, encoding="utf-8")

    meta, df = parse_ecosim_csv(path, dicts, scenario="baseline")
    assert meta.variable == "biomass"
    assert meta.freq == "monthly"  # not the filename-default "annual"
    assert set(df["month"]) == {1, 2}
    assert (df["year"] == 1998).all()


def test_no_plugin_file_without_freq_suffix_detects_annual_from_header(dicts, tmp_path):
    # Same idea, annual this time: header says "year", filename gives no hint.
    content = (
        _HEADER_BLOCK
        + "Data,Biomass\n\n"
        + "year\\group,1,2\n"
        + "1998,0.01,0.02\n"
        + "1999,0.011,0.021\n"
    )
    path = tmp_path / "Biomass.csv"
    path.write_text(content, encoding="utf-8")

    meta, df = parse_ecosim_csv(path, dicts, scenario="baseline")
    assert meta.freq == "annual"
    assert set(df["year"]) == {1998, 1999}
    assert (df["month"] == 1).all()


def test_no_plugin_long_shape_without_freq_suffix_detects_monthly(dicts, tmp_path):
    content = (
        _HEADER_BLOCK
        + "Data,CatchFleetGroup\n\n"
        + "timestep,fleet,group,value\n"
        + "1,1,1,0.001\n"
        + "13,1,1,0.002\n"
    )
    path = tmp_path / "CatchFleetGroup.csv"
    path.write_text(content, encoding="utf-8")

    meta, df = parse_ecosim_csv(path, dicts, scenario="baseline")
    assert meta.freq == "monthly"
    # timestep 13 = first month of the second year (start_year=1998).
    assert set(df["year"]) == {1998, 1999}
