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


@router.get("/selection")
def selection(
    category: str = Query(..., description="Results-Extractor box, e.g. 'prey_with_predators'"),
    variable: list[str] = Query(..., description="The box's checked variables"),
    freq: str = Query("annual", pattern="^(annual|monthly)$"),
    scenario: list[str] | None = Query(None, description="One or more scenario ids"),
) -> list[dict]:
    """The box's selection window (time-series step 5): its groups or fleets present
    in these variables' data and, in an "attached" box, each one's partners."""
    return service.list_selection_options(category=category, variable=variable, freq=freq, scenario=scenario)


@router.get("/runs")
def runs(scenario: list[str] | None = Query(None, description="One or more scenario ids")) -> list[dict]:
    """Monte Carlo / Ecosampler runs of these scenarios (none for ordinary output)."""
    return service.list_runs(scenario=scenario)


@router.get("/datasets")
def datasets(scenario: str | None = None) -> list[dict]:
    return service.list_datasets(scenario=scenario)
