"""Admin endpoint: re-run ingestion from the UI ("Reload Data" button).

Runs the pipeline in-process (same process as the API), so rebuilding the
DuckDB catalog does not fight a second process for the write lock. Defined as a
sync handler so FastAPI runs it in a worker thread (the event loop stays free).
"""

from __future__ import annotations

from fastapi import APIRouter

from ecosim.core.config import get_settings
from ecosim.ingestion.pipeline import run_ingest

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reload")
def reload_data() -> dict:
    """Re-scan DataEcosim/ into the canonical store and rebuild the catalog."""
    report = run_ingest(get_settings())
    return {
        "status": "ok",
        "scenarios": [s["id"] for s in report.scenarios],
        "datasets": report.datasets_written,
        "rows": report.rows_written,
        "files_read": report.files_read,
        "errors": len(report.errors),
    }
