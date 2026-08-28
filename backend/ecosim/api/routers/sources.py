"""Data-source registry API: register, list, activate and forget the
network-share/local directories the app reads raw EwE model output/input
data from.

See ``docs/Plans and TO_DO lists/27.08_data_upload_PLAN.md`` for the design
and ``docs/data-contract.md``'s "Oczekiwany układ katalogów źródłowych" for
the folder-layout convention validated below. Activating a source runs the
same ingestion pipeline the old fixed-path ``/admin/reload`` used to
(``ingestion.activation.activate_source``) -- just against whichever
sources are now active, into the single shared canonical store.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ecosim.core.workspace import DataSource, SourceKind, get_workspace_registry
from ecosim.ingestion.activation import ActivationError, activate_source
from ecosim.ingestion.pipeline import validate_input_root, validate_output_root

router = APIRouter(prefix="/admin", tags=["admin"])


class SourceOut(BaseModel):
    id: str
    name: str
    path: str
    kind: SourceKind
    added_at: datetime
    last_scanned_at: datetime | None
    status: str
    error: str | None
    active: bool

    @classmethod
    def from_source(cls, source: DataSource, *, active: bool) -> "SourceOut":
        return cls(
            id=source.id,
            name=source.name,
            path=str(source.path),
            kind=source.kind,
            added_at=source.added_at,
            last_scanned_at=source.last_scanned_at,
            status=source.status,
            error=source.error,
            active=active,
        )


class AddSourceIn(BaseModel):
    name: str
    path: str
    kind: Literal["output", "input"]


class BrowseEntry(BaseModel):
    name: str
    path: str
    looks_like_source: bool


class BrowseOut(BaseModel):
    path: str
    parent: str | None
    entries: list[BrowseEntry]
    is_drives_list: bool = False


# Sentinel passed as `path` (never a real filesystem path -- intercepted
# before any path resolution) to request the Windows drive list, and
# returned as `parent` when browsing is at a drive root (e.g. C:\) so the
# "up" button can get back to it. Windows has no single root the way Unix
# has "/", so without this a mapped network drive (a common way a shared
# folder actually reaches this app -- see the plan doc) would never be
# reachable by clicking, only by pasting its path directly.
_DRIVES = "__DRIVES__"


def _list_windows_drives() -> list[BrowseEntry]:
    import string

    drives = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:/")
        try:
            if root.is_dir():
                drives.append(BrowseEntry(name=f"{letter}:\\", path=str(root), looks_like_source=False))
        except OSError:
            continue
    return drives


def _looks_like_ewe_export(path: Path) -> bool:
    """Cheap, top-level-only sniff test to hint the folder picker -- not full
    validation (that's ``validate_output_root``/``validate_input_root``, which
    scan recursively at add-time). EwE has no fixed output folder name (see
    docs/ewe-data-formats.md), so this deliberately does NOT require an
    'output'/'input' folder -- it's just a shortcut for the common case, and a
    folder without this hint can still be perfectly valid. Doesn't check for
    Mapa_grupy_fleets.xlsx: that dictionary is this project's own convention,
    not evidence a folder holds real EwE data."""
    try:
        entries = list(path.iterdir())
    except OSError:
        return False
    names = {p.name for p in entries}
    if "output" in names or "input" in names:
        return True
    return any(p.suffix.lower() in (".csv", ".asc") for p in entries if p.is_file())


@router.get("/sources", response_model=list[SourceOut])
def list_sources(kind: SourceKind | None = None) -> list[SourceOut]:
    registry = get_workspace_registry()
    active_ids = {s.id for s in (registry.active("output"), registry.active("input")) if s is not None}
    return [SourceOut.from_source(s, active=s.id in active_ids) for s in registry.list_sources(kind=kind)]


@router.post("/sources", response_model=SourceOut)
def add_source(body: AddSourceIn) -> SourceOut:
    registry = get_workspace_registry()
    path = Path(body.path)
    if not path.is_dir():
        raise HTTPException(422, f"Not a reachable directory: {body.path}")

    validator = validate_output_root if body.kind == "output" else validate_input_root
    problems = validator(path)
    if problems:
        raise HTTPException(422, " ".join(problems))

    name = body.name.strip() or path.name
    source = registry.add_source(name, path, body.kind)
    return SourceOut.from_source(source, active=False)  # never active immediately after adding


@router.post("/sources/{source_id}/activate")
def activate_source_endpoint(source_id: str) -> dict:
    registry = get_workspace_registry()
    source = registry.get(source_id)
    if source is None:
        raise HTTPException(404, f"Unknown data source: {source_id}")
    try:
        result = activate_source(registry, source)
    except ActivationError as exc:
        raise HTTPException(422, f"Ingestion failed: {exc}") from exc
    return {"status": "ok", **asdict(result)}


@router.delete("/sources/{source_id}")
def remove_source(source_id: str) -> dict:
    registry = get_workspace_registry()
    if registry.get(source_id) is None:
        raise HTTPException(404, f"Unknown data source: {source_id}")
    registry.remove_source(source_id)
    return {"status": "ok"}


@router.get("/browse", response_model=BrowseOut)
def browse(path: str | None = None) -> BrowseOut:
    """Server-side directory listing for the folder-picker UI -- the browser
    has no way to hand the backend a real filesystem path, so the picker asks
    the backend what it can see instead.

    Constrained to ``ECOSIM_BROWSE_ROOT`` when set (required on a shared
    server, so one user can't browse another's files via this endpoint --
    see the plan doc §4.2). Unset = local/dev mode: defaults to the user's
    home folder (most model data ends up somewhere under there), with the
    Windows drive list (mapped network drives included) reachable via the
    ``_DRIVES`` sentinel -- the frontend always shows a "This PC" shortcut
    for it, not just via repeated "up" clicks from wherever browsing is.
    """
    root_override = os.environ.get("ECOSIM_BROWSE_ROOT")
    allowed_root = Path(root_override).resolve() if root_override else None
    on_windows = os.name == "nt"

    if path == _DRIVES:
        if allowed_root is not None:
            raise HTTPException(403, "Path is outside the allowed browse root")
        return BrowseOut(path="This PC", parent=None, entries=_list_windows_drives(), is_drives_list=True)

    target = Path(path).resolve() if path else (allowed_root or Path.home())
    if allowed_root is not None:
        try:
            target.relative_to(allowed_root)
        except ValueError:
            raise HTTPException(403, "Path is outside the allowed browse root") from None

    if not target.is_dir():
        raise HTTPException(404, f"Not a directory: {target}")

    try:
        children = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise HTTPException(403, f"Cannot list directory: {exc}") from exc

    entries = [
        BrowseEntry(name=child.name, path=str(child), looks_like_source=_looks_like_ewe_export(child))
        for child in children
        if child.is_dir() and not child.name.startswith(".")
    ]

    parent = target.parent
    if on_windows and allowed_root is None and parent == target:
        parent_str = _DRIVES
    elif parent == target or (allowed_root is not None and parent == allowed_root.parent):
        parent_str = None
    else:
        parent_str = str(parent)
    return BrowseOut(path=str(target), parent=parent_str, entries=entries)
