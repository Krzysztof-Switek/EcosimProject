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
        )


def _new_source(name: str, path: Path, kind: SourceKind) -> DataSource:
    return DataSource(id=uuid.uuid4().hex[:12], name=name, path=path, kind=kind, added_at=datetime.now(timezone.utc))


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

    def add_source(self, name: str, path: Path, kind: SourceKind) -> DataSource:
        if not path.is_dir():
            raise ValueError(f"Not a reachable directory: {path}")
        source = _new_source(name, path, kind)
        data = self._load()
        data["sources"].append(source.to_json())
        self._write(data)
        return source

    def keep_only(self, kind: SourceKind, source_id: str) -> None:
        """Removes every other source of this ``kind``, keeping only
        ``source_id`` -- there's a single current output source and a single
        current input source, no remembered history to pick from (a per-user
        list would make sense once there's per-user accounts; for a single
        shared instance today it's just clutter -- see
        docs/Plans and TO_DO lists/27.08_data_upload_PLAN.md).

        Deliberately a separate step from ``add_source``, called only *after*
        a new source has successfully activated (see
        ``ingestion.activation.activate_source``): pruning eagerly at add-time
        would delete the previous, still-working source before knowing
        whether its replacement even works, undoing the guarantee that a
        failed activation never destroys what was working before.
        """
        data = self._load()
        data["sources"] = [s for s in data["sources"] if s["kind"] != kind or s["id"] == source_id]
        self._write(data)

    def remove_source(self, source_id: str) -> None:
        """Forgets the source from the registry. Never touches the raw
        directory itself, and there is no per-source store cache to clean up
        any more -- the canonical store is always a single, freshly rebuilt
        location reflecting whatever is active right now (see
        ``ingestion.activation``)."""
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

    def mark_scanned(self, source_id: str, *, ok: bool, error: str | None = None) -> None:
        data = self._load()
        for s in data["sources"]:
            if s["id"] == source_id:
                s["status"] = "ok" if ok else "error"
                s["error"] = None if ok else error
                s["last_scanned_at"] = datetime.now(timezone.utc).isoformat()
        self._write(data)


def _config_dir() -> Path:
    override = os.environ.get("ECOSIM_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".ecosim"


def get_workspace_registry() -> WorkspaceRegistry:
    return WorkspaceRegistry(_config_dir() / "workspaces.json")
