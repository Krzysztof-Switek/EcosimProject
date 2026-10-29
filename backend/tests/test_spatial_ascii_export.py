"""ASCII export of selected Ecospace maps: the model's own grid, exact values,
cropped per area of interest, file names that encode the selection."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

rasterio = pytest.importorskip("rasterio")

from ecosim.export.spatial_ascii import (  # noqa: E402
    ExportArea, file_stem, name_part, write_ascii_zip,
)
from ecosim.ingestion.parsers.asc_grid import MapCrsError  # noqa: E402

# Same header as the real FuMa_SSP1_SCEN maps (metres, EPSG:3035), 4x3 cells.
_HEADER = "ncols 4\nnrows 3\nxllcorner 4535378\nyllcorner 3432716\ncellsize 4000\nNODATA_value -9999\n"
_VALUES = [[0.123456789012, 2, 3, -9999], [5, 6, 7, 8], [9, 10, 11, 12]]


def _row(tmp_path, year=2004, group="Acartia sp."):
    src = tmp_path / f"EcospaceMapBiomass-{group}-{year}.asc"
    src.write_text(_HEADER + "\n".join(" ".join(str(v) for v in r) for r in _VALUES) + "\n", encoding="ascii")
    return {
        "source_path": str(src), "source_crs_wkt": None, "model": "fuma", "model_name": "FuMa_SSP1_SCEN",
        "scenario": "ssp1_a002", "variable": "biomass", "group_name": group, "fleet_name": None, "year": year,
    }


def _lonlat_box_around_cell(row: int, col: int) -> dict:
    """A small lon/lat square around the centre of one cell of the grid above."""
    from rasterio.warp import transform

    x = 4535378 + 4000 * col + 2000
    y = 3432716 + 4000 * (3 - row) - 2000
    (lon,), (lat,) = transform("EPSG:3035", "EPSG:4326", [x], [y])
    d = 0.01
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}]}


def _export(tmp_path, rows, areas, map_crs="EPSG:3035"):
    buf = io.BytesIO()
    report = write_ascii_zip(buf, rows, areas=areas, map_crs=map_crs, selection={"scenario": "ssp1_a002"})
    return report, zipfile.ZipFile(io.BytesIO(buf.getvalue()))


def test_full_area_keeps_grid_and_exact_values(tmp_path):
    report, zf = _export(tmp_path, [_row(tmp_path)], [])
    stem = "full-area/full-area__FuMa_SSP1_SCEN__ssp1_a002__biomass__Acartia-sp__2004"
    assert report.files == 1
    text = zf.read(f"{stem}.asc").decode()
    assert "xllcorner 4535378" in text and "cellsize 4000" in text
    assert text.splitlines()[6].split()[0] == "0.123456789012"  # not rounded to Float32
    assert "LAEA" in zf.read(f"{stem}.prj").decode() or "Lambert" in zf.read(f"{stem}.prj").decode()
    assert {"README.txt", "selection.json"} <= set(zf.namelist())


def test_each_area_cropped_separately_and_masked(tmp_path):
    areas = [ExportArea("North east", _lonlat_box_around_cell(0, 2)), ExportArea("South", _lonlat_box_around_cell(2, 0))]
    report, zf = _export(tmp_path, [_row(tmp_path)], areas)
    assert report.files == 2
    ne = zf.read("North-east/North-east__FuMa_SSP1_SCEN__ssp1_a002__biomass__Acartia-sp__2004.asc").decode()
    assert "ncols 1" in ne and "nrows 1" in ne and ne.splitlines()[-1].strip() == "3"
    south = zf.read("South/South__FuMa_SSP1_SCEN__ssp1_a002__biomass__Acartia-sp__2004.asc").decode()
    assert south.splitlines()[-1].strip() == "9"


def test_area_outside_the_grid_is_reported_not_written(tmp_path):
    far = ExportArea("Far", {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {
        "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]})
    report, zf = _export(tmp_path, [_row(tmp_path)], [far])
    assert report.files == 0 and len(report.skipped) == 1
    assert json.loads(zf.read("selection.json"))["not_exported"] == report.skipped


def test_wrong_declared_crs_is_refused(tmp_path):
    with pytest.raises(MapCrsError):
        _export(tmp_path, [_row(tmp_path)], [], map_crs=None)  # no CRS set: WGS84 assumed, metres refused


def test_file_names_encode_the_selection():
    assert name_part("Acartia sp.") == "Acartia-sp"
    assert name_part("Gulf / Bothnia") == "Gulf-Bothnia"
    assert file_stem(area="Area 1", model="M", scenario="s", variable="catch", entity=None, years="2004") == \
        "Area-1__M__s__catch__all__2004"
