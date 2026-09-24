"""Tests proving ingestion works with no group/fleet name dictionary of any
kind -- not "gracefully degrades without one" (that framing implied a
dictionary was still a supported concept), but simply the only behavior that
exists at all: this pipeline has no mechanism to resolve numeric group/fleet
ids to names beyond what EwE's own files already carry directly (removed
2026-08-28, see docs/Plans and TO_DO lists/28.08_session_summary.md).

Regression coverage for the real bug (2026-08-27) that started this: a user
pointed the "Model output data" tile at genuine Monte Carlo results and got
rejected citing a file (Mapa_grupy_fleets.xlsx) EwE itself has never heard
of and this project no longer has any code path to even look for.
"""

from __future__ import annotations

import pandas as pd
import pytest

rasterio = pytest.importorskip("rasterio")

from ecosim.core.config import Settings
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


def test_run_ingest_has_no_dictionary_mechanism_and_ingests_fine(tmp_path):
    ecosim_dir = tmp_path / "output" / "TestModel" / "ecosim_test_scenario"
    ecosim_dir.mkdir(parents=True)
    (ecosim_dir / "biomass_annual.csv").write_text(
        _HEADER_BLOCK + "Data,Biomass\n\n" + "year\\group,1,2\n" + "1998,0.01,0.02\n" + "1999,0.011,0.021\n",
        encoding="utf-8",
    )

    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = run_ingest(settings)

    assert report.rows_written > 0
    assert not report.errors
    assert not (tmp_path / "store" / "dictionaries" / "groups.csv").exists()
    assert not (tmp_path / "store" / "dictionaries" / "fleets.csv").exists()


def test_build_raster_index_resolves_group_names_straight_from_the_filename(tmp_path):
    asc_dir = tmp_path / "output" / "TestScenario" / "test scenario" / "asc"
    asc_dir.mkdir(parents=True)
    (asc_dir / "Ecospace RunInfo.txt").write_text(
        '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
        '"<HEADER ecosim/>"\nEcosimScenario,"test scenario"\nStartYear,1998\n'
        '"<HEADER end/>"\n',
        encoding="utf-8",
    )
    (asc_dir / "EcospaceMapBiomass-Cod adult-00001.asc").write_text("ncols 1\n", encoding="utf-8")

    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = build_raster_index(settings)

    assert report.rasters_indexed == 1
    df = pd.read_csv(settings.spatial_dir / "raster_index.csv")
    row = df.iloc[0]
    assert row["group_name"] == "Cod adult"  # resolved straight from the filename
    assert pd.isna(row["group_id"])  # no id source exists for this shape at all
