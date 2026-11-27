"""Region packs and areas (regions/), built from small synthetic packs shaped
like the real ICES / management packs (docs/ewe-data-formats.md section 8)."""

from __future__ import annotations

import zipfile

import numpy as np
import pytest
from rasterio.crs import CRS

from ecosim.regions import store
from ecosim.regions.datagrid import resolve_grid
from ecosim.regions.grid import GridSignature, cell_areas_km2, read_asc_header
from ecosim.regions.masks import AreaError, area_mask, area_summary
from regions_helpers import CS, NAT, SD, SUBDIVISIONS, XLL, YLL, _area, _make_pack, _write_asc

def test_import_recognises_layers_by_content(imported):
    pack, _ = imported
    by_key = {layer["key"]: layer for layer in pack["layers"]}
    assert set(by_key) == {"ices_subdivisions", "03_natura2000_2024"}
    sd = by_key["ices_subdivisions"]
    assert sd["kind"] == "regions" and sd["title"] == "ICES subdivisions" and sd["crs"] == "EPSG:3035"
    # codes stay text: 28.1 and 28.2 are different subdivisions
    assert [c["code"] for c in sd["classes"]] == ["25", "26", "28.1", "28.2"]
    assert {c["code"]: c["cells"] for c in sd["classes"]} == {"25": 7, "26": 7, "28.1": 6, "28.2": 4}
    nat = by_key["03_natura2000_2024"]
    assert nat["kind"] == "mask" and nat["title"] == "Natura 2000 (2024)"
    assert nat["classes"][0]["cells"] == 6
    assert nat["details"] == {"Meaning of 1": "SPA i SCI", "Source": "EEA 2024"}
    text = " ".join(pack["warnings"])
    assert "legend says" not in text
    assert "100-region limit" in text and "Grid_depth.asc" in text and "no .prj" in text


def test_union_and_intersection(imported):
    _, ctx = imported
    assert area_mask(_area([SD("25")]), ctx).sum() == 7
    assert area_mask(_area([SD("25", "26")]), ctx).sum() == 14
    assert area_mask(_area([SD("25"), SD("26")]), ctx).sum() == 14  # items in a group = union
    assert area_mask(_area([SD("25", "26")], [NAT]), ctx).sum() == 4  # groups = intersection
    assert area_mask(_area([NAT], [SD("28.1")]), ctx).sum() == 2
    assert area_mask(_area([SD("28.2")], [NAT]), ctx).sum() == 0
    all_sd = {"kind": "regions", "layer": "ices_subdivisions"}  # no codes = every region, never id 0
    assert area_mask(_area([all_sd]), ctx).sum() == 24


def test_area_summary_km2(imported):
    _, ctx = imported
    assert area_summary(_area([SD("25")]), ctx) == {"cells": 7, "area_km2": 112.0}


def test_drawn_polygon_uses_cell_centres(imported):
    from rasterio.warp import transform_geom

    _, ctx = imported
    # a polygon around the centres of columns 1-2 of rows 1-2 (4 cells), drawn in lon/lat
    x0, x1 = XLL + 1 * CS + 100, XLL + 3 * CS - 100
    ytop = YLL + 5 * CS
    y0, y1 = ytop - 3 * CS + 100, ytop - 1 * CS - 100
    square = {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}
    lonlat = transform_geom("EPSG:3035", "EPSG:4326", square)
    mask = area_mask(_area([{"kind": "drawn", "geojson": {"type": "Feature", "geometry": lonlat}}]), ctx)
    assert mask.sum() == 4 and mask[1:3, 1:3].all()
    # drawn + region in one group (union), then cut by Natura
    mixed = area_mask(_area([{"kind": "drawn", "geojson": lonlat}, SD("28.2")], [NAT]), ctx)
    assert mixed.sum() == 4


def test_area_errors(imported):
    _, ctx = imported
    with pytest.raises(AreaError, match="no region 99"):
        area_mask(_area([SD("99")]), ctx)
    with pytest.raises(AreaError, match="not available"):
        area_mask(_area([{"kind": "regions", "layer": "ices_rectangles"}]), ctx)
    with pytest.raises(AreaError, match="empty"):
        area_mask({"groups": []}, ctx)


def test_resolve_grid_matches_by_header_not_declared_crs(imported, tmp_path):
    # an EwE map on the same grid that declares WGS 84 (as real exports do)
    data = tmp_path / "data" / "EcospaceMapBiomass-Cod-00001.asc"
    data.parent.mkdir()
    _write_asc(data, np.where(SUBDIVISIONS == -9999, -9999, 5), crs_epsg=4326)
    g = resolve_grid([{"source_path": str(tmp_path / "missing.asc")}, {"source_path": str(data)}])
    assert g.status == "matched" and g.crs_label == "EPSG:3035"
    assert {layer["key"] for layer in g.layers} == {"ices_subdivisions", "03_natura2000_2024"}


def test_resolve_grid_no_match_and_unknown(imported, tmp_path):
    other = tmp_path / "other.asc"
    _write_asc(other, np.zeros((3, 3)), crs_epsg=4326, xll=10.0, yll=54.0, cs=0.1)
    g = resolve_grid([{"source_path": str(other)}])
    assert g.status == "no_match" and "Load a map pack made for this grid" in g.message
    assert g.context() is not None  # drawn areas still work on it
    assert resolve_grid([{"source_path": str(tmp_path / "nope.asc")}]).status == "unknown"
    assert resolve_grid([]).status == "unknown"


def test_zip_import_reimport_and_remove(tmp_path):
    src = _make_pack(tmp_path / "pack")
    zpath = tmp_path / "pack.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src).as_posix())
        zf.writestr("../evil.asc", "x")  # never extracted outside the temp dir
    first = store.import_pack(zpath)
    again = store.import_pack(zpath)
    assert first["id"] == again["id"] and len(store.list_packs()) == 1
    layer = again["layers"][0]
    outlines = store.layer_outlines(store.get_layer(layer["id"]))
    assert outlines["features"] and all(f["geometry"]["type"] == "MultiPolygon" for f in outlines["features"])
    lon, lat = outlines["features"][0]["geometry"]["coordinates"][0][0][0]
    assert 0 < lon < 40 and 40 < lat < 70  # lon/lat, not metres
    assert store.remove_pack(first["id"]) and store.list_packs() == []


def test_import_rejects_folder_without_region_maps(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(store.RegionPackError, match="No region maps"):
        store.import_pack(tmp_path / "empty")


def test_cell_areas_geographic_shrink_northwards():
    grid = GridSignature(2, 2, 10.0, 54.0, 1.0)
    areas = cell_areas_km2(grid, CRS.from_epsg(4326))
    assert areas[0, 0] < areas[1, 0]  # row 0 is the northern row
    assert 6000 < areas[1, 0] < 7500  # 1° x 1° at 54-55°N ≈ 7.0 thousand km²


def test_read_asc_header_center_variant(tmp_path):
    p = tmp_path / "c.asc"
    p.write_text("ncols 2\nnrows 2\nxllcenter 5\nyllcenter 7\ncellsize 2\nNODATA_value -9999\n0 0\n0 0\n")
    assert read_asc_header(p) == GridSignature(2, 2, 4.0, 6.0, 2.0)


def test_area_outline_covers_exactly_its_cells(imported):
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom

    _, ctx = imported
    out = area_summary(_area([SD("25", "26")], [NAT]), ctx, outline=True)
    assert out["cells"] == 4
    (feature,) = out["geojson"]["features"]
    back = transform_geom("EPSG:4326", "EPSG:3035", feature["geometry"])
    inside = geometry_mask([back], out_shape=(5, 6), transform=ctx.grid.transform(), invert=True)
    assert (inside == area_mask(_area([SD("25", "26")], [NAT]), ctx)).all()  # cell-centre rule round-trips


def test_area_library_round_trip():
    from ecosim.regions.library import load_library, save_library

    assert load_library() == {"areas": [], "selected": []}
    a = {"id": "a1", "name": "SD 25", "area": _area([SD("25")])}
    saved = save_library([a], ["a1", "gone"])
    assert saved["selected"] == ["a1"]  # ids of deleted areas are dropped
    assert load_library() == {"areas": [a], "selected": ["a1"]}
