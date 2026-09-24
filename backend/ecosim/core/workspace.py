"""Registry of data sources: the folders (local dev path, or a mounted
network share) the app reads raw EwE exports from.

EwE model **output** (Ecosim/Ecospace results) and **input** (driver/forcing
grids) are two genuinely separate datasets a researcher may get from
different places at different times -- so each is tracked and activated
independently (``kind: "output" | "input"``), not as subfolders of one
shared root. Output is the mandatory one: models/scenarios/groups all derive
from it, so the rest of the app stays gated until an output source is
active; input is optional and only adds driver-grid variables when present.

No default/auto-registered source of any kind -- a fresh install always
starts with an empty registry, and the app makes the user point at a real
folder before anything else works. See
``docs/Plans and TO_DO lists/27.08_data_upload_PLAN.md`` for the design.

Everything persistent this app owns -- this registry and (via
``core.config.Settings.store_dir``) the canonical derived store -- lives
under one *profile* directory (``profile_dir()`` below), never inside the
project's own code tree. Exactly one profile (``DEFAULT_PROFILE_ID``) exists
today since there's no auth yet, but every consumer already goes through
``profile_dir(profile_id)`` rather than assuming a single fixed path -- so
wiring in a real per-account profile id later (once auth exists) is a change
to *how the id is resolved*, not to the directory layout itself. See
``docs/Plans and TO_DO lists/28.08_session_summary.md``.

Deliberately has NO dependency on ``ecosim.ingestion.*``/``ecosim.catalog.*``
-- ``core.config`` imports this module, so importing anything that itself
imports ``core.config`` back would be circular. The "activate a source and
run ingestion" orchestration lives in ``ecosim.ingestion.activation``
instead, one layer up.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

SourceKind = Literal["output", "input"]


class NoActiveDataSourceError(RuntimeError):
    """No *output* data source is active yet -- the API surfaces this as
    HTTP 409 (see api/app.py) so the frontend shows the source picker instead
    of a broken, empty catalog. Output is the mandatory one (models/
    scenarios/groups all derive from it); input is optional."""


@dataclass
class DataSource:
    id: str
    name: str
    path: Path
    kind: SourceKind
    added_at: datetime
    last_scanned_at: datetime | None = None
    status: str = "unscanned"  # "unscanned" | "ok" | "error"
    error: str | None = None
    # "spatial" | "timeseries" | "mixed" | "montecarlo" | None -- what the
    # most recent successful scan actually found, per
    # ingestion.activation.ActivationResult.data_kind. None until scanned
    # (or when nothing was ingestible, e.g. an input source added before any
    # output source exists). Persisted so the source picker/tile gating
    # survives a restart without re-scanning.
    data_kind: str | None = None
    # Distinct source directories seen for whichever scenario spans the
    # most, per ingestion.activation.ActivationResult.run_count -- 1 for
    # ordinary data. Persisted alongside data_kind (not just held in the
    # transient ActivationResult) so the Monte Carlo tile's "N samples"
    # survives a page reload without re-running activation.
    run_count: int = 1
    # Wall-clock seconds the most recent successful (re)scan of this source
    # took -- a cached mirror of sources/<id>/meta.json's duration_seconds
    # (see ingestion.activation), written at the same moment as data_kind/
    # run_count by mark_scanned(). None until scanned, or for a source
    # migrated from the pre-per-source-cache layout whose original scan
    # duration was never recorded. Shown on the "Indexed data" panel's
    # Rescan button as a rough time estimate -- never used to decide
    # whether to rescan, only to inform the user before they click it.
    scan_duration_seconds: float | None = None
    # The user explicitly agreed (when adding the folder) that its files may
    # be downloaded to this computer before scanning -- set only through the
    # "Download and scan" choice for a folder whose files are cloud-only
    # placeholders (see ingestion/file_access.py). Every later scan of this
    # source downloads whatever is missing first instead of refusing. Never
    # set implicitly: a multi-GB download is the user's call, not the app's.
    keep_local: bool = False

    def to_json(self) -> dict:
        d = asdict(self)
        d["path"] = str(self.path)
        d["added_at"] = self.added_at.isoformat()
        d["last_scanned_at"] = self.last_scanned_at.isoformat() if self.last_scanned_at else None
        return d

    @classmethod
    def from_json(cls, d: dict) -> DataSource:
        return cls(
            id=d["id"],
            name=d["name"],
            path=Path(d["path"]),
            kind=d["kind"],
            added_at=datetime.fromisoformat(d["added_at"]),
            last_scanned_at=datetime.fromisoformat(d["last_scanned_at"]) if d.get("last_scanned_at") else None,
            status=d.get("status", "unscanned"),
            error=d.get("error"),
            data_kind=d.get("data_kind"),
            run_count=d.get("run_count", 1),
            scan_duration_seconds=d.get("scan_duration_seconds"),
            keep_local=d.get("keep_local", False),
        )


def _new_source(name: str, path: Path, kind: SourceKind, keep_local: bool = False) -> DataSource:
    return DataSource(
        id=uuid.uuid4().hex[:12], name=name, path=path, kind=kind,
        added_at=datetime.now(timezone.utc), keep_local=keep_local,
    )


class WorkspaceRegistry:
    """Persists known data sources + which one is active *per kind* to a
    small JSON file that lives outside of any data source itself (default
    ``~/.ecosim``, see ``get_workspace_registry``). Reads/writes the file
    fresh on every call -- this app runs at a scale (one admin, a handful of
    sources) where that's simpler and safer than an in-memory cache that
    could go stale across requests or CLI invocations."""

    def __init__(self, config_path: Path):
        self._config_path = config_path

    def _load(self) -> dict:
        if not self._config_path.exists():
            data: dict = {"active_output_id": None, "active_input_id": None, "sources": []}
            self._write(data)
            return data
        return json.loads(self._config_path.read_text(encoding="utf-8"))

    def _write(self, data: dict) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_sources(self, kind: SourceKind | None = None) -> list[DataSource]:
        sources = [DataSource.from_json(s) for s in self._load()["sources"]]
        return [s for s in sources if kind is None or s.kind == kind]

    def get(self, source_id: str) -> DataSource | None:
        return next((s for s in self.list_sources() if s.id == source_id), None)

    def active(self, kind: SourceKind) -> DataSource | None:
        data = self._load()
        active_id = data.get(f"active_{kind}_id")
        if not active_id:
            return None
        raw = next((s for s in data["sources"] if s["id"] == active_id), None)
        return DataSource.from_json(raw) if raw else None

    def add_source(self, name: str, path: Path, kind: SourceKind, *, keep_local: bool = False) -> DataSource:
        if not path.is_dir():
            raise ValueError(f"Not a reachable directory: {path}")
        source = _new_source(name, path, kind, keep_local)
        data = self._load()
        data["sources"].append(source.to_json())
        self._write(data)
        return source

    def keep_only(self, kind: SourceKind, source_id: str) -> None:
        """Removes every other source of this ``kind``, keeping only
        ``source_id``.

        No longer called by ``ingestion.activation.activate_source`` as of
        2026-08-28: each source now gets its own independently-cached ingest
        output (``core/config.py``'s "Per-source cache"), so re-activating a
        previously-scanned source can be instant instead of a full rescan --
        which only works if the registry keeps a genuine history of every
        source ever added, not just the one most recently activated per
        kind. Left in place (unused internally) rather than deleted, since
        it's still a reasonable primitive for a future explicit "forget
        everything except this" bulk action, and deleting it would be a
        bigger, unrequested change than just not calling it.
        """
        data = self._load()
        data["sources"] = [s for s in data["sources"] if s["kind"] != kind or s["id"] == source_id]
        self._write(data)

    def remove_source(self, source_id: str) -> None:
        """Forgets the source from the registry. Does NOT touch the raw
        source directory, and does NOT delete that source's on-disk ingest
        cache (``core/config.py::source_cache_dir``) -- that's the caller's
        job (see ``ingestion.activation.remove_source_and_rebuild``, which
        also rebuilds the live combined catalog afterward so a dangling
        DuckDB view never outlives a deleted cache). Kept a pure
        registry-only operation here so it stays usable/testable without
        touching the filesystem beyond this one JSON file."""
        data = self._load()
        data["sources"] = [s for s in data["sources"] if s["id"] != source_id]
        for key in ("active_output_id", "active_input_id"):
            if data.get(key) == source_id:
                data[key] = None
        self._write(data)

    def set_active(self, source_id: str) -> None:
        data = self._load()
        match = next((s for s in data["sources"] if s["id"] == source_id), None)
        if match is None:
            raise ValueError(f"Unknown data source: {source_id}")
        data[f"active_{match['kind']}_id"] = source_id
        self._write(data)

    def mark_scanned(
        self,
        source_id: str,
        *,
        ok: bool,
        error: str | None = None,
        data_kind: str | None = None,
        run_count: int = 1,
        scan_duration_seconds: float | None = None,
    ) -> None:
        data = self._load()
        for s in data["sources"]:
            if s["id"] == source_id:
                s["status"] = "ok" if ok else "error"
                s["error"] = None if ok else error
                s["last_scanned_at"] = datetime.now(timezone.utc).isoformat()
                # Only touch data_kind/run_count/scan_duration_seconds on a
                # successful scan -- a failed scan didn't recompute them, so
                # leave whatever was last known (irrelevant anyway while
                # status=="error").
                if ok:
                    s["data_kind"] = data_kind
                    s["run_count"] = run_count
                    s["scan_duration_seconds"] = scan_duration_seconds
        self._write(data)


DEFAULT_PROFILE_ID = "default"


def _config_dir() -> Path:
    override = os.environ.get("ECOSIM_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".ecosim"


def profile_dir(profile_id: str = DEFAULT_PROFILE_ID) -> Path:
    """Root directory for one profile's persistent state. Both this
    registry's JSON file and (via ``core.config.Settings.store_dir``) the
    canonical derived store live under here -- outside the project's own
    code tree, so they survive independently of it and are never mistaken
    for something the app ships/bundles."""
    return _config_dir() / "profiles" / profile_id


def get_workspace_registry() -> WorkspaceRegistry:
    return WorkspaceRegistry(profile_dir() / "workspaces.json")
