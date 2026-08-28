"""Tests proving the group/fleet dictionary (Mapa_grupy_fleets.xlsx) is
optional end-to-end -- not just at the registration-validator level
(test_source_validation.py) but through real ingestion too. Regression
coverage for a real bug (2026-08-27): a user pointed the "Model output
data" tile at genuine Monte Carlo results that kept their dictionary
elsewhere and got rejected citing a file EwE itself has never heard of.
See ingestion.parsers.group_map.Dictionaries.empty() and
docs/Plans and TO_DO lists/27.08_data_upload_PLAN.md.
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


def test_run_ingest_without_dictionary_still_ingests_real_shape(tmp_path):
    ecosim_dir = tmp_path / "output" / "TestModel" / "ecosim_test_scenario"
    ecosim_dir.mkdir(parents=True)
    (ecosim_dir / "biomass_annual.csv").write_text(
        _HEADER_BLOCK + "Data,Biomass\n\n" + "year\\group,1,2\n" + "1998,0.01,0.02\n" + "1999,0.011,0.021\n",
        encoding="utf-8",
    )
    # No Mapa_grupy_fleets.xlsx anywhere under tmp_path -- deliberate.

    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = run_ingest(settings)

    assert report.group_dictionary_found is False
    assert report.rows_written > 0
    assert not report.errors


def test_build_raster_index_without_dictionary_resolves_names_from_filename(tmp_path):
    asc_dir = tmp_path / "output" / "TestScenario" / "test scenario" / "asc"
    asc_dir.mkdir(parents=True)
    (asc_dir / "Ecospace RunInfo.txt").write_text(
        '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
        '"<HEADER ecosim/>"\nEcosimScenario,"test scenario"\nStartYear,1998\n'
        '"<HEADER end/>"\n',
        encoding="utf-8",
    )
    (asc_dir / "EcospaceMapBiomass-Cod adult-00001.asc").write_text("ncols 1\n", encoding="utf-8")
    # No Mapa_grupy_fleets.xlsx anywhere -- deliberate.

    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = build_raster_index(settings)

    assert report.group_dictionary_found is False
    assert report.rasters_indexed == 1
    df = pd.read_csv(settings.spatial_dir / "raster_index.csv")
    row = df.iloc[0]
    assert row["group_name"] == "Cod adult"  # resolved straight from the filename
    assert pd.isna(row["group_id"])  # no dictionary -> no numeric id, but not a failure
