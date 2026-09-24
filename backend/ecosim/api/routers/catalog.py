"""Catalog endpoints — the navigable index for the UI."""

from __future__ import annotations

from fastapi import APIRouter

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


@router.get("/datasets")
def datasets(scenario: str | None = None) -> list[dict]:
    return service.list_datasets(scenario=scenario)
