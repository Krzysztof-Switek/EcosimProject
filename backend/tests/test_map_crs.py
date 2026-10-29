"""Ecospace maps whose declared coordinate system can't be right, and the
per-source CRS the user sets to fix it.

Real case (2026-10-28): the FuMa_SSP1_SCEN model's maps have ``xllcorner
4535378 / yllcorner 3432716 / cellsize 4000`` -- metres -- while its
RunInfo.txt (and the .prj files EwE writes for ECOIND maps) declare WGS 84.
Stamped as WGS84 that's a longitude of 4.5 million degrees and the map
showed up duplicated all over the world. The synthetic grid below uses
exactly that header, shrunk to a few cells."""

from __future__ import annotations

import pytest

rasterio = pytest.importorskip("rasterio")

from ecosim.core.workspace import WorkspaceRegistry  # noqa: E402
from ecosim.ingestion.parsers.asc_grid import MapCrsError, write_cog  # noqa: E402
from ecosim.ingestion.spatial_pipeline import clear_materialized  # noqa: E402

_WGS84_WKT_AS_EWE_WRITES_IT = (
    "GEOGCS['WGS 84', DATUM['WGS_1984', SPHEROID['WGS 84',6378137,298.257223563, "
    "AUTHORITY['EPSG','7030']], AUTHORITY['EPSG','6326']], PRIMEM['Greenwich',0, "
    "AUTHORITY['EPSG','8901']], UNIT['degree',0.01745329251994328, AUTHORITY['EPSG','9122']], "
    "AUTHORITY['EPSG','4326']]"
)


def _metric_grid(path, ncols=4, nrows=3):
    rows = "\n".join(" ".join(["-9999"] + [str(r * 10 + c) for c in range(1, ncols)]) for r in range(nrows))
    path.write_text(
        f"ncols {ncols}\nnrows {nrows}\nxllcorner 4535378\nyllcorner 3432716\n"
        f"cellsize 4000\nNODATA_value -9999\n{rows}\n",
        encoding="ascii",
    )
    return path


def test_metres_declared_as_degrees_are_refused_with_candidates(tmp_path):
    src = _metric_grid(tmp_path / "EcospaceMapBiomass-Cod-00001.asc")
    out = tmp_path / "out.tif"
    with pytest.raises(MapCrsError) as info:
        write_cog(src, out, source_crs_wkt=_WGS84_WKT_AS_EWE_WRITES_IT)
    assert not out.exists()  # nothing mis-georeferenced is ever written
    err = info.value
    assert err.crs == "EPSG:4326"
    assert err.bounds[0] == 4535378
    by_code = {c["crs"]: c for c in err.candidates}
    # Each candidate shows where it would put the grid -- LAEA lands on the
    # south-western Baltic, which is how a user can tell it apart.
    west, south, east, north = by_code["EPSG:3035"]["extent"]
    assert 13 < west < 14 and 53.5 < south < 54.5


def test_user_set_map_crs_reprojects_to_wgs84_keeping_values(tmp_path):
    src = _metric_grid(tmp_path / "EcospaceMapBiomass-Cod-00001.asc")
    out = tmp_path / "out.tif"
    meta = write_cog(src, out, source_crs_wkt=_WGS84_WKT_AS_EWE_WRITES_IT, map_crs="EPSG:3035")
    with rasterio.open(out) as ds:
        assert ds.crs.to_epsg() == 4326
        assert 13 < ds.bounds.left < 14 and 53.5 < ds.bounds.bottom < 54.5
        data = ds.read(1)
        valid = set(data[data != ds.nodata].tolist())
    assert meta["xmin"] == pytest.approx(ds.bounds.left)
    # Nearest-neighbour: only original cell values appear, none interpolated.
    assert valid and valid <= {r * 10 + c for r in range(3) for c in range(1, 4)}


def test_plausible_wgs84_grid_is_written_unchanged(tmp_path):
    src = tmp_path / "EcospaceMapBiomass-Cod-00001.asc"
    src.write_text(
        "ncols 2\nnrows 2\nxllcorner 10\nyllcorner 54\ncellsize 0.5\nNODATA_value -9999\n1 2\n3 4\n",
        encoding="ascii",
    )
    out = tmp_path / "out.tif"
    meta = write_cog(src, out, source_crs_wkt=_WGS84_WKT_AS_EWE_WRITES_IT)
    assert (meta["width"], meta["height"], meta["xmin"], meta["ymax"]) == (2, 2, 10, 55)


def test_map_crs_survives_registry_round_trip(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("FuMa", tmp_path, "output")
    assert registry.get(source.id).map_crs is None
    registry.set_map_crs(source.id, "EPSG:3035")
    assert registry.get(source.id).map_crs == "EPSG:3035"


def test_folder_added_again_keeps_its_map_crs(tmp_path):
    # Real case (2026-10-28): the same asc folder added a second time lost the
    # CRS chosen for it, and the map was mis-placed again.
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    first = registry.add_source("asc", tmp_path, "output")
    registry.set_map_crs(first.id, "EPSG:3035")
    again = registry.add_source("asc", tmp_path, "output")
    assert registry.get(again.id).map_crs == "EPSG:3035"
    other = tmp_path / "other"
    other.mkdir()
    assert registry.add_source("other", other, "output").map_crs is None


def test_clear_materialized_removes_only_that_domains_cogs(tmp_path):
    out_tif = tmp_path / "scenario=s" / "domain=output" / "variable=biomass" / "cod__2004.tif"
    in_tif = tmp_path / "scenario=s" / "domain=input" / "variable=sst" / "x__2004.tif"
    for p in (out_tif, in_tif):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x")
    (tmp_path / "raster_index.csv").write_text("id\n")
    assert clear_materialized(tmp_path, "output") == 1
    assert not out_tif.exists() and in_tif.exists() and (tmp_path / "raster_index.csv").exists()
