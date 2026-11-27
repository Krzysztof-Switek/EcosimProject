"""Time-series endpoint — tidy rows for charts and scenario comparison."""

from __future__ import annotations

import tempfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ecosim.catalog import service
from ecosim.catalog.categories import CATEGORY_ORDER
from ecosim.catalog.runs import run_label
from ecosim.core.workspace import get_workspace_registry
from ecosim.export.timeseries_csv import range_label, time_label, write_timeseries_zip

router = APIRouter(prefix="/timeseries", tags=["timeseries"])


@router.get("")
def timeseries(
    variable: str = Query(..., description="Canonical variable slug, e.g. 'biomass'"),
    freq: str = Query("annual", pattern="^(annual|monthly)$"),
    model: list[str] | None = Query(None, description="One or more Ecopath model ids"),
    scenario: list[str] | None = Query(None, description="One or more scenario ids"),
    group: list[str] | None = Query(None, description="Group names (case-insensitive)"),
    group_id: list[int] | None = Query(None, description="EwE group numbers"),
    fleet: list[str] | None = Query(None, description="Fleet names (case-insensitive)"),
    fleet_id: list[int] | None = Query(None, description="EwE fleet numbers"),
    year_from: int | None = None,
    year_to: int | None = None,
    month_from: int | None = Query(None, ge=1, le=12, description="Month-of-year lower bound (monthly)"),
    month_to: int | None = Query(None, ge=1, le=12, description="Month-of-year upper bound (monthly)"),
) -> dict:
    rows = service.query_timeseries(
        variable=variable,
        freq=freq,
        model=model,
        scenario=scenario,
        group=group,
        group_id=group_id,
        fleet=fleet,
        fleet_id=fleet_id,
        year_from=year_from,
        year_to=year_to,
        month_from=month_from,
        month_to=month_to,
    )
    return {"count": len(rows), "variable": variable, "freq": freq, "rows": rows}


class RangeIn(BaseModel):
    freq: str = "annual"
    # Monte Carlo: one run (a run_id from /catalog/runs); none = the baseline run
    # with the samples' 5th-95th percentile (see service.query_timeseries).
    run: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    month_from: int | None = None
    month_to: int | None = None


class TimeseriesQueryIn(RangeIn):
    variable: str
    scenario: list[str] | None = None
    # The selection of the variable's Results-Extractor box: [parent] or
    # [parent, partner] keys from /catalog/selection. A body, not a query
    # string: every predator x prey pair of a box can be thousands of characters.
    picks: list[list[str]] | None = None


@router.post("")
def timeseries_query(body: TimeseriesQueryIn) -> dict:
    """``GET /timeseries`` with a Results-Extractor box selection (``picks``)."""
    rows = service.query_timeseries(
        variable=body.variable, freq=body.freq, scenario=body.scenario, picks=body.picks,
        run=body.run, year_from=body.year_from, year_to=body.year_to,
        month_from=body.month_from, month_to=body.month_to,
    )
    return {"count": len(rows), "variable": body.variable, "freq": body.freq, "rows": rows}


class ExportItemIn(BaseModel):
    variable: str
    scenarios: list[str]
    picks: list[list[str]] | None = None
    # How the picks read to a person (e.g. "AdCod_3: Sprat, Herring"), for the README.
    selection: str = "all"


class TimeseriesExportIn(RangeIn):
    # The Results Extractor's "Yearly": the mean over the year of monthly data.
    yearly: bool = False
    items: list[ExportItemIn]


_BOX_LABELS = dict(CATEGORY_ORDER)


@router.post("/export")
def export_csv(body: TimeseriesExportIn) -> StreamingResponse:
    """The selected series as CSV files in a zip, one per variable -- the Results
    Extractor's "Save Results" (see export/timeseries_csv.py)."""
    datasets = {d["variable"]: d for d in service.list_datasets() if d["freq"] == body.freq}
    items = []
    for item in body.items:
        dataset = datasets.get(item.variable) or {}
        items.append({
            "variable": item.variable,
            "label": dataset.get("label") or item.variable,
            "category": dataset.get("category"),
            "box": _BOX_LABELS.get(dataset.get("category")),
            "scenarios": item.scenarios,
            "selection": item.selection,
            "rows": service.query_timeseries(
                variable=item.variable, freq=body.freq, scenario=item.scenarios, picks=item.picks,
                run=body.run, year_from=body.year_from, year_to=body.year_to,
                month_from=body.month_from, month_to=body.month_to,
            ),
        })
    if not any(i["rows"] for i in items):
        raise HTTPException(status_code=422, detail="Nothing to export for this selection.")

    source = get_workspace_registry().active("output")
    years = range_label(body.year_from, body.year_to, body.month_from, body.month_to)
    out = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    write_timeseries_zip(out, items, selection={
        "freq": body.freq, "yearly": body.yearly, "years": years,
        "data_source": source.name if source else None,
        "runs": run_label(body.run) if body.run else None,
    })
    out.seek(0)
    filename = f"ecosim_timeseries__{time_label(body.freq, body.yearly)}__{years}.zip"
    return StreamingResponse(
        out, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(out.close),
    )
