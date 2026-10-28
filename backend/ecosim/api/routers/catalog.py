"""Catalog endpoints — the navigable index for the UI."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ecosim.catalog import service

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/models")
def models() -> list[dict]:
    """Ecopath models (step 1) with the Ecosim scenarios under each (step 2)."""
    return service.list_models()


@router.get("/scenarios")
def scenarios() -> list[dict]:
    return service.list_scenarios()


@router.get("/tree")
def tree() -> list[dict]:
    """Full navigation tree: scenario -> domain -> variables."""
    return service.get_scenario_tree()


@router.get("/groups")
def groups(
    variable: list[str] = Query(..., description="One or more canonical variable slugs"),
    freq: str = Query("annual", pattern="^(annual|monthly)$"),
    scenario: list[str] | None = Query(None, description="One or more scenario ids"),
) -> list[dict]:
    """Functional groups present in these variables' data (step 5 of the time-series
    navigator): EwE group number (``id``), its ``name`` where EwE wrote one, and which
    variables it occurs in."""
    return service.list_dimension(dimension="group", variable=variable, freq=freq, scenario=scenario)


@router.get("/fleets")
def fleets(
    variable: list[str] = Query(..., description="One or more canonical variable slugs"),
    freq: str = Query("annual", pattern="^(annual|monthly)$"),
    scenario: list[str] | None = Query(None, description="One or more scenario ids"),
) -> list[dict]:
    """Fleets present in these variables' data (step 6 of the time-series navigator),
    same shape as ``/catalog/groups``."""
    return service.list_dimension(dimension="fleet", variable=variable, freq=freq, scenario=scenario)


@router.get("/datasets")
def datasets(scenario: str | None = None) -> list[dict]:
    return service.list_datasets(scenario=scenario)
