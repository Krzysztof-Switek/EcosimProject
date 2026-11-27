"""Analysis plugin listing + run endpoints (Etap 3 — R analyses).

The selected data itself is downloaded through ``POST /timeseries/export``.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ecosim.analyses import registry, runner
from ecosim.core.config import get_settings

router = APIRouter(prefix="/analyses", tags=["analyses"])


def r_disabled() -> bool:
    """``ECOSIM_DISABLE_R=1`` turns R analyses off -- on a shared server until
    running R safely is designed (an R script runs with the server's rights)."""
    return os.environ.get("ECOSIM_DISABLE_R", "").lower() in ("1", "true", "yes")


class RunRequest(BaseModel):
    manifest: dict = {}
    params: dict = {}


def _public(spec: registry.AnalysisSpec) -> dict:
    # `dir` is a server-local filesystem path -- not the client's business.
    return spec.model_dump(exclude={"dir"})


@router.get("")
def list_analyses(variable: list[str] | None = Query(None), context: str | None = None) -> list[dict]:
    """All registered analyses, or (with `variable` given) only the ones whose
    declared requirements are met by that set -- e.g. what a caller currently
    has selected in the time-series basket. ``context`` (timeseries / spatial)
    keeps those run from that view. None when R is turned off."""
    if r_disabled():
        return []
    specs = registry.list_analyses()
    if context:
        specs = [s for s in specs if s.context == context]
    if variable:
        specs = [s for s in specs if s.is_compatible(set(variable))]
    return [_public(s) for s in specs]


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    spec = registry.get_analysis(analysis_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _public(spec)


@router.post("/{analysis_id}/run")
def run_analysis(analysis_id: str, body: RunRequest) -> dict:
    if r_disabled():
        raise HTTPException(status_code=403, detail="R analyses are turned off on this server.")
    spec = registry.get_analysis(analysis_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    try:
        return runner.run_analysis(spec, body.manifest, body.params)
    except runner.AnalysisRunError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/jobs/{job_id}/artifact/{artifact_path:path}")
def get_artifact(job_id: str, artifact_path: str) -> FileResponse:
    """Serve one file an analysis wrote under its job's out/ (a figure, a table…)."""
    settings = get_settings()
    out_dir = (settings.jobs_dir / job_id / "out").resolve()
    target = (out_dir / artifact_path).resolve()
    # Reject anything that escapes out/ (e.g. "../../secrets") -- job_id and
    # artifact_path both come straight from the client.
    if out_dir not in target.parents and target != out_dir:
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(target)
