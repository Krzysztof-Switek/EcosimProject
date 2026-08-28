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


def test_write_cog_accepts_matching_wgs84_wkt(tmp_path):
    from ecosim.ingestion.parsers.asc_grid import write_cog

    src = RAW / "output/Baseline_cumulative/baseline cumulative/asc/EcospaceMapBiomass-Benthopelagic-00001.asc"
    # The exact CoordinateSystemWKT string this scenario's real RunInfo.txt reports.
    wgs84_wkt = (
        "GEOGCS['WGS 84', DATUM['WGS_1984', SPHEROID['WGS 84',6378137,298.257223563, "
        "AUTHORITY['EPSG','7030']], AUTHORITY['EPSG','6326']], PRIMEM['Greenwich',0, "
        "AUTHORITY['EPSG','8901']], UNIT['degree',0.01745329251994328, AUTHORITY['EPSG','9122']], "
        "AUTHORITY['EPSG','4326']]"
    )
    out = tmp_path / "biomass.tif"
    write_cog(src, out, source_crs_wkt=wgs84_wkt)
    assert out.exists()


def test_write_cog_rejects_non_wgs84_wkt(tmp_path):
    from ecosim.ingestion.parsers.asc_grid import write_cog

    src = RAW / "output/Baseline_cumulative/baseline cumulative/asc/EcospaceMapBiomass-Benthopelagic-00001.asc"
    # A real local-UTM WKT (zone 33N, metres) -- stands in for what Ecospace's
    # "Assume Square Cells" mode would report instead of WGS84.
    utm_wkt = (
        "PROJCS['WGS 84 / UTM zone 33N', GEOGCS['WGS 84', DATUM['WGS_1984', "
        "SPHEROID['WGS 84',6378137,298.257223563]], PRIMEM['Greenwich',0], "
        "UNIT['degree',0.0174532925199433]], PROJECTION['Transverse_Mercator'], "
        "PARAMETER['latitude_of_origin',0], PARAMETER['central_meridian',15], "
        "PARAMETER['scale_factor',0.9996], PARAMETER['false_easting',500000], "
        "PARAMETER['false_northing',0], UNIT['metre',1], AUTHORITY['EPSG','32633']]"
    )
    out = tmp_path / "biomass.tif"
    with pytest.raises(ValueError, match="not WGS84/EPSG:4326"):
        write_cog(src, out, source_crs_wkt=utm_wkt)
    assert not out.exists()  # rejected before any conversion work happened


def test_materialize_raster_converts_once_then_caches(tmp_path):
    from ecosim.core.config import Settings
    from ecosim.ingestion.spatial_pipeline import materialize_raster

    settings = Settings(output_raw_dir=RAW, store_dir=tmp_path)
    row = {
        "path": "biomass.tif",
        # Absolute -- output/input rasters now come from two independently-
        # chosen roots, so there's no shared raw_dir left to store paths
        # relative to (see ingestion/spatial_pipeline.py).
        "source_path": str(
            RAW / "output/Baseline_cumulative/baseline cumulative/asc/"
            "EcospaceMapBiomass-Benthopelagic-00001.asc"
        ),
    }

    first = materialize_raster(row, settings)
    assert first.exists()
    mtime = first.stat().st_mtime

    second = materialize_raster(row, settings)
    assert second == first
    assert second.stat().st_mtime == mtime  # second call is a cache hit, not a re-conversion


def test_build_raster_index_carries_source_crs_wkt(tmp_path):
    # End-to-end: build_raster_index() reads CoordinateSystemWKT from the real
    # Ecospace RunInfo.txt and carries it into the index, so materialize_raster
    # can actually validate it later (see the write_cog tests above).
    from ecosim.core.config import Settings
    from ecosim.ingestion.spatial_pipeline import build_raster_index

    settings = Settings(output_raw_dir=RAW, input_raw_dir=RAW, store_dir=tmp_path)
    report = build_raster_index(settings)
    assert report.rasters_indexed > 0

    import pandas as pd

    df = pd.read_csv(settings.spatial_dir / "raster_index.csv")
    output_rows = df[df["domain"] == "output"]
    assert not output_rows.empty
    assert output_rows["source_crs_wkt"].notna().all()
    assert output_rows["source_crs_wkt"].str.contains("4326").all()

    input_rows = df[df["domain"] == "input"]
    if not input_rows.empty:
        assert input_rows["source_crs_wkt"].isna().all()  # no RunInfo.txt under input/


def test_build_raster_index_flags_same_year_collision(tmp_path):
    # Confirmed possible by the official docs (UG p.182: "especially when
    # writing spatial output for every monthly time step") -- Ecospace can be
    # configured to write spatial maps more often than once a year. Our raster
    # id has no month dimension, so two .asc files landing in the same
    # (scenario, variable, entity, year) must be caught, not silently merged.
    import shutil

    import pandas as pd

    from ecosim.core.config import Settings
    from ecosim.ingestion.spatial_pipeline import build_raster_index

    raw = tmp_path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    shutil.copy(RAW / "Mapa_grupy_fleets.xlsx", raw / "Mapa_grupy_fleets.xlsx")

    asc_dir = raw / "output" / "TestScenario" / "test scenario" / "asc"
    asc_dir.mkdir(parents=True, exist_ok=True)
    (asc_dir / "Ecospace RunInfo.txt").write_text(
        '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
        '"<HEADER ecosim/>"\nEcosimScenario,"test scenario"\nStartYear,1998\n'
        '"<HEADER end/>"\n',
        encoding="utf-8",
    )
    # Timesteps 1 and 2 both fall in year 1998 ((t-1)//12 == 0 for both) --
    # exactly what monthly-cadence output for the same group would look like.
    (asc_dir / "EcospaceMapBiomass-Benthopelagic-00001.asc").write_text("ncols 1\n", encoding="utf-8")
    (asc_dir / "EcospaceMapBiomass-Benthopelagic-00002.asc").write_text("ncols 1\n", encoding="utf-8")

    settings = Settings(output_raw_dir=raw, store_dir=tmp_path / "store")
    report = build_raster_index(settings)

    assert any("duplicate raster id" in e for e in report.errors)
    df = pd.read_csv(settings.spatial_dir / "raster_index.csv")
    matches = df[df["id"].str.contains("test_scenario") & df["id"].str.endswith("|1998")]
    assert len(matches) == 1  # only the first of the two colliding files got indexed
