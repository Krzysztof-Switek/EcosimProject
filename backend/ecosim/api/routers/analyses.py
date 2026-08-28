"""Analysis plugin listing + run endpoints (Etap 3 — R analyses).

Also: plain data export (no R involved) -- the same manifest that can drive an
analysis can instead just be downloaded, for anyone who'd rather work in their
own tool. See rows_for_manifest() in analyses/runner.py.
"""

from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ecosim.analyses import registry, runner
from ecosim.core.config import get_settings

router = APIRouter(prefix="/analyses", tags=["analyses"])


class RunRequest(BaseModel):
    manifest: dict = {}
    params: dict = {}


class ExportRequest(BaseModel):
    manifest: dict = {}


def _public(spec: registry.AnalysisSpec) -> dict:
    # `dir` is a server-local filesystem path -- not the client's business.
    return spec.model_dump(exclude={"dir"})


@router.get("")
def list_analyses(variable: list[str] | None = Query(None)) -> list[dict]:
    """All registered analyses, or (with `variable` given) only the ones whose
    declared requirements are met by that set -- e.g. what a caller currently
    has selected in the time-series basket."""
    specs = registry.list_analyses()
    if variable:
        specs = [s for s in specs if s.is_compatible(set(variable))]
    return [_public(s) for s in specs]


@router.post("/export")
def export_data(body: ExportRequest) -> StreamingResponse:
    """Download exactly what a manifest selects as CSV -- no R, no sandbox."""
    rows = runner.rows_for_manifest(body.manifest)
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ecosim_export.csv"},
    )


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    spec = registry.get_analysis(analysis_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _public(spec)


@router.post("/{analysis_id}/run")
def run_analysis(analysis_id: str, body: RunRequest) -> dict:
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
