"""Parser tests against real sample files under DataEcosim/."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecosim.ingestion.parsers.ecosim_csv import parse_ecosim_csv

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "DataEcosim"
ECOSIM = RAW / "output/Baseline_cumulative/ecosim_Baltic_Ecosim"

pytestmark = pytest.mark.skipif(not RAW.exists(), reason="DataEcosim/ not present")


def test_wide_by_id_preserves_ids_but_has_no_name_source():
    # EwE's wide-by-id shape carries only bare numeric column headers, no
    # name anywhere in the file -- there is no external dictionary any more
    # (removed 2026-08-28, see docs/Plans and TO_DO lists/28.08_session_summary.md),
    # so group_name is always null for this shape; group_id is unaffected,
    # since it comes straight from the CSV's own column headers.
    meta, df = parse_ecosim_csv(ECOSIM / "biomass_annual.csv", scenario="baseline")
    assert meta.variable == "biomass" and meta.freq == "annual"
    assert df["group_id"].nunique() == 50
    assert df["fleet_id"].isna().all()
    assert df["group_name"].isna().all()
    row = df[(df.year == 1998) & (df.group_id == 1)].iloc[0]
    assert row["value"] == pytest.approx(0.001336367, rel=1e-6)


def test_monthly_timestep_to_date():
    meta, df = parse_ecosim_csv(ECOSIM / "biomass_monthly.csv", scenario="baseline")
    assert meta.freq == "monthly"
    assert {df.month.min(), df.month.max()} == {1, 12}
    assert df.year.min() == 1998


def test_long_fleet_group_preserves_ids_but_has_no_name_source():
    # Same story as wide-by-id: the long fleet-group shape is bare numeric
    # ids only, so fleet_name/group_name stay null; fleet_id/group_id are
    # unaffected.
    meta, df = parse_ecosim_csv(ECOSIM / "catch-fleet-group_annual.csv", scenario="baseline")
    assert meta.variable == "catch_fleet_group"
    assert df["fleet_id"].notna().all() and df["group_id"].notna().all()
    assert df["fleet_name"].isna().all() and df["group_name"].isna().all()


def test_single_series():
    meta, df = parse_ecosim_csv(ECOSIM / "fib_annual.csv", scenario="baseline")
    assert meta.variable == "fib"
    assert df["group_id"].isna().all() and df["fleet_id"].isna().all()


def test_predation_wide_by_name_resolves_names_from_the_file_itself():
    # Unlike wide-by-id/long, this shape carries real names directly in the
    # file (target species in the filename, partner species in the column
    # headers) -- resolves fully with no external dictionary of any kind.
    meta, df = parse_ecosim_csv(ECOSIM / "predation_cod adult_annual.csv", scenario="baseline")
    assert meta.variable == "predation"
    assert (df["group_name"] == "Cod adult").all()
    assert df["group_id"].isna().all()  # no numeric id source for this shape
    assert df["partner_name"].notna().all()


def test_prey_consolidated_owner_is_predator():
    # prey_<predator> = diet/consumption: owner (predator) -> group, columns -> prey.
    meta, df = parse_ecosim_csv(ECOSIM / "prey_cod adult_annual.csv", scenario="baseline")
    assert meta.variable == "prey"
    assert (df["group_name"] == "Cod adult").all()
    assert df["partner_name"].notna().all()


# EwE's basic auto-save (no Results Extractor Plugin) writes "a single output
# file ... 12 rows of data for each year" with no plugin-style <var>_annual /
# <var>_monthly filename split (docs/ewe-data-formats.md, UG p.275). We have
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


def test_no_plugin_file_without_freq_suffix_detects_monthly_from_header(tmp_path):
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

    meta, df = parse_ecosim_csv(path, scenario="baseline")
    assert meta.variable == "biomass"
    assert meta.freq == "monthly"  # not the filename-default "annual"
    assert set(df["month"]) == {1, 2}
    assert (df["year"] == 1998).all()


def test_no_plugin_file_without_freq_suffix_detects_annual_from_header(tmp_path):
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

    meta, df = parse_ecosim_csv(path, scenario="baseline")
    assert meta.freq == "annual"
    assert set(df["year"]) == {1998, 1999}
    assert (df["month"] == 1).all()


def test_no_plugin_long_shape_without_freq_suffix_detects_monthly(tmp_path):
    content = (
        _HEADER_BLOCK
        + "Data,CatchFleetGroup\n\n"
        + "timestep,fleet,group,value\n"
        + "1,1,1,0.001\n"
        + "13,1,1,0.002\n"
    )
    path = tmp_path / "CatchFleetGroup.csv"
    path.write_text(content, encoding="utf-8")

    meta, df = parse_ecosim_csv(path, scenario="baseline")
    assert meta.freq == "monthly"
    # timestep 13 = first month of the second year (start_year=1998).
    assert set(df["year"]) == {1998, 1999}
