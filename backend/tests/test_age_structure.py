"""Ecospace region age-structure tables (ingestion/parsers/age_structure_csv.py).
Shape copied from a real EwE 6.7 Ecosampler export (RU_SSP1_Calib, 2026-10-30)."""

from __future__ import annotations

from ecosim.catalog import service
from ecosim.catalog.build import build_catalog
from ecosim.core.config import Settings
from ecosim.ingestion.parsers.age_structure_csv import parse_age_structure_csv
from ecosim.ingestion.pipeline import run_ingest

_HEADER = (
    '"<HEADER software/>"\nEwEVersion,"6.7.0.19431"\n'
    '"<HEADER ecopath/>"\nModelName,FuMa\n'
    '"<HEADER ecosim/>"\nEcosimScenario,SSP1_A002\nStartYear,2004\n'
    '"<HEADER ecospace/>"\nEcospaceScenario,SSP1_A002\nMapRows,219\n'
    '"<HEADER end/>"\n'
)
_TABLE = (
    "Max Age,3\n"
    "Timestep, Region,JuvCod_0,JuvCod_1,AdCod_3_2,AdCod_3_3\n"
    "0,Ecosim Base Values,2.5,2.2,0.9,0.8\n"
    "1,0,0.03,0.035,0.4,0.3\n"
    "13,0,0.08,0.036,0.5,0.2\n"
)


def test_cohorts_become_group_and_age(tmp_path):
    f = tmp_path / "AgeStructure_Cod_Region_All_Number.csv"
    f.write_text(_HEADER + _TABLE, encoding="utf-8")
    [(variable, freq, df)] = parse_age_structure_csv(f, scenario="ssp1_a002")
    assert (variable, freq) == ("age_structure_number", "annual")  # one row per January
    assert len(df) == 8  # 2 years x 4 cohorts; the base-values row is not a time step
    assert sorted(df["year"].unique()) == [2004, 2005]
    row = df[(df["group_name"] == "AdCod_3") & (df["partner_id"] == 3) & (df["year"] == 2005)].iloc[0]
    assert row["value"] == 0.2 and row["partner_name"] == "3 months"
    assert row["unit"] == "Numbers at age (all regions)"


def test_ingested_into_the_age_structure_box(tmp_path):
    run = tmp_path / "raw" / "Sample_00001" / "SSP1_A002" / "RegionAgeStructure"
    run.mkdir(parents=True)
    (run / "AgeStructure_Cod_Region_All_Weight.csv").write_text(_HEADER + _TABLE, encoding="utf-8")
    settings = Settings(output_raw_dir=tmp_path / "raw", store_dir=tmp_path / "store")
    report = run_ingest(settings)
    assert not report.errors and report.skipped_unsupported == 0
    build_catalog(settings)
    ds = {d["variable"]: d for d in service.list_datasets(settings)}
    assert ds["age_structure_weight"]["category"] == "age_structure"
    groups = service.list_selection_options(settings, category="age_structure", variable=["age_structure_weight"])
    assert [(g["name"], [c["id"] for c in g["children"]]) for g in groups] == [
        ("AdCod_3", [2, 3]), ("JuvCod", [0, 1]),  # unnumbered here (no Ecopath loaded): by name
    ]
    rows = service.query_timeseries(settings, variable="age_structure_weight", picks=[["juvcod", "1"]])
    assert [(r["year"], r["value"]) for r in rows] == [(2004, 0.035), (2005, 0.036)]
