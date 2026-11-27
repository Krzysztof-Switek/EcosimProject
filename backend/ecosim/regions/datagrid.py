"""Which grid a scenario's maps are on, and which region layers fit it.

The grid is read from the six-line header of one of the scenario's own
``.asc`` maps that is already on this computer -- never a cloud-only one
(reading it would download it, see ingestion/file_access.py). Any map the
user has opened in the spatial view is local, so in practice one exists.

The grid's real CRS: a matching region pack's ``.prj`` (checked by its
authors), else the data source's user-set CRS, else the CRS EwE declared.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ecosim.ingestion.file_access import is_cloud_only
from ecosim.regions.grid import GridSignature, read_asc_header
from ecosim.regions.masks import GridContext
from ecosim.regions.store import layers_for_grid

_MAX_PATHS_CHECKED = 5000


@dataclass
class DataGrid:
    status: str  # "matched" | "no_match" | "unknown"
    message: str | None
    grid: GridSignature | None = None
    crs: object | None = None
    crs_label: str | None = None
    layers: list[dict] = field(default_factory=list)

    def context(self) -> GridContext | None:
        if self.grid is None or self.crs is None:
            return None
        return GridContext(self.grid, self.crs, self.layers)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "grid": self.grid.to_dict() if self.grid else None,
            "crs": self.crs_label,
        }


def first_local_grid(rows: list[dict]) -> tuple[GridSignature, dict] | None:
    for row in rows[:_MAX_PATHS_CHECKED]:
        path = Path(row["source_path"])
        if os.path.exists(path) and not is_cloud_only(path):
            try:
                return read_asc_header(path), row
            except (OSError, ValueError):
                continue
    return None


def resolve_grid(rows: list[dict], *, map_crs: str | None = None) -> DataGrid:
    """``rows``: the scenario's ``{source_path, source_crs_wkt}`` (catalog
    ``raster_sources``); ``map_crs``: the data source's user-set CRS."""
    from rasterio.crs import CRS

    from ecosim.ingestion.parsers.asc_grid import MapCrsError, grid_crs

    if not rows:
        return DataGrid("unknown", "This scenario has no maps, so areas can't be applied to it.")
    found = first_local_grid(rows)
    if found is None:
        return DataGrid("unknown", "None of this scenario's maps is on this computer yet. "
                                   "Show one map first; the reference areas will then be matched to its grid.")
    grid, row = found
    layers = layers_for_grid(grid)
    if layers:
        crs = CRS.from_wkt(layers[0]["crs_wkt"])
        label = layers[0]["crs"]
        return DataGrid("matched", None, grid, crs, label, layers)
    try:
        crs = grid_crs(Path(row["source_path"]).name, grid.bounds(),
                       source_crs_wkt=row.get("source_crs_wkt"), map_crs=map_crs)
        epsg = crs.to_epsg()
        label = f"EPSG:{epsg}" if epsg else crs.to_string()
    except MapCrsError:
        crs, label = None, None
    msg = (f"No reference areas match this model's grid ({grid.describe()}"
           f"{', ' + label if label else ''}). Load a map pack made for this grid.")
    return DataGrid("no_match", msg, grid, crs, label, [])


def scenario_grid(scenario: str, domain: str = "output") -> DataGrid:
    from ecosim.catalog import service
    from ecosim.core.workspace import get_workspace_registry

    source = get_workspace_registry().active("input" if domain == "input" else "output")
    rows = service.raster_sources(scenario, domain)
    return resolve_grid(rows, map_crs=source.map_crs if source else None)
