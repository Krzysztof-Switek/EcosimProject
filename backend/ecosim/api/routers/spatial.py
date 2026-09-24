"""Spatial endpoints — raster layer index and COG file access."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ecosim.catalog import service
from ecosim.core.config import get_settings
from ecosim.ingestion.file_access import UnreadableFileError
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
    return service.list_rasters(scenario=scenario, variable=variable, group=group, fleet=fleet, year=year)


@router.get("/raster/{raster_id}")
def raster_file(raster_id: str) -> FileResponse:
    """Serve the Cloud-Optimized GeoTIFF for one raster index entry.

    Converts from the raw ``.asc`` on first request for this raster (~100ms)
    and caches it; every later request is served straight from disk.
    """
    row = service.get_raster(raster_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Raster not found")
    try:
        path = materialize_raster(row, get_settings())
    except UnreadableFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/tiff")
