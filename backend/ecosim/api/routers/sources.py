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

from ecosim.core.config import dir_size_bytes, source_cache_dir
from ecosim.core.workspace import DataSource, SourceKind, get_workspace_registry
from ecosim.ingestion.activation import (
    get_activation_progress,
    get_running_activation,
    remove_source_and_rebuild,
    request_cancel,
    scan_warnings,
    start_activation,
    start_rescan,
)
from ecosim.ingestion.file_access import can_make_local, cloud_only_message, scan_local_availability
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
    data_kind: str | None = None
    run_count: int = 1
    scan_duration_seconds: float | None = None
    # Total size on disk of this source's own cache slot (sources/<id>/) --
    # NOT the shared live store (catalog.duckdb, materialized COGs), which
    # isn't attributable to one specific source. 0 for a never-scanned
    # source. See core/config.py::dir_size_bytes.
    cache_size_bytes: int = 0
    # What the last successful scan found but did NOT load -- see
    # ingestion.activation.ActivationResult.warnings. Empty when everything
    # found was loaded (and for scans recorded before this field existed).
    scan_warnings: list[str] = []

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
            data_kind=source.data_kind,
            run_count=source.run_count,
            scan_duration_seconds=source.scan_duration_seconds,
            cache_size_bytes=dir_size_bytes(source_cache_dir(source.id)),
            scan_warnings=scan_warnings(source.id) if source.status == "ok" else [],
        )


class AddSourceIn(BaseModel):
    name: str
    path: str
    kind: Literal["output", "input"]
    # The user chose "Download and scan" for a folder whose files aren't on
    # this computer yet -- see DataSource.keep_local. Without it, such a
    # folder is refused (409 "not_local") before anything is registered.
    keep_local: bool = False


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
    folder without this hint can still be perfectly valid."""
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

    # Before anything is registered or read: are the files actually on this
    # computer? (Attributes only -- a few seconds even for ~160k files, and
    # it never triggers a download itself.) If not, nothing is registered;
    # the UI explains and offers "Download and scan" (keep_local=True).
    # This is information, not a failure -- hence a structured 409 the
    # panel turns into a notice, instead of a failed-scan row.
    if not body.keep_local:
        availability = scan_local_availability(path)
        if availability.cloud_only:
            raise HTTPException(409, {
                "code": "not_local",
                "message": cloud_only_message(availability, path),
                "cloud_only_files": availability.cloud_only,
                "cloud_only_bytes": availability.cloud_only_bytes,
                "files_checked": availability.files_checked,
                "can_download": can_make_local(),
            })

    validator = validate_output_root if body.kind == "output" else validate_input_root
    problems = validator(path)
    if problems:
        raise HTTPException(422, " ".join(problems))

    name = body.name.strip() or path.name
    source = registry.add_source(name, path, body.kind, keep_local=body.keep_local)
    return SourceOut.from_source(source, active=False)  # never active immediately after adding


@router.post("/sources/{source_id}/activate")
def activate_source_endpoint(source_id: str) -> dict:
    """Starts activation in the background and returns immediately. If this
    source's own ingest cache is already valid (a previously successful
    scan, see ``ingestion.activation._cache_is_valid``), this is near-
    instant -- no raw-file re-scan, just recombining the live store from
    whichever sources are active. Otherwise it's the slow, full ingest path
    (verified 2026-08-28: ~400GB/800k+ files can take close to an hour).
    Poll ``GET .../activation-status`` for live progress and the final
    result/error either way; this response only confirms the attempt was
    accepted."""
    registry = get_workspace_registry()
    source = registry.get(source_id)
    if source is None:
        raise HTTPException(404, f"Unknown data source: {source_id}")
    running = get_running_activation()
    if running is not None:
        # Global, not per-source: the combine step at the end of any
        # activation/rescan writes to ONE shared live store, so two
        # operations racing would corrupt each other's partial writes.
        raise HTTPException(
            409,
            f"Another activation/rescan is already in progress (source_id={running.source_id}) "
            "-- wait for it to finish or cancel it first.",
        )
    start_activation(registry, source)
    return {"status": "started", "source_id": source_id}


@router.post("/sources/{source_id}/rescan")
def rescan_source_endpoint(source_id: str) -> dict:
    """Forces a real re-ingest of exactly THIS source's own cache slot,
    regardless of its current status or whether it's active -- never
    touches any other source's cache, and never changes which source is
    active (see ``ingestion.activation.rescan_source``'s docstring). This is
    the ONLY way to refresh a source's cached data: the app never decides on
    its own that a source's raw data changed."""
    registry = get_workspace_registry()
    source = registry.get(source_id)
    if source is None:
        raise HTTPException(404, f"Unknown data source: {source_id}")
    running = get_running_activation()
    if running is not None:
        raise HTTPException(
            409,
            f"Another activation/rescan is already in progress (source_id={running.source_id}) "
            "-- wait for it to finish or cancel it first.",
        )
    start_rescan(registry, source)
    return {"status": "started", "source_id": source_id}


@router.get("/sources/{source_id}/activation-status")
def activation_status_endpoint(source_id: str) -> dict:
    """Poll target for a background activation started above.
    ``status``: "unknown" (nothing tracked for this id -- either never
    started, or the backend restarted since), "running", "ok", "error", or
    "cancelled". ``phase``/``files_done``/``files_total`` update live while
    running (``files_total`` is null during discovery -- see
    ``pipeline.ProgressFn``); ``result``/``error`` are only present once
    finished."""
    progress = get_activation_progress(source_id)
    if progress is None:
        return {"status": "unknown", "phase": None, "files_done": 0, "files_total": None}
    out: dict = {
        "status": progress.status,
        "phase": progress.phase,
        "files_done": progress.files_done,
        "files_total": progress.files_total,
    }
    if progress.result is not None:
        out["result"] = asdict(progress.result)
    if progress.error is not None:
        out["error"] = progress.error
    return out


@router.post("/sources/{source_id}/activation-cancel")
def activation_cancel_endpoint(source_id: str) -> dict:
    """Cooperatively stop an in-flight activation -- signals a
    ``threading.Event`` checked at the same checkpoints as progress
    reporting (see ``pipeline.run_ingest``/``spatial_pipeline.
    build_raster_index``), so it stops within a few hundred files rather
    than instantly, and never leaves partial/corrupt store data behind.
    Whatever source was active before is left untouched either way."""
    if not request_cancel(source_id):
        raise HTTPException(404, f"No running activation for source: {source_id}")
    return {"status": "cancelling", "source_id": source_id}


@router.delete("/sources/{source_id}")
def remove_source(source_id: str) -> dict:
    """Forgets the source AND deletes its on-disk ingest cache, then
    immediately rebuilds the live catalog from whatever's left active (see
    ``ingestion.activation.remove_source_and_rebuild``) -- so a stale
    ``catalog.duckdb`` view never outlives the deleted cache. Never touches
    the raw source directory itself."""
    registry = get_workspace_registry()
    if registry.get(source_id) is None:
        raise HTTPException(404, f"Unknown data source: {source_id}")
    running = get_running_activation()
    if running is not None and running.source_id == source_id:
        # Deleting a source's cache out from under a background thread
        # that's still writing to it -- reject instead of racing; cancel it
        # first via activation-cancel.
        raise HTTPException(409, "This source is still being activated/rescanned -- cancel it first.")
    remove_source_and_rebuild(registry, source_id)
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
