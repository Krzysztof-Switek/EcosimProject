"""Time-series endpoint — tidy rows for charts and scenario comparison."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ecosim.catalog import service

router = APIRouter(prefix="/timeseries", tags=["timeseries"])


@router.get("")
def timeseries(
    variable: str = Query(..., description="Canonical variable slug, e.g. 'biomass'"),
    freq: str = Query("annual", pattern="^(annual|monthly)$"),
    model: list[str] | None = Query(None, description="One or more Ecopath model ids"),
    scenario: list[str] | None = Query(None, description="One or more scenario ids"),
    group: list[str] | None = Query(None, description="Group names (case-insensitive)"),
    fleet: list[str] | None = Query(None, description="Fleet names (case-insensitive)"),
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
        fleet=fleet,
        year_from=year_from,
        year_to=year_to,
        month_from=month_from,
        month_to=month_to,
    )
    return {"count": len(rows), "variable": variable, "freq": freq, "rows": rows}
