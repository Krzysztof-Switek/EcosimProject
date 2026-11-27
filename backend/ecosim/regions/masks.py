"""An area as a set of cells of one model grid.

Area definition (JSON, grid-independent -- the same saved area works on any
grid that has the layers it names)::

    {"groups": [
        [ {"kind": "regions", "layer": "ices_subdivisions", "codes": ["25", "26"]},
          {"kind": "drawn", "geojson": {...lon/lat GeoJSON...}} ],
        [ {"kind": "regions", "layer": "03_natura2000_2024"} ]
    ]}

Items inside a group are joined (union, OR); groups are intersected (AND):
the example is (SD 25 + SD 26 + drawn polygon) ∩ Natura 2000. ``layer`` is a
layer's grid-independent ``key``; ``codes`` picks classes of a region layer
(omitted = all of them; a mask layer has no codes). A drawn polygon covers
the cells whose centre is inside it -- the rule the region packs use too.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ecosim.regions.grid import GridSignature, cell_areas_km2
from ecosim.regions.store import layer_array


class AreaError(ValueError):
    """The area can't be built on this grid -- message shown to the user."""


@dataclass
class GridContext:
    grid: GridSignature
    crs: object  # rasterio CRS -- the grid's real coordinate system
    layers: list[dict]  # region layers on this grid (store.layers_for_grid)


def _item_mask(item: dict, ctx: GridContext) -> np.ndarray:
    kind = item.get("kind")
    if kind == "regions":
        key = item.get("layer")
        layer = next((lay for lay in ctx.layers if lay["key"] == key), None)
        if layer is None:
            raise AreaError(f"The layer \"{key}\" is not available for this model's grid ({ctx.grid.describe()}).")
        arr = layer_array(layer)
        if layer["kind"] == "mask":
            return arr == 1
        codes = item.get("codes")
        by_code = {c["code"]: c["id"] for c in layer["classes"]}
        if codes is None:
            return arr > 0
        unknown = [c for c in codes if c not in by_code]
        if unknown:
            raise AreaError(f"{layer['title']}: no region {', '.join(unknown)} on this grid.")
        return np.isin(arr, [by_code[c] for c in codes])
    if kind == "drawn":
        return _drawn_mask(item.get("geojson") or {}, ctx)
    raise AreaError(f"Unknown area item kind: {kind!r}")


def _drawn_mask(geojson: dict, ctx: GridContext) -> np.ndarray:
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom

    geoms = _geometries(geojson)
    if not geoms:
        raise AreaError("The drawn area has no polygon.")
    projected = [transform_geom("EPSG:4326", ctx.crs, g) for g in geoms]
    return geometry_mask(projected, out_shape=(ctx.grid.nrows, ctx.grid.ncols),
                         transform=ctx.grid.transform(), invert=True, all_touched=False)


def _geometries(geojson: dict) -> list[dict]:
    t = geojson.get("type")
    if t == "FeatureCollection":
        return [g for f in geojson.get("features", []) for g in _geometries(f)]
    if t == "Feature":
        return _geometries(geojson.get("geometry") or {})
    if t in ("Polygon", "MultiPolygon"):
        return [geojson]
    if t == "GeometryCollection":
        return [g for sub in geojson.get("geometries", []) for g in _geometries(sub)]
    return []


def area_mask(area: dict, ctx: GridContext) -> np.ndarray:
    """``bool[nrows, ncols]``, row 0 = north (the ``.asc`` row order)."""
    groups = [g for g in area.get("groups", []) if g]
    if not groups:
        raise AreaError("The area is empty -- pick at least one region or draw a polygon.")
    result = np.ones((ctx.grid.nrows, ctx.grid.ncols), dtype=bool)
    for group in groups:
        union = np.zeros_like(result)
        for item in group:
            union |= _item_mask(item, ctx)
        result &= union
    return result


def mask_outline(mask: np.ndarray, ctx: GridContext) -> dict:
    """The area's cells as lon/lat polygons traced along cell edges -- to draw
    the area and clip a map to it (a cell is inside exactly when its centre
    is inside these polygons, so the export's centre rule gives the same cells)."""
    from rasterio.features import shapes
    from rasterio.warp import transform_geom

    polys = [g["coordinates"] for g, v in shapes(mask.astype(np.uint8), mask=mask, transform=ctx.grid.transform())
             if int(v) == 1]
    if not polys:
        return {"type": "FeatureCollection", "features": []}
    geom = {"type": "MultiPolygon", "coordinates": polys}
    if ctx.crs.to_epsg() != 4326:
        geom = transform_geom(ctx.crs, "EPSG:4326", geom)
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geom, "properties": {}}]}


def area_summary(area: dict, ctx: GridContext, *, outline: bool = False) -> dict:
    mask = area_mask(area, ctx)
    cells = int(mask.sum())
    km2 = float(cell_areas_km2(ctx.grid, ctx.crs)[mask].sum()) if cells else 0.0
    out: dict = {"cells": cells, "area_km2": round(km2, 1)}
    if outline:
        out["geojson"] = mask_outline(mask, ctx)
    return out
