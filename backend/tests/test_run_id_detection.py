"""Tests for run_id / Monte Carlo detection (added 2026-08-28).

Real trigger: a user activated genuine Ecosampler/Monte Carlo output
(RU_SSP1, 58 samples) and got a "successful" activation that silently
merged all 58 runs' CSVs into one indistinguishable scenario, while the
raster side rejected 98.3% of files as duplicate-id collisions. Neither is
right -- see core/schema.py's run_id docstring and
docs/Plans and TO_DO lists/28.08_session_summary.md.

These fixtures are entirely synthetic (no dependency on DataEcosim/ or any
real dataset) and deliberately do NOT use the "Sample_N" naming convention
anywhere -- run_id detection is purely structural (how many distinct
directories a (model,scenario) is found under), not name-based, exactly
like every other discovery rule in this pipeline.
"""

from __future__ import annotations

import pandas as pd
import pytest

rasterio = pytest.importorskip("rasterio")

from ecosim.core.config import Settings
from ecosim.ingestion.activation import ActivationResult, _data_kind, activate_source
from ecosim.ingestion.pipeline import run_ingest
from ecosim.ingestion.spatial_pipeline import build_raster_index

_HEADER_BLOCK = (
    '"<HEADER software/>"\n'
    'EwEVersion,"6.7.0.19540"\n'
    '"<HEADER ecopath/>"\n'
    'ModelName,"Test Model"\n'
    '"<HEADER ecosim/>"\n'
    "EcosimScenario,test_scenario\n"
    "StartYear,1998\n"
    '"<HEADER end/>"\n'
    "\n"
)
_CSV_BODY = "Data,Biomass\n\n" + "year\\group,1,2\n" + "1998,0.01,0.02\n" + "1999,0.011,0.021\n"


def _write_run_csv(root, run_dir: str) -> None:
    ecosim_dir = root / run_dir / "ecosim_test_scenario"
    ecosim_dir.mkdir(parents=True)
    (ecosim_dir / "biomass_annual.csv").write_text(_HEADER_BLOCK + _CSV_BODY, encoding="utf-8")


def _write_run_asc(root, run_dir: str) -> None:
    asc_dir = root / run_dir / "test scenario" / "asc"
    asc_dir.mkdir(parents=True)
    (asc_dir / "Ecospace RunInfo.txt").write_text(
        '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
        '"<HEADER ecosim/>"\nEcosimScenario,"test scenario"\nStartYear,1998\n'
        '"<HEADER end/>"\n',
        encoding="utf-8",
    )
    (asc_dir / "EcospaceMapBiomass-Cod adult-00001.asc").write_text("ncols 1\n", encoding="utf-8")


def test_single_run_csv_gets_null_run_id_and_is_not_flagged(tmp_path):
    _write_run_csv(tmp_path, "run1")
    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = run_ingest(settings)

    assert not report.has_multiple_runs
    assert report.run_count == 1
    df = pd.read_parquet(
        settings.timeseries_dir / "scenario=test_scenario/domain=output/variable=biomass/freq=annual/part.parquet"
    )
    assert df["run_id"].isna().all()


def test_two_directories_same_scenario_get_distinct_run_id(tmp_path):
    _write_run_csv(tmp_path, "Sample_00001")
    _write_run_csv(tmp_path, "Sample_00002")
    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = run_ingest(settings)

    assert report.has_multiple_runs
    assert report.run_count == 2
    df = pd.read_parquet(
        settings.timeseries_dir / "scenario=test_scenario/domain=output/variable=biomass/freq=annual/part.parquet"
    )
    assert df["run_id"].notna().all()
    assert df["run_id"].nunique() == 2
    # Both runs' rows survive independently (2 years x 2 groups x 2 runs) --
    # this is exactly what silently merged into one scenario before run_id
    # existed.
    assert len(df) == 8


def test_single_run_raster_gets_null_run_id(tmp_path):
    _write_run_asc(tmp_path, "run1")
    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = build_raster_index(settings)

    assert not report.has_multiple_runs
    assert report.run_count == 1
    df = pd.read_csv(settings.spatial_dir / "raster_index.csv")
    assert df["run_id"].isna().all()
    assert not df["id"].iloc[0].endswith("|run1")  # id unchanged from before run_id existed


def test_two_directories_same_scenario_get_distinct_raster_run_id(tmp_path):
    _write_run_asc(tmp_path, "Sample_00001")
    _write_run_asc(tmp_path, "Sample_00002")
    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = build_raster_index(settings)

    # Both files map to the same (scenario, variable, entity, year) and would
    # have collided under the pre-run_id id scheme -- now both are kept.
    assert report.rasters_indexed == 2
    assert not report.errors
    assert report.has_multiple_runs
    assert report.run_count == 2
    df = pd.read_csv(settings.spatial_dir / "raster_index.csv")
    assert df["run_id"].notna().all()
    assert df["id"].nunique() == 2


def test_data_kind_classification():
    assert _data_kind(has_timeseries=True, has_rasters=True, is_montecarlo=True) == "montecarlo"
    assert _data_kind(has_timeseries=True, has_rasters=True, is_montecarlo=False) == "mixed"
    assert _data_kind(has_timeseries=True, has_rasters=False, is_montecarlo=False) == "timeseries"
    assert _data_kind(has_timeseries=False, has_rasters=True, is_montecarlo=False) == "spatial"
    assert _data_kind(has_timeseries=False, has_rasters=False, is_montecarlo=False) is None


def test_activate_source_reports_montecarlo_and_run_count(tmp_path):
    from ecosim.core.workspace import WorkspaceRegistry

    raw = tmp_path / "raw"
    _write_run_csv(raw, "Sample_00001")
    _write_run_csv(raw, "Sample_00002")
    _write_run_asc(raw, "Sample_00001")
    _write_run_asc(raw, "Sample_00002")

    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("MC", raw, "output")
    result = activate_source(registry, source)

    assert isinstance(result, ActivationResult)
    assert result.data_kind == "montecarlo"
    assert result.run_count == 2
    assert registry.get(source.id).data_kind == "montecarlo"


def test_activate_source_reports_mixed_for_ordinary_single_run(tmp_path):
    from ecosim.core.workspace import WorkspaceRegistry

    raw = tmp_path / "raw"
    _write_run_csv(raw, "run1")
    _write_run_asc(raw, "run1")

    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("Ordinary", raw, "output")
    result = activate_source(registry, source)

    assert result.data_kind == "mixed"
    assert result.run_count == 1
    assert registry.get(source.id).data_kind == "mixed"
