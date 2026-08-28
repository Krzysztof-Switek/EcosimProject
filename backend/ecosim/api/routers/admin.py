"""Admin endpoint: re-run ingestion for whichever data sources are currently
active ("Reload Data" in the UI).

Source management itself (add/list/activate/forget/browse) lives in
``api/routers/sources.py``. This is a quick refresh of the existing
active output(+input) pair -- it does not change which sources are active
(that's what "Activate"/"Rescan" in the source picker does via
``ingestion.activation.activate_source``), it just re-scans them.
"""

from __future__ import annotations

from fastapi import APIRouter

from ecosim.catalog.build import build_catalog
from ecosim.core.config import get_settings
from ecosim.ingestion.pipeline import run_ingest
from ecosim.ingestion.spatial_pipeline import build_raster_index

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reload")
def reload_data() -> dict:
    """Re-scan the active data source(s) into the canonical store and
    rebuild the catalog (including the spatial raster index -- fast,
    index-only, see ``ecosim.ingestion.spatial_pipeline``; individual
    rasters still materialize lazily on first view). Raises 409 (via the
    global ``NoActiveDataSourceError`` handler) if no output source is
    active yet."""
    settings = get_settings()
    report = run_ingest(settings)
    spatial_report = build_raster_index(settings)
    build_catalog(settings)
    return {
        "status": "ok",
        "models": [m["id"] for m in report.models],
        "scenarios": [s["id"] for s in report.scenarios],
        "datasets": report.datasets_written,
        "rows": report.rows_written,
        "files_read": report.files_read,
        "errors": len(report.errors),
        "rasters_indexed": spatial_report.rasters_indexed,
        "spatial_errors": len(spatial_report.errors),
        "group_dictionary_found": report.group_dictionary_found and spatial_report.group_dictionary_found,
    }
