"""Reference areas: region packs in the profile, their layers on the active
data's grid, and areas (region combinations / drawn polygons) as cells."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ecosim.regions import store
from ecosim.regions.datagrid import scenario_grid
from ecosim.regions.masks import AreaError, area_summary

router = APIRouter(prefix="/regions", tags=["regions"])

_LAYER_FIELDS = ("id", "pack_id", "key", "kind", "title", "category", "grid", "crs", "classes", "details")


def _public(layer: dict) -> dict:
    return {k: layer.get(k) for k in _LAYER_FIELDS}


def _pack_out(pack: dict) -> dict:
    return {
        "id": pack["id"],
        "name": pack["name"],
        "source_path": pack["source_path"],
        "imported_at": pack["imported_at"],
        "warnings": pack.get("warnings", []),
        "layers": [_public(layer) for layer in pack["layers"]],
    }


@router.get("/packs")
def packs() -> list[dict]:
    return [_pack_out(p) for p in store.list_packs()]


class PackIn(BaseModel):
    path: str
    name: str | None = None


@router.post("/packs")
def import_pack(body: PackIn) -> dict:
    """Copy a folder or .zip of region maps into the profile (replaces an
    earlier import of the same path). Takes a few seconds: every map is read
    and its outlines traced."""
    path = Path(body.path).resolve()
    root = os.environ.get("ECOSIM_BROWSE_ROOT")  # same limit as GET /admin/browse
    if root:
        try:
            path.relative_to(Path(root).resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Path is outside the allowed browse root") from None
    try:
        return _pack_out(store.import_pack(path, body.name))
    except store.RegionPackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/packs/{pack_id}")
def remove_pack(pack_id: str) -> dict:
    if not store.remove_pack(pack_id):
        raise HTTPException(status_code=404, detail="No such region pack.")
    return {"removed": pack_id}


@router.get("/layers")
def layers(scenario: str | None = None, domain: str = "output") -> dict:
    """Without ``scenario``: every layer. With it: the layers on that
    scenario's grid, plus how the grid was matched (``grid.status``)."""
    if scenario is None:
        return {"grid": None, "layers": [_public(layer) for layer in store.list_layers()]}
    data_grid = scenario_grid(scenario, domain)
    return {"grid": data_grid.to_dict(), "layers": [_public(layer) for layer in data_grid.layers]}


@router.get("/layers/{layer_id}/outlines")
def outlines(layer_id: str) -> dict:
    layer = store.get_layer(layer_id)
    if layer is None:
        raise HTTPException(status_code=404, detail="No such region layer.")
    return store.layer_outlines(layer)


class AreaIn(BaseModel):
    scenario: str
    domain: str = "output"
    area: dict
    # Also return the area's cells as lon/lat polygons (to draw / clip a map).
    outline: bool = False


@router.post("/area/summary")
def summary(body: AreaIn) -> dict:
    """How many cells (and km²) an area covers on the scenario's grid."""
    data_grid = scenario_grid(body.scenario, body.domain)
    ctx = data_grid.context()
    if ctx is None:
        raise HTTPException(status_code=422, detail=data_grid.message or "The model's grid is unknown.")
    try:
        return {**area_summary(body.area, ctx, outline=body.outline), "grid": data_grid.to_dict()}
    except AreaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
