"""Tests for the Ecospace .asc grid parser/converter."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecosim.ingestion.parsers.asc_grid import parse_input_filename, parse_output_filename

rasterio = pytest.importorskip("rasterio")

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "DataEcosim"

pytestmark = pytest.mark.skipif(not RAW.exists(), reason="DataEcosim/ not present")


def test_parse_output_biomass_filename():
    meta = parse_output_filename("EcospaceMapBiomass-Cod adult-00013.asc", start_year=1998)
    assert meta is not None
    assert meta.variable == "biomass"
    assert meta.entity_type == "group"
    assert meta.entity_name == "Cod adult"
    assert meta.year == 1999  # timestep 13 = first month of the second year


def test_parse_output_effort_is_fleet_dimensioned():
    meta = parse_output_filename("EcospaceMapEffort-Gillnet-00001.asc", start_year=1998)
    assert meta is not None
    assert meta.variable == "effort"
    assert meta.entity_type == "fleet"
    assert meta.year == 1998


def test_parse_output_habitat_capacity():
    meta = parse_output_filename("LayerHabitatCapacity-Bivalve-00625.asc", start_year=1998)
    assert meta is not None
    assert meta.variable == "habitat_capacity"
    assert meta.year == 1998 + (625 - 1) // 12


def test_parse_output_unrecognised_returns_none():
    assert parse_output_filename("Ecospace RunInfo.txt", start_year=1998) is None


def test_parse_input_simple_suffix_year():
    meta = parse_input_filename("Obott_1998.asc", driver="Bottom o2")
    assert meta is not None
    assert meta.variable == "bottom_o2"
    assert meta.year == 1998
    assert meta.entity_type is None


def test_parse_input_codrv_embedded_year():
    meta = parse_input_filename(
        "HIST_Baltic_all__yy2005_map_VerticalSUM_reproductive_volume_km3.asc",
        driver="CodRV_4ml",
    )
    assert meta is not None
    assert meta.variable == "codrv_4ml"
    assert meta.year == 2005


def test_write_cog_roundtrip(tmp_path):
    from ecosim.ingestion.parsers.asc_grid import write_cog

    src = RAW / "output/Baseline_cumulative/baseline cumulative/asc/EcospaceMapBiomass-Benthopelagic-00001.asc"
    out = tmp_path / "biomass.tif"
    meta = write_cog(src, out)
    assert out.exists()
    with rasterio.open(out) as ds:
        assert ds.crs.to_epsg() == 4326
        assert ds.width == meta["width"] == 675
        assert ds.height == meta["height"] == 374
        assert ds.overviews(1)  # COG must carry at least one overview level


def test_materialize_raster_converts_once_then_caches(tmp_path):
    from ecosim.core.config import Settings
    from ecosim.ingestion.spatial_pipeline import materialize_raster

    settings = Settings(raw_dir=RAW, store_dir=tmp_path)
    row = {
        "path": "biomass.tif",
        "source_path": "output/Baseline_cumulative/baseline cumulative/asc/"
        "EcospaceMapBiomass-Benthopelagic-00001.asc",
    }

    first = materialize_raster(row, settings)
    assert first.exists()
    mtime = first.stat().st_mtime

    second = materialize_raster(row, settings)
    assert second == first
    assert second.stat().st_mtime == mtime  # second call is a cache hit, not a re-conversion
