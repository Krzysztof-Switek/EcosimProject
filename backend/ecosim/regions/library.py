"""The user's saved areas, kept in the profile (``areas.json``) so the backend
sees the same areas as the browser -- zonal statistics, export and R
analyses work on them (plan 26.11 stage 3).

``{"areas": [{"id", "name", "area": {"groups": [...]}}], "selected": [id, ...]}``
-- ``area`` as in regions/masks.py. Written whole on every change (a handful
of areas; a drawn polygon is a few KB).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from ecosim.core.workspace import profile_dir

_lock = threading.Lock()


def library_path() -> Path:
    return profile_dir() / "areas.json"


def load_library() -> dict:
    path = library_path()
    if not path.exists():
        return {"areas": [], "selected": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"areas": data.get("areas", []), "selected": data.get("selected", [])}


def save_library(areas: list[dict], selected: list[str]) -> dict:
    ids = {a["id"] for a in areas}
    data = {"areas": areas, "selected": [s for s in selected if s in ids]}
    path = library_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    return data
