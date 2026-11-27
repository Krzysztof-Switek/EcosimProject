"""Region packs saved in the user's profile.

A pack is copied in on import (``profile_dir()/regions/<pack_id>/``) --
small (a few MB), and moving or deleting the original folder afterwards
breaks nothing. Layout per pack::

    pack.json                     name, source path, imported_at, layers[], warnings[]
    <layer_slug>.npy              int16 cell array (LAND=-1, 0 = no region, id)
    <layer_slug>.outlines.json    lon/lat GeoJSON, one feature per class

Re-importing the same source path replaces that pack.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath

import numpy as np

from ecosim.core.workspace import profile_dir
from ecosim.regions.grid import GridSignature
from ecosim.regions.pack import build_outlines, scan_pack


class RegionPackError(ValueError):
    """A pack can't be imported -- the message is shown to the user."""


def regions_dir() -> Path:
    return profile_dir() / "regions"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _safe_extract(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = PurePosixPath(member.filename.replace("\\", "/"))
            if member.is_dir() or name.is_absolute() or ".." in name.parts:
                continue
            if name.suffix.lower() not in {".asc", ".prj", ".csv"}:
                continue
            target = dest.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def list_packs() -> list[dict]:
    root = regions_dir()
    if not root.exists():
        return []
    packs = []
    for meta in sorted(root.glob("*/pack.json")):
        try:
            packs.append(json.loads(meta.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(packs, key=lambda p: p.get("imported_at", ""))


def list_layers() -> list[dict]:
    """Every layer of every pack (metadata only, no cell arrays)."""
    return [layer for pack in list_packs() for layer in pack["layers"]]


def import_pack(path: Path, name: str | None = None) -> dict:
    path = Path(path)
    if not path.exists():
        raise RegionPackError(f"Not found: {path}")
    with tempfile.TemporaryDirectory() as tmp:
        if path.is_file():
            if path.suffix.lower() != ".zip":
                raise RegionPackError("Choose a folder or a .zip file with region maps (.asc + .prj).")
            try:
                _safe_extract(path, Path(tmp))
            except zipfile.BadZipFile as exc:
                raise RegionPackError(f"{path.name} is not a valid .zip file.") from exc
            scan_root = Path(tmp)
        else:
            scan_root = path
        scanned = scan_pack(scan_root)
    if not scanned.layers:
        detail = f" ({scanned.warnings[0]})" if scanned.warnings else ""
        raise RegionPackError(f"No region maps found in {path.name}{detail}.")

    source = str(path.resolve())
    existing = next((p for p in list_packs() if p.get("source_path") == source), None)
    pack_id = existing["id"] if existing else uuid.uuid4().hex[:12]
    root = regions_dir()
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{pack_id}_", dir=root))
    try:
        layers = []
        used: set[str] = set()
        for layer in scanned.layers:
            slug = _slug(PurePosixPath(layer.rel_path).with_suffix("").as_posix())
            while slug in used:
                slug += "_"
            used.add(slug)
            layer_id = f"{pack_id}__{slug}"
            np.save(staging / f"{slug}.npy", layer.array)
            outlines = build_outlines(layer.array, layer.grid, layer.crs_wkt, layer.classes, layer_id=layer_id)
            (staging / f"{slug}.outlines.json").write_text(json.dumps(outlines), encoding="utf-8")
            layers.append({
                "id": layer_id, "pack_id": pack_id, "file": slug, "rel_path": layer.rel_path,
                "key": layer.key, "kind": layer.kind, "title": layer.title, "category": layer.category,
                "grid": layer.grid.to_dict(), "crs_wkt": layer.crs_wkt, "crs": _crs_label(layer.crs_wkt),
                "classes": layer.classes, "details": layer.details,
            })
        meta = {
            "id": pack_id,
            "name": name or path.stem,
            "source_path": source,
            "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "layers": layers,
            "warnings": scanned.warnings,
        }
        (staging / "pack.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        target = root / pack_id
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _load_array.cache_clear()
    return meta


def remove_pack(pack_id: str) -> bool:
    target = regions_dir() / pack_id
    if not (target / "pack.json").exists():
        return False
    shutil.rmtree(target)
    _load_array.cache_clear()
    return True


def get_layer(layer_id: str) -> dict | None:
    return next((layer for layer in list_layers() if layer["id"] == layer_id), None)


def layer_array(layer: dict) -> np.ndarray:
    path = regions_dir() / layer["pack_id"] / f"{layer['file']}.npy"
    return _load_array(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=64)
def _load_array(path: str, _mtime: int) -> np.ndarray:
    arr = np.load(path)
    arr.setflags(write=False)
    return arr


def layer_outlines(layer: dict) -> dict:
    path = regions_dir() / layer["pack_id"] / f"{layer['file']}.outlines.json"
    return json.loads(path.read_text(encoding="utf-8"))


def layers_for_grid(grid: GridSignature) -> list[dict]:
    return [layer for layer in list_layers() if GridSignature.from_dict(layer["grid"]).matches(grid)]


def _crs_label(wkt: str) -> str:
    from rasterio.crs import CRS

    crs = CRS.from_wkt(wkt)
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.to_string()
