"""ECOIND plug-in output (UG p.229-231). Shapes copied from a real EwE 6.7
Ecosampler export (RU_SSP1_Calib, 2026-10-30)."""

from __future__ import annotations

from ecosim.catalog import service
from ecosim.catalog.build import build_catalog
from ecosim.core.config import Settings
from ecosim.ingestion.parsers.ecoind_csv import parse_ecoind_csv
from ecosim.ingestion.pipeline import run_ingest

_HEADER = (
    '"<HEADER software/>"\nEwEVersion,"6.7.0.19431"\n'
    '"<HEADER ecopath/>"\nModelName,FuMa\n'
    '"<HEADER ecosim/>"\nEcosimScenario,SSP1_A002\nTimeSeries,keyrun\nStartYear,2004\n'
    '"<HEADER end/>"\n\n\n'
)
_TABLE = 'Time,"Total B","Kempton\'s Q",MTI\n' + "".join(
    f"{t},{1000 + t},{1.5 + t / 100},4.07,\n" for t in range(1, 25)
)


def test_indicator_table_becomes_monthly_and_yearly_mean_variables(tmp_path):
    f = tmp_path / "biodiv_ind_Ecosim.csv"
    f.write_text(_HEADER + _TABLE, encoding="utf-8")
    out = {(v, freq): df for v, freq, df in parse_ecoind_csv(f, scenario="ssp1_a002")}
    assert set(out) == {(v, fr) for v in ("ecoind_total_b", "ecoind_kempton_s_q", "ecoind_mti")
                        for fr in ("monthly", "annual")}
    monthly = out[("ecoind_total_b", "monthly")]
    assert len(monthly) == 24
    assert monthly.iloc[0][["year", "month", "value"]].tolist() == [2004, 1, 1001]
    assert monthly.iloc[12][["year", "month"]].tolist() == [2005, 1]
    annual = out[("ecoind_total_b", "annual")]
    assert annual[["year", "value"]].values.tolist() == [[2004, 1006.5], [2005, 1018.5]]
    assert monthly["unit"].iloc[0] == "Total B (ECOIND)"
    assert monthly["model_name"].iloc[0] == "FuMa"


def test_ingested_as_indicators(tmp_path):
    run = tmp_path / "raw" / "Sample_00001" / "ecosim_SSP1_A002"
    run.mkdir(parents=True)
    (run / "biodiv_ind_Ecosim.csv").write_text(_HEADER + _TABLE, encoding="utf-8")
    settings = Settings(output_raw_dir=tmp_path / "raw", store_dir=tmp_path / "store")
    report = run_ingest(settings)
    assert not report.errors and report.skipped_unsupported == 0
    build_catalog(settings)
    ds = {(d["variable"], d["freq"]): d for d in service.list_datasets(settings)}
    assert ds[("ecoind_mti", "annual")]["category"] == "indicators"
    assert ds[("ecoind_mti", "annual")]["label"] == "MTI (ECOIND, yearly mean)"


_ECOSPACE_HEADER = (
    '"<HEADER ecopath/>"\nModelName,FuMa\n'
    '"<HEADER ecosim/>"\nEcosimScenario,SSP1_A002\nStartYear,2004\n'
    '"<HEADER ecospace/>"\nEcospaceScenario,SSP1_A002\nMapRows,1\nMapCols,1\n'
    '"<HEADER end/>"\n'
)
_GRID = "ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n1.5\n"


def test_ecoind_maps_are_indexed_per_sample_without_runinfo(tmp_path):
    """The ECOIND maps' folder has no "Ecospace RunInfo.txt"; its identity comes
    from the region tables beside them. A headerless map-as-CSV table there must
    not be taken for one."""
    import pandas as pd

    from ecosim.catalog.service import list_raster_runs
    from ecosim.ingestion.spatial_pipeline import build_raster_index

    raw = tmp_path / "raw" / "Calib"
    for sample in ("Sample_00001", "Sample_00002"):
        space = raw / sample / "SSP1_A002"
        (space / "RegionAgeStructure").mkdir(parents=True)
        (space / "biodiv_ind_Ecospace12.csv").write_text("Column,Row,Lon,Lat,\"Total B\"\n1,1,0,0,2\n")
        (space / "RegionAgeStructure" / "AgeStructure_Cod_Region_All_Number.csv").write_text(
            _ECOSPACE_HEADER + "Max Age,2\n", encoding="utf-8")
        for step in ("0012", "0024"):
            (space / f"biodiv_ind_Total B-{step}.asc").write_text(_GRID)
    settings = Settings(output_raw_dir=tmp_path / "raw", store_dir=tmp_path / "store")
    report = build_raster_index(settings)
    assert report.unrecognized_files == 0 and report.has_multiple_runs
    assert report.ecoind_map_tables == 2  # the map-as-CSV duplicates, reported not loaded
    df = pd.read_csv(settings.spatial_dir / "raster_index.csv")
    assert set(df["variable"]) == {"ecoind_total_b"}
    assert set(df["scenario"]) == {"ssp1_a002"} and set(df["year"]) == {2004, 2005}
    assert df["group_name"].isna().all() and len(df) == 4
    build_catalog(settings)
    assert [r["label"] for r in list_raster_runs(settings, scenario="ssp1_a002", variable="ecoind_total_b")] == [
        "Sample_00001", "Sample_00002",
    ]
