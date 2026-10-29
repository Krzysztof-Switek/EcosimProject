"""Spatial endpoints — raster layer index and COG file access."""

from __future__ import annotations

import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ecosim.catalog import service
from ecosim.core.config import get_settings
from ecosim.core.workspace import get_workspace_registry
from ecosim.export.spatial_ascii import ExportArea, name_part, write_ascii_zip
from ecosim.ingestion.file_access import UnreadableFileError
from ecosim.ingestion.parsers.asc_grid import MapCrsError
from ecosim.ingestion.spatial_pipeline import materialize_raster

router = APIRouter(prefix="/spatial", tags=["spatial"])


@router.get("/layers")
def layers() -> list[dict]:
    """Spatial variables available per (model, scenario) — the browse index."""
    return service.list_raster_layers()


@router.get("/rasters")
def rasters(
    scenario: str,
    variable: str,
    group: str | None = None,
    fleet: str | None = None,
    year: int | None = None,
) -> list[dict]:
    rows = service.list_rasters(scenario=scenario, variable=variable, group=group, fleet=fleet, year=year)
    # Only what the browser uses: the full rows also carry each map's source
    # path and its run's whole CRS WKT, which made one variable's list ~1.7 MB
    # (Biomass, 21 groups x 95 years) -- slow, and through the dev proxy such
    # responses were intermittently reset, leaving the map view empty.
    return [{k: r.get(k) for k in _RASTER_FIELDS} for r in rows]


_RASTER_FIELDS = (
    "id", "model", "model_name", "scenario", "domain", "variable",
    "group_id", "group_name", "fleet_id", "fleet_name", "year",
)


@router.get("/raster/{raster_id}")
def raster_file(raster_id: str) -> FileResponse:
    """Serve the Cloud-Optimized GeoTIFF for one raster index entry.

    Converts from the raw ``.asc`` on first request for this raster (~100ms)
    and caches it; every later request is served straight from disk.
    """
    row = service.get_raster(raster_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Raster not found")
    source = get_workspace_registry().active("input" if row["domain"] == "input" else "output")
    try:
        path = materialize_raster(row, get_settings(), map_crs=source.map_crs if source else None)
    except UnreadableFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MapCrsError as exc:
        # Structured, so the map can offer to fix it (pick the real CRS) instead
        # of only showing an error -- see asc_grid.MapCrsError.
        raise HTTPException(status_code=422, detail={
            "code": "map_crs_mismatch",
            "message": str(exc),
            "source_id": source.id if source else None,
            "source_name": source.name if source else None,
            "crs": exc.crs,
            "bounds": list(exc.bounds),
            "candidates": exc.candidates,
        }) from exc
    return FileResponse(path, media_type="image/tiff")


class ExportAreaIn(BaseModel):
    name: str
    geojson: dict


class AsciiExportItem(BaseModel):
    variable: str
    # Checked group/fleet names; the variable's maps of other groups/fleets are
    # left out (ignored for a variable without groups/fleets).
    entities: list[str] = []
    year_from: int
    year_to: int


class AsciiExportIn(BaseModel):
    scenario: str
    # Each variable with its own groups/fleets and year range (chosen per
    # variable in the spatial view).
    items: list[AsciiExportItem]
    # Areas of interest (lon/lat GeoJSON); none = the whole model grid.
    areas: list[ExportAreaIn] = []


@router.post("/export/ascii")
def export_ascii(body: AsciiExportIn) -> StreamingResponse:
    """The selected maps as ESRI ASCII grids in a zip: the model's own grid and
    values, cropped to each area of interest separately (see
    export/spatial_ascii.py). Reads the raw ``.asc`` files, one per (variable,
    group/fleet, year) -- a few seconds for a long series."""
    rows: list[dict] = []
    variables: list[dict] = []
    for item in body.items:
        wanted = set(item.entities)
        candidates = [
            r for r in service.list_rasters(scenario=body.scenario, variable=item.variable)
            if item.year_from <= r["year"] <= item.year_to
        ]
        picked = [r for r in candidates
                  if not (r.get("group_name") or r.get("fleet_name"))
                  or (r.get("group_name") or r.get("fleet_name")) in wanted]
        rows += picked
        variables.append({
            "variable": item.variable,
            "groups_or_fleets": sorted(wanted) or "all",
            "years": f"{item.year_from}-{item.year_to}",
            "maps": len(picked),
        })
    if not rows:
        raise HTTPException(status_code=422, detail="Nothing to export for this selection.")

    domain = rows[0]["domain"]
    source = get_workspace_registry().active("input" if domain == "input" else "output")
    selection = {
        "model": rows[0].get("model_name") or rows[0].get("model"),
        "scenario": body.scenario,
        "areas": [a.name for a in body.areas] or ["full-area (whole model grid)"],
        "data_source": source.name if source else None,
        "variables": variables,
    }

    out = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    try:
        write_ascii_zip(
            out, rows,
            areas=[ExportArea(a.name, a.geojson) for a in body.areas],
            map_crs=source.map_crs if source else None,
            selection=selection,
        )
    except (UnreadableFileError, MapCrsError) as exc:
        out.close()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out.seek(0)
    filename = f"ecosim_ascii__{name_part(body.scenario)}.zip"
    return StreamingResponse(
        out, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(out.close),
    )
