"""Admin endpoint: force-rescan whichever data sources are currently active
("Reload Data" in the UI).

Source management itself (add/list/activate/forget/browse) lives in
``api/routers/sources.py``. This is a convenience wrapper over
``ingestion.activation.rescan_source`` -- "refresh everything I currently
have loaded", looped over whichever of output/input are active -- not a
third, different ingestion path: it does not change which sources are
active, and each source is still rescanned independently into its own
cache slot (see ``core/config.py``'s per-source-cache docstring). Still a
fully explicit, user-triggered action, same as the source picker's per-row
Rescan button (which touches exactly one source); this just does "all of
what's currently loaded" in one click.
"""

from __future__ import annotations

from fastapi import APIRouter

from ecosim.core.workspace import NoActiveDataSourceError, get_workspace_registry
from ecosim.ingestion.activation import rescan_source

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reload")
def reload_data() -> dict:
    """Force-rescan the active data source(s) (ignoring any existing cache)
    and rebuild the catalog. Raises 409 (via the global
    ``NoActiveDataSourceError`` handler) if no output source is active yet."""
    registry = get_workspace_registry()
    output = registry.active("output")
    if output is None:
        raise NoActiveDataSourceError(
            "No active model output data source. Register one via "
            "POST /admin/sources (kind=output) and activate it first."
        )
    input_source = registry.active("input")
    sources = [output] + ([input_source] if input_source is not None else [])

    models: list[str] = []
    scenarios: list[str] = []
    totals = {
        "datasets": 0, "rows": 0, "files_read": 0, "errors": 0,
        "rasters_indexed": 0, "spatial_errors": 0, "skipped_unsupported": 0,
    }
    for source in sources:
        # Both are active by construction, so rescan_source's own "recombine
        # only if still active" check always fires -- the live catalog is
        # fresh after this loop, no separate rebuild call needed here.
        result = rescan_source(registry, source)
        models += result.models
        scenarios += result.scenarios
        totals["datasets"] += result.datasets
        totals["rows"] += result.rows
        totals["files_read"] += result.files_read
        totals["errors"] += result.errors
        totals["rasters_indexed"] += result.rasters_indexed
        totals["spatial_errors"] += result.spatial_errors
        totals["skipped_unsupported"] += result.skipped_unsupported

    return {"status": "ok", "models": models, "scenarios": scenarios, **totals}
