"""A small synthetic region pack shaped like the real ICES / management packs
(docs/ewe-data-formats.md section 8) -- shared by the region, zonal and
spatial-analysis tests; the ``imported`` fixture is in conftest.py."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from rasterio.crs import CRS

from ecosim.regions import store
from ecosim.regions.grid import GridSignature
from ecosim.regions.masks import GridContext

# 6 columns x 5 rows, 4 km cells, EPSG:3035 -- row 0 is north.
XLL, YLL, CS = 4_000_000.0, 3_000_000.0, 4000.0
SUBDIVISIONS = np.array([
    [-9999, 1, 1, 2, 2, -9999],
    [1, 1, 1, 2, 2, 2],
    [1, 1, 3, 3, 2, 2],
    [0, 3, 3, 3, 4, 4],
    [-9999, -9999, 3, 4, 4, -9999],
])
NATURA = np.where(SUBDIVISIONS == -9999, -9999, 0)
NATURA[1:3, 1:4] = 1  # 6 cells: SD 25 x3, SD 26 x1, SD 28.1 x2
# cells per subdivision: 25 -> 7, 26 -> 7, 28.1 -> 6, 28.2 -> 4; id 0 -> 1


def _write_asc(path: Path, values: np.ndarray, *, crs_epsg: int = 3035, xll=XLL, yll=YLL, cs=CS) -> None:
    rows, cols = values.shape
    lines = [f"ncols {cols}", f"nrows {rows}", f"xllcorner {xll}", f"yllcorner {yll}",
             f"cellsize {cs}", "NODATA_value -9999"]
    lines += [" ".join(str(int(v)) for v in row) for row in values]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    path.with_suffix(".prj").write_text(CRS.from_epsg(crs_epsg).to_wkt(), encoding="ascii")


def _make_pack(root: Path) -> Path:
    grid = root / "Grid"
    grid.mkdir(parents=True)
    _write_asc(grid / "Grid_ICES_subdivisions.asc", SUBDIVISIONS)
    (grid / "Grid_ICES_subdivisions.csv").write_text(
        "﻿ewe_region_id;ices_subdivision;ices_area_code;water_cells\n"
        "0;;;1\n1;25;27.3.d.25;7\n2;26;27.3.d.26;7\n3;28.1;27.3.d.28.1;6\n4;28.2;27.3.d.28.2;4\n",
        encoding="utf-8",
    )
    _write_asc(grid / "Grid_03_Natura2000_2024.asc", NATURA)
    split = grid / "Prostokaty_limit_100"
    split.mkdir()
    _write_asc(split / "Grid_ICES_subdivisions_part_01.asc", SUBDIVISIONS)
    (split / "Grid_ICES_subdivisions_part_01.csv").write_text(
        "ewe_region_id;full_map_region_id;ices_subdivision;water_cells\n1;1;25;7\n", encoding="utf-8")
    _write_asc(grid / "Grid_depth.asc", np.where(SUBDIVISIONS == -9999, -9999, 37))
    (grid / "Grid_no_prj.asc").write_text((grid / "Grid_03_Natura2000_2024.asc").read_text(), encoding="ascii")
    (root / "Layers.csv").write_text(
        "﻿siatka;plik_ASC;komorki_1;znaczenie_1;zrodlo;okres\n"
        "Grid;Grid_03_Natura2000_2024.asc;6;SPA i SCI;EEA 2024;\n", encoding="utf-8")
    return root


def import_test_pack(tmp_path: Path):
    """Import the synthetic pack; returns (pack, GridContext of its grid)."""
    pack = store.import_pack(_make_pack(tmp_path / "pack"), "Test areas")
    grid = GridSignature(6, 5, XLL, YLL, CS)
    return pack, GridContext(grid, CRS.from_epsg(3035), store.layers_for_grid(grid))


def _area(*groups):
    return {"groups": [list(g) for g in groups]}


SD = lambda *codes: {"kind": "regions", "layer": "ices_subdivisions", "codes": list(codes)}  # noqa: E731
NAT = {"kind": "regions", "layer": "03_natura2000_2024"}
