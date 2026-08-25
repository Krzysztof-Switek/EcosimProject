"""Admin endpoint: re-run ingestion from the UI ("Reload Data" button).

Runs the pipeline in-process (same process as the API), so rebuilding the
DuckDB catalog does not fight a second process for the write lock. Defined as a
sync handler so FastAPI runs it in a worker thread (the event loop stays free).
"""

from __future__ import annotations

from fastapi import APIRouter

from ecosim.core.config import get_settings
from ecosim.ingestion.pipeline import run_ingest
from ecosim.ingestion.spatial_pipeline import build_raster_index

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reload")
def reload_data() -> dict:
    """Re-scan DataEcosim/ into the canonical store and rebuild the catalog.

    Also rebuilds the spatial raster index (fast -- no COG conversion, see
    ecosim.ingestion.spatial_pipeline) so newly-arrived .asc scenarios show up
    immediately; individual rasters still materialize lazily on first view.
    """
    settings = get_settings()
    report = run_ingest(settings)  # rebuilds the catalog itself, before the raster index below exists
    spatial_report = build_raster_index(settings)

    from ecosim.catalog.build import build_catalog

    build_catalog(settings)  # rebuild again so the fresh raster_index.csv is loaded as catalog_rasters
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
    }
