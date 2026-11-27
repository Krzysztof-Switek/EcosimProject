"""Reading a region pack: a folder of ESRI ASCII region maps on a model grid.

Recognised by content, never by folder or file names:

* **Region map with a legend** -- ``<stem>.asc`` + ``<stem>.prj`` +
  ``<stem>.csv``; cell value = region id (local to that map), the legend's
  ``ewe_region_id`` column maps it to a code. ``ices_subdivision`` /
  ``ices_rectangle`` code columns mark the ICES layers; codes are kept as
  text (``28.1`` and ``28.2`` are different subdivisions). Id 0 = water with
  no region.
* **Mask** -- ``.asc`` + ``.prj`` whose values are only 0/1 (1 = in the
  layer, 0 = water outside it). Optional descriptions come from any CSV in
  the pack that has a column naming the ``.asc`` files (the management
  pack's ``Warstwy_i_liczebnosc.csv``).
* Skipped, with a warning: maps whose legend has ``full_map_region_id``
  (pieces of a map split only for EwE's 100-region limit -- the full map is
  used), maps without ``.prj``, anything else (e.g. a depth grid).

In every map -9999 (the header's NODATA_value) is land / outside the model's
water mask. Cell membership follows the cell centre, as the packs were built
(docs/ewe-data-formats.md section 8).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ecosim.regions.grid import GridSignature
from ecosim.regions.titles import DETAIL_LABELS, LAYER_KIND_TITLES, mask_title

LAND = -1  # stored value for NODATA cells; 0 = water without region

_ICES_CODE_COLUMNS = {
    "ices_subdivision": "ices_subdivisions",
    "ices_rectangle": "ices_rectangles",
}
_SPLIT_PART_COLUMN = "full_map_region_id"


@dataclass
class ScannedLayer:
    rel_path: str
    key: str  # grid-independent identity, e.g. "ices_subdivisions", "03_natura2000_2024"
    kind: str  # "regions" (legend, several codes) | "mask" (0/1)
    title: str
    category: str  # "ICES" | "Management" | "Other"
    grid: GridSignature
    crs_wkt: str
    array: np.ndarray  # int16, LAND / 0 / region id (mask: 1)
    classes: list[dict]  # [{id, code, label, cells}]
    details: dict = field(default_factory=dict)


@dataclass
class ScannedPack:
    layers: list[ScannedLayer]
    warnings: list[str]


def _read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1250"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path.name}: unknown text encoding")
    first = text.splitlines()[0] if text else ""
    delimiter = max((";", ",", "\t"), key=first.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _read_grid(path: Path):
    import rasterio

    with rasterio.open(path) as src:
        values = src.read(1)
        nodata = src.nodata
        crs = src.crs
        t = src.transform
        grid = GridSignature(src.width, src.height, t.c, t.f + t.e * src.height, t.a)
    return values, nodata, crs, grid


def _grid_prefix_stripped(stem: str, folder: str) -> str:
    if folder and stem.lower().startswith(folder.lower() + "_"):
        return stem[len(folder) + 1:]
    return stem


def _mask_catalog(root: Path, asc_names: set[str], legend_paths: set[Path]) -> dict[str, dict]:
    """``{asc file name: details}`` from any CSV with a column naming the maps."""
    out: dict[str, dict] = {}
    for path in root.rglob("*.csv"):
        if path in legend_paths:
            continue
        try:
            rows = _read_csv(path)
        except (OSError, ValueError):
            continue
        if not rows:
            continue
        name_col = next((c for c in rows[0] if any(r.get(c) in asc_names for r in rows)), None)
        if not name_col:
            continue
        for r in rows:
            name = r.get(name_col)
            if name in asc_names:
                out[name] = {DETAIL_LABELS[k]: v for k, v in r.items() if k in DETAIL_LABELS and v}
    return out


def scan_pack(root: Path) -> ScannedPack:
    warnings: list[str] = []
    layers: list[ScannedLayer] = []
    asc_paths = sorted(root.rglob("*.asc"))
    legend_paths = {p.with_suffix(".csv") for p in asc_paths if p.with_suffix(".csv").exists()}
    catalog = _mask_catalog(root, {p.name for p in asc_paths}, legend_paths)

    for path in asc_paths:
        rel = path.relative_to(root).as_posix()
        prj = path.with_suffix(".prj")
        if not prj.exists():
            warnings.append(f"{rel}: skipped -- no .prj file next to it, so its coordinate system is unknown.")
            continue
        legend_path = path.with_suffix(".csv")
        legend = _read_csv(legend_path) if legend_path in legend_paths else None
        if legend and _SPLIT_PART_COLUMN in legend[0]:
            warnings.append(f"{rel}: skipped -- part of a map split for EwE's 100-region limit; the full map is used.")
            continue
        try:
            values, nodata, crs, grid = _read_grid(path)
        except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the pack
            warnings.append(f"{rel}: skipped -- could not read it ({exc}).")
            continue
        if crs is None:
            warnings.append(f"{rel}: skipped -- its .prj could not be read.")
            continue
        land = values == nodata if nodata is not None else np.zeros(values.shape, bool)
        water = values[~land]
        if water.size and not np.all(water == np.round(water)):
            warnings.append(f"{rel}: skipped -- not a region map (cell values are not whole numbers).")
            continue
        ids = np.where(land, LAND, values).astype(np.int16)
        folder = path.parent.name
        stem_key = _grid_prefix_stripped(path.stem, folder)

        if legend and "ewe_region_id" in legend[0]:
            layer = _regions_layer(rel, legend, ids, grid, crs, stem_key, warnings)
            if layer:
                layers.append(layer)
            continue
        present = set(np.unique(ids[ids != LAND]).tolist())
        if present <= {0, 1}:
            layers.append(ScannedLayer(
                rel_path=rel, key=stem_key.lower(), kind="mask", title=mask_title(stem_key),
                category="Management", grid=grid, crs_wkt=crs.to_wkt(), array=ids,
                classes=[{"id": 1, "code": stem_key.lower(), "label": mask_title(stem_key),
                          "cells": int((ids == 1).sum())}],
                details=catalog.get(path.name, {}),
            ))
            continue
        warnings.append(f"{rel}: skipped -- not a region map (no legend, and values are not only 0/1).")

    seen: set[tuple] = set()
    unique: list[ScannedLayer] = []
    for layer in layers:
        ident = (layer.key, layer.grid)
        if ident in seen:
            warnings.append(f"{layer.rel_path}: skipped -- the same layer on the same grid is already in this pack.")
            continue
        seen.add(ident)
        unique.append(layer)
    return ScannedPack(unique, warnings)


def _regions_layer(rel, legend, ids, grid, crs, stem_key, warnings) -> ScannedLayer | None:
    columns = list(legend[0])
    code_col = next((c for c in columns if c in _ICES_CODE_COLUMNS), None)
    if code_col:
        key = _ICES_CODE_COLUMNS[code_col]
        title, category = LAYER_KIND_TITLES[key], "ICES"
    else:
        code_col = next((c for c in columns if c != "ewe_region_id"), None)
        key, title, category = stem_key.lower(), mask_title(stem_key), "Other"
    if not code_col:
        warnings.append(f"{rel}: skipped -- its legend has no code column.")
        return None
    counts = dict(zip(*np.unique(ids[ids > 0], return_counts=True)))
    classes = []
    for row in legend:
        try:
            region_id = int(row["ewe_region_id"])
        except (KeyError, ValueError):
            continue
        code = row.get(code_col, "")
        if region_id <= 0 or not code:
            continue
        label = row.get("ices_area_code") or code
        cells = int(counts.get(region_id, 0))
        expected = row.get("water_cells")
        if expected and expected.isdigit() and int(expected) != cells:
            warnings.append(f"{rel}: region {code} has {cells} cells, its legend says {expected}.")
        classes.append({"id": region_id, "code": code, "label": label, "cells": cells})
    unknown = sorted(set(int(i) for i in counts) - {c["id"] for c in classes})
    if unknown:
        warnings.append(f"{rel}: region ids {unknown[:10]} are on the map but not in its legend; they are ignored.")
    classes.sort(key=lambda c: _natural_key(c["code"]))
    return ScannedLayer(
        rel_path=rel, key=key, kind="regions", title=title, category=category, grid=grid,
        crs_wkt=crs.to_wkt(), array=ids, classes=classes,
    )


def _natural_key(code: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", code)]


def build_outlines(layer_array: np.ndarray, grid: GridSignature, crs_wkt: str, classes: list[dict],
                   *, layer_id: str) -> dict:
    """One lon/lat (multi)polygon per class, traced along cell edges -- for
    drawing and clicking only; areas are always computed from the cells."""
    from rasterio.crs import CRS
    from rasterio.features import shapes
    from rasterio.warp import transform_geom

    by_id = {c["id"]: c for c in classes}
    parts: dict[int, list] = {}
    data = layer_array.astype(np.int32)
    for geom, value in shapes(data, mask=data > 0, transform=grid.transform()):
        if int(value) in by_id:
            parts.setdefault(int(value), []).append(geom["coordinates"])
    src = CRS.from_wkt(crs_wkt)
    features = []
    for region_id, polys in parts.items():
        geom = {"type": "MultiPolygon", "coordinates": polys}
        if not src.to_epsg() == 4326:
            geom = transform_geom(src, "EPSG:4326", geom)
        geom["coordinates"] = _round(geom["coordinates"])
        c = by_id[region_id]
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {"layer": layer_id, "code": c["code"], "label": c["label"], "cells": c["cells"]},
        })
    return {"type": "FeatureCollection", "features": features}


def _round(coords):
    if coords and isinstance(coords[0], (int, float)):
        return [round(coords[0], 5), round(coords[1], 5)]
    return [_round(c) for c in coords]
