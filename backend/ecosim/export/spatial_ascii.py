"""Export of selected Ecospace maps as ESRI ASCII grids, for analysis outside
the platform.

The files are the model's own: the same grid and coordinate system as the raw
``.asc`` EwE wrote (e.g. EPSG:3035, 4 km cells), values copied exactly (read as
Float64, written with 15 significant digits -- the raw text, not the Float32
the map works with), only cropped to an area of interest with the cells whose
centre falls outside it set to NODATA. Each ``.asc`` gets a ``.prj`` with the
grid's real CRS (the user-set ``DataSource.map_crs`` where EwE's declared one is
wrong -- see ingestion/parsers/asc_grid.py), which EwE itself doesn't write for
its map output.

Every file name encodes the whole selection (see ``file_stem`` and the
README.txt written into the archive), so files stay identifiable once
unpacked and mixed with others.
"""

from __future__ import annotations

import io
import json
import math
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ecosim.ingestion.file_access import UnreadableFileError, describe_read_error, is_cloud_only
from ecosim.ingestion.parsers.asc_grid import grid_crs

FULL_AREA = "full-area"
_FIELD_SEP = "__"


def name_part(text: str) -> str:
    """One field of a file name: letters, digits, '.', '-' and single '_' only,
    so the ``__`` field separator can never occur inside a field. Mirrors
    ``namePart`` in frontend/src/features/spatial/exportNames.ts."""
    part = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip())
    part = re.sub(r"_{2,}", "_", re.sub(r"-{2,}", "-", part)).strip("-._")
    return part or "x"


def file_stem(*, area: str, model: str | None, scenario: str, variable: str,
              entity: str | None, years: str) -> str:
    """``<area>__<model>__<scenario>__<variable>__<group or fleet>__<years>``;
    ``all`` stands in for the group/fleet of a variable that has none."""
    return _FIELD_SEP.join(name_part(p) for p in (
        area, model or "no-model", scenario, variable, entity or "all", years,
    ))


@dataclass
class ExportArea:
    name: str
    # GeoJSON FeatureCollection in lon/lat (as drawn on/uploaded to the map).
    geojson: dict | None = None


@dataclass
class AsciiExportReport:
    files: int = 0
    skipped: list[str] = field(default_factory=list)


def _geometries(geojson: dict) -> list[dict]:
    geoms = []
    for feature in geojson.get("features", []):
        g = feature.get("geometry") or {}
        if g.get("type") in ("Polygon", "MultiPolygon"):
            geoms.append(g)
    return geoms


def _read_grid(path: Path):
    import rasterio

    # Float64: the raw text values exactly, not GDAL's default Float32.
    with rasterio.Env(AAIGRID_DATATYPE="Float64"):
        with rasterio.open(path) as src:
            return src.read(1), src.transform, tuple(src.bounds), src.nodata


def _crop(data, transform, nodata, crs, area: ExportArea):
    """``(data, transform)`` cropped to the area's bounding box, cells whose
    centre is outside the area set to ``nodata``; None if they don't overlap."""
    import numpy as np
    from rasterio.features import bounds as geom_bounds
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom

    geoms = [transform_geom("EPSG:4326", crs, g) for g in _geometries(area.geojson or {})]
    if not geoms:
        return None
    boxes = [geom_bounds(g) for g in geoms]
    west, south = min(b[0] for b in boxes), min(b[1] for b in boxes)
    east, north = max(b[2] for b in boxes), max(b[3] for b in boxes)
    # Cells the box touches (north-up grid: transform.e < 0).
    rows, cols = data.shape
    col0 = max(0, math.floor((west - transform.c) / transform.a))
    col1 = min(cols, math.ceil((east - transform.c) / transform.a))
    row0 = max(0, math.floor((north - transform.f) / transform.e))
    row1 = min(rows, math.ceil((south - transform.f) / transform.e))
    if row0 >= row1 or col0 >= col1:
        return None
    win_transform = transform * transform.translation(col0, row0)
    out = data[row0:row1, col0:col1].copy()
    outside = geometry_mask(geoms, out_shape=out.shape, transform=win_transform)
    if outside.all():
        return None
    out[outside] = nodata
    if np.all(out == nodata):
        return None
    return out, win_transform


def _asc_text(data, transform, nodata) -> str:
    import numpy as np

    rows, cols = data.shape
    cellsize = transform.a
    xll = transform.c
    yll = transform.f + transform.e * rows
    lines = [
        f"ncols {cols}", f"nrows {rows}",
        f"xllcorner {xll:.15g}", f"yllcorner {yll:.15g}",
        f"cellsize {cellsize:.15g}", f"NODATA_value {nodata:.15g}",
    ]
    buf = io.StringIO()
    buf.write("\n".join(lines) + "\n")
    np.savetxt(buf, data, fmt="%.15g", delimiter=" ")
    return buf.getvalue()


def _readme(selection: dict, report: AsciiExportReport) -> str:
    lines = [
        "Ecosim platform -- ASCII grid export",
        f"Created: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "File names: <area>__<model>__<scenario>__<variable>__<group or fleet>__<year>.asc",
        "  area           name of the area of interest, or 'full-area' (the whole model grid)",
        "  group or fleet 'all' for a variable without groups/fleets",
        "  Fields are separated by '__'. Spaces and other characters outside",
        "  A-Z a-z 0-9 . - _ are written as '-'.",
        "",
        "Grid: the model's own (same cells and coordinate system as the EwE .asc output),",
        "values copied exactly. Cropped to the area's bounding box; cells whose centre is",
        "outside the area are NODATA. The .prj next to each file gives the coordinate system.",
        "",
        "Selection:",
    ]
    for key, value in selection.items():
        if key == "variables":
            for v in value:
                groups = v["groups_or_fleets"]
                lines += [
                    f"  {v['variable']}:",
                    f"    groups/fleets: {', '.join(groups) if isinstance(groups, list) else groups}",
                    f"    years: {v['years']}",
                ]
        else:
            lines.append(f"  {key}: {', '.join(map(str, value)) if isinstance(value, list) else value}")
    lines += ["", f"Files: {report.files}"]
    if report.skipped:
        lines += ["", "Not exported:"] + [f"  {s}" for s in report.skipped]
    return "\n".join(lines) + "\n"


def write_ascii_zip(
    out,
    rows: list[dict],
    *,
    areas: list[ExportArea],
    map_crs: str | None,
    selection: dict,
) -> AsciiExportReport:
    """Write a zip of ``.asc`` + ``.prj`` per (area, raster row) to the binary
    stream ``out``, plus README.txt and selection.json. ``rows`` are raster
    index rows (``catalog_rasters``); ``areas`` empty means the full grid."""
    from rasterio.crs import CRS
    from rasterio.enums import WktVersion

    report = AsciiExportReport()
    areas = areas or [ExportArea(FULL_AREA)]
    prj_cache: dict[str, str] = {}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            src = Path(row["source_path"])
            try:
                data, transform, bounds, nodata = _read_grid(src)
            except Exception as exc:  # noqa: BLE001 - say what's actually wrong
                if is_cloud_only(src):
                    raise UnreadableFileError(describe_read_error(exc, src)) from exc
                raise
            if nodata is None:
                nodata = -9999.0
            crs: CRS = grid_crs(src.name, bounds, source_crs_wkt=row.get("source_crs_wkt"), map_crs=map_crs)
            crs_key = crs.to_string()
            if crs_key not in prj_cache:
                prj_cache[crs_key] = crs.to_wkt(version=WktVersion.WKT1_ESRI)
            entity = row.get("group_name") or row.get("fleet_name")
            for area in areas:
                stem = file_stem(
                    area=area.name, model=row.get("model_name") or row.get("model"),
                    scenario=row["scenario"], variable=row["variable"],
                    entity=entity, years=str(row["year"]),
                )
                if area.geojson is None:
                    grid = (data, transform)
                else:
                    grid = _crop(data, transform, nodata, crs, area)
                    if grid is None:
                        report.skipped.append(f"{stem}: no model cells inside the area")
                        continue
                folder = name_part(area.name)
                zf.writestr(f"{folder}/{stem}.asc", _asc_text(*grid, nodata))
                zf.writestr(f"{folder}/{stem}.prj", prj_cache[crs_key])
                report.files += 1
        zf.writestr("README.txt", _readme(selection, report))
        zf.writestr("selection.json", json.dumps(
            {**selection, "files": report.files, "not_exported": report.skipped}, indent=2,
        ))
    return report
