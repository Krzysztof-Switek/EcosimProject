"""The user's saved areas of interest (regions/library.py)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ecosim.regions.library import load_library, save_library

router = APIRouter(prefix="/areas", tags=["areas"])


class SavedArea(BaseModel):
    id: str
    name: str
    area: dict  # {"groups": [[item, ...], ...]}, see regions/masks.py


class Library(BaseModel):
    areas: list[SavedArea]
    selected: list[str] = []


@router.get("")
def get_areas() -> dict:
    return load_library()


@router.put("")
def put_areas(body: Library) -> dict:
    return save_library([a.model_dump() for a in body.areas], body.selected)
