"""Zonal statistics: one Ecospace variable summarised over areas, map by map.

For every map (one raster-index row: variable x group/fleet x year x run) and
every area (a cell mask, regions/masks.py) the raw ``.asc`` values of the
area's cells give

* ``n_cells`` / ``area_km2`` -- the area's cells that have a value. Model maps
  can have no value in cells a region pack calls water (real case: values in
  13,523 of the 14,985 ICES water cells), so this is reported as coverage
  instead of silently treating the gap as zero;
* ``mean`` -- area-weighted: Σ vᵢ·aᵢ / Σ aᵢ over those cells;
* ``total`` -- Σ vᵢ·aᵢ, only for variables that are densities per km²
  (biomass, catch, discards, effort -- plan 27.08 §1.3). Not for a fraction
  (habitat capacity) or anything whose summing meaning isn't documented:
  ECOIND indicators (UG p.229-231 describe the indicators, not what a sum of a
  per-cell indicator would mean) and input drivers.

Monte Carlo runs are summarised like ``catalog.service.query_timeseries``:
the value from the baseline run (else the main run, else the median) with the
5th/95th percentile over the samples (UG p.180, Fig. 10).

Results are cached per (map, area) in the store (``zonal/<area key>.parquet``)
-- a map fetched from the cloud once is never fetched again for the same area,
and asking again costs nothing. The area key hashes the area's actual cells and
the grid's CRS, so the same cells drawn or picked differently share a cache,
and a changed region pack or CRS gets a new one. A cached entry remembers the
source file's path, size and modification time and is recomputed if any of
them changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ecosim.regions.grid import GridSignature, cell_areas_km2
from ecosim.regions.masks import AreaError, GridContext, area_mask

DENSITY_VARIABLES = {"biomass", "catch", "discards", "effort"}
FRACTION_VARIABLES = {"habitat_capacity"}

# Above this many maps to read or to fetch from the cloud, the work runs as a
# background job the user starts knowingly (cost shown first). A handful of
# downloads (~0.3 MB each) is what showing a few maps costs anyway.
INLINE_MAX_MAPS = 300
INLINE_MAX_DOWNLOADS = 30
# Measured on the real Monte Carlo folder (docs/ewe-data-formats.md).
DOWNLOAD_FILES_PER_SECOND = 10.0
READ_FILES_PER_SECOND = 60.0
_FLUSH_EVERY = 200


def aggregation(variable: str) -> str:
    """``density`` (mean and total), ``fraction`` or ``indicator`` (mean only)."""
    if variable in DENSITY_VARIABLES:
        return "density"
    if variable in FRACTION_VARIABLES:
        return "fraction"
    return "indicator"


# --------------------------------------------------------------------------- areas


@dataclass
class ZonalArea:
    id: str
    name: str
    mask: np.ndarray
    key: str

    @property
    def cells(self) -> int:
        return int(self.mask.sum())


def area_key(mask: np.ndarray, grid: GridSignature, crs) -> str:
    h = hashlib.sha1()
    h.update(json.dumps(grid.to_dict(), sort_keys=True).encode())
    h.update(crs.to_wkt().encode())
    h.update(np.packbits(mask, axis=None).tobytes())
    return h.hexdigest()[:20]


OUTSIDE_SUFFIX = "__outside"


def complement(area: ZonalArea, ctx: GridContext) -> ZonalArea:
    """The rest of the grid. Land and cells without model values hold no value
    in the maps, so they never count -- its coverage is therefore not meaningful."""
    mask = ~area.mask
    return ZonalArea(area.id + OUTSIDE_SUFFIX, f"{area.name} (outside)", mask, area_key(mask, ctx.grid, ctx.crs))


def build_areas(areas: list[dict], ctx: GridContext) -> list[ZonalArea]:
    """``areas``: ``[{id, name, area}]`` (area = masks.py definition)."""
    out = []
    for a in areas:
        mask = area_mask(a["area"], ctx)
        if not mask.any():
            raise AreaError(f"\"{a.get('name') or a['id']}\" has no cells on this model's grid.")
        out.append(ZonalArea(str(a["id"]), a.get("name") or str(a["id"]), mask, area_key(mask, ctx.grid, ctx.crs)))
    return out


# --------------------------------------------------------------------------- one map


def read_values(path: Path, grid: GridSignature) -> np.ndarray:
    """The map's values as Float64 (exactly the raw text), NODATA -> NaN.
    Raises ValueError if the map isn't on ``grid``."""
    import rasterio

    with rasterio.Env(AAIGRID_DATATYPE="Float64"):
        with rasterio.open(path) as src:
            t = src.transform
            here = GridSignature(src.width, src.height, t.c, t.f + t.e * src.height, t.a)
            if not grid.matches(here):
                raise ValueError(f"{path.name} is on a different grid ({here.describe()}) "
                                 f"than the areas ({grid.describe()}).")
            data = src.read(1).astype(np.float64)
            nodata = src.nodata
    if nodata is not None:
        data[data == nodata] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data


def map_stats(values: np.ndarray, cell_km2: np.ndarray, areas: list[ZonalArea]) -> list[dict]:
    valid = ~np.isnan(values)
    out = []
    for a in areas:
        m = a.mask & valid
        n = int(m.sum())
        if n == 0:
            out.append({"n_cells": 0, "area_km2": 0.0, "wsum": None, "vmin": None, "vmax": None})
            continue
        v, w = values[m], cell_km2[m]
        out.append({"n_cells": n, "area_km2": float(w.sum()), "wsum": float((v * w).sum()),
                    "vmin": float(v.min()), "vmax": float(v.max())})
    return out


# --------------------------------------------------------------------------- cache


_CACHE_COLUMNS = ("raster_id", "source_path", "size", "mtime_ns", "n_cells", "area_km2", "wsum", "vmin", "vmax")
_cache_lock = threading.Lock()


def cache_dir() -> Path:
    from ecosim.core.config import get_settings

    return get_settings().store_dir / "zonal"


def _file_stamp(path: str) -> tuple[int, int] | None:
    """(size, mtime) from the file's metadata -- never its content, so a
    cloud-only file is not downloaded by asking."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def load_cache(key: str) -> dict[str, dict]:
    import pyarrow.parquet as pq

    path = cache_dir() / f"{key}.parquet"
    if not path.exists():
        return {}
    table = pq.read_table(path).to_pylist()
    return {r["raster_id"]: r for r in table}


def save_cache(key: str, entries: dict[str, dict]) -> None:
    """Merge ``entries`` (raster_id -> row) into the area's cache file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    if not entries:
        return
    with _cache_lock:
        merged = load_cache(key)
        merged.update(entries)
        d = cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        cols = {c: [r.get(c) for r in merged.values()] for c in _CACHE_COLUMNS}
        schema = pa.schema([("raster_id", pa.string()), ("source_path", pa.string()), ("size", pa.int64()), ("mtime_ns", pa.int64()),
                            ("n_cells", pa.int64()), ("area_km2", pa.float64()), ("wsum", pa.float64()),
                            ("vmin", pa.float64()), ("vmax", pa.float64())])
        tmp = d / f"{key}.parquet.tmp"
        pq.write_table(pa.table(cols, schema=schema), tmp)
        os.replace(tmp, d / f"{key}.parquet")


def _fresh(entry: dict | None, row: dict) -> bool:
    """Cached for this very file (another data source can reuse a raster id),
    unchanged since."""
    stamp = row["_stamp"]
    return (entry is not None and stamp is not None and entry.get("source_path") == row["source_path"]
            and (entry["size"], entry["mtime_ns"]) == stamp)


# --------------------------------------------------------------------------- plan


@dataclass
class ZonalRequest:
    scenario: str
    variable: str
    areas: list[dict]
    entities: list[str] = field(default_factory=list)  # group/fleet names; empty = all
    year_from: int | None = None
    year_to: int | None = None
    run: str | None = None  # a run_id, "all" (every Monte Carlo run, summarised), or None
    domain: str = "output"
    # Also each area's complement -- the rest of the model's grid ("<id>__outside").
    complements: bool = False


@dataclass
class ZonalPlan:
    request: ZonalRequest
    grid: dict  # DataGrid.to_dict()
    ctx: GridContext
    areas: list[ZonalArea]
    rows: list[dict]  # the maps, each with "_stamp"
    run_kinds: dict[str, str]  # run_id -> baseline/main/sample
    cached: dict[str, dict[str, dict]]  # area key -> raster_id -> stats
    todo: list[dict]  # rows missing for at least one area
    to_download: list[dict]  # todo rows only in the cloud

    @property
    def bytes_to_download(self) -> int:
        return sum(r["_stamp"][0] for r in self.to_download if r["_stamp"])

    def cost(self) -> dict:
        seconds = len(self.to_download) / DOWNLOAD_FILES_PER_SECOND + len(self.todo) / READ_FILES_PER_SECOND
        return {
            "maps": len(self.rows),
            "maps_cached": len(self.rows) - len(self.todo),
            "maps_to_read": len(self.todo),
            "maps_to_download": len(self.to_download),
            "bytes_to_download": self.bytes_to_download,
            "seconds_estimate": round(seconds),
            # The sync app needed for the downloads isn't running: they'd be left out.
            "sync_app_missing": self.sync_app_missing(),
        }

    def sync_app_missing(self) -> str | None:
        from ecosim.ingestion.file_access import sync_client_not_running

        if not self.to_download:
            return None
        return sync_client_not_running(Path(self.to_download[0]["source_path"]).parent)

    @property
    def inline(self) -> bool:
        return len(self.to_download) <= INLINE_MAX_DOWNLOADS and len(self.todo) <= INLINE_MAX_MAPS


def _entity(row: dict) -> str | None:
    return row.get("group_name") or row.get("fleet_name")


def make_plan(req: ZonalRequest) -> ZonalPlan:
    from ecosim.catalog import service
    from ecosim.ingestion.file_access import is_cloud_only
    from ecosim.regions.datagrid import scenario_grid

    if not req.areas:
        raise AreaError("Pick at least one area.")
    data_grid = scenario_grid(req.scenario, req.domain)
    ctx = data_grid.context()
    if ctx is None:
        raise AreaError(data_grid.message or "The model's grid is unknown.")
    areas = build_areas(req.areas, ctx)
    if req.complements:
        areas += [complement(a, ctx) for a in areas]

    runs = service.list_raster_runs(scenario=req.scenario, variable=req.variable)
    run_kinds = {r["run_id"]: r["kind"] for r in runs}
    run_filter = None
    if req.run not in (None, "all"):
        run_filter = req.run
    elif req.run is None and runs:
        run_filter = runs[0]["run_id"]  # baseline, else main run (list_raster_runs order)
    rows = service.list_rasters(scenario=req.scenario, variable=req.variable, run=run_filter)
    wanted = set(req.entities)
    rows = [r for r in rows
            if (req.year_from is None or r["year"] >= req.year_from)
            and (req.year_to is None or r["year"] <= req.year_to)
            and (not wanted or _entity(r) is None or _entity(r) in wanted)
            and r.get("domain", req.domain) == req.domain]
    if not rows:
        raise AreaError("No maps match this selection.")

    for r in rows:
        r["_stamp"] = _file_stamp(r["source_path"])
    cached = {a.key: load_cache(a.key) for a in areas}
    todo = [r for r in rows if not all(_fresh(cached[a.key].get(r["id"]), r) for a in areas)]
    to_download = [r for r in todo if r["_stamp"] is not None and is_cloud_only(Path(r["source_path"]))]
    return ZonalPlan(req, data_grid.to_dict(), ctx, areas, rows, run_kinds, cached, todo, to_download)


# --------------------------------------------------------------------------- compute


@dataclass
class Progress:
    phase: str = "starting"  # downloading | reading | done
    done: int = 0
    total: int = 0
    paused: bool = False  # the sync app stopped serving files; waiting for it


def compute(plan: ZonalPlan, *, on_progress: Callable[[Progress], None] | None = None,
            cancel_event: threading.Event | None = None) -> dict:
    """Download what's only in the cloud, read every map not cached yet, then
    return :func:`result`. Cancelling keeps everything computed so far."""
    from ecosim.ingestion.file_access import (
        SourceNotLocalError,
        download_files,
        is_cloud_only,
        sync_client_not_running,
    )

    progress = Progress()
    failed: list[str] = []

    def report() -> None:
        if on_progress is not None:
            on_progress(progress)

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    skip: set[str] = set()
    if plan.to_download:
        first = Path(plan.to_download[0]["source_path"])
        client = sync_client_not_running(first.parent)
        if client:
            # Summarise what is on this computer and say what's missing --
            # never read a cloud-only file without its sync app (it would fail).
            skip = {r["id"] for r in plan.to_download}
            failed.append(f"{len(skip)} of these maps are stored only online and {client} isn't running, so "
                          f"they are left out. Start {client} and ask again to include them.")
        else:
            progress.phase, progress.total = "downloading", plan.bytes_to_download
            report()

            def on_bytes(done: int, _total: int) -> None:
                progress.done = done
                report()

            def on_pause(paused: bool) -> None:
                progress.paused = paused
                report()

            root = Path(os.path.commonpath([r["source_path"] for r in plan.to_download]))
            files = [(Path(r["source_path"]), r["_stamp"][0]) for r in plan.to_download]
            try:
                download_files(files, root, on_progress=on_bytes, cancel_event=cancel_event, on_pause=on_pause)
            except SourceNotLocalError as exc:
                failed.append(str(exc))  # read what did arrive; the rest is reported as missing
            progress.paused = False
            skip = {r["id"] for r in plan.to_download if is_cloud_only(Path(r["source_path"]))}

    cell_km2 = cell_areas_km2(plan.ctx.grid, plan.ctx.crs)
    pending: dict[str, dict[str, dict]] = {a.key: {} for a in plan.areas}
    progress.phase, progress.done, progress.total = "reading", 0, len(plan.todo)
    report()

    def flush() -> None:
        for a in plan.areas:
            save_cache(a.key, pending[a.key])
            plan.cached[a.key].update(pending[a.key])
            pending[a.key] = {}

    for i, row in enumerate(plan.todo, 1):
        if cancelled():
            break
        if row["id"] in skip:
            continue
        src = Path(row["source_path"])
        stamp = _file_stamp(row["source_path"])
        try:
            values = read_values(src, plan.ctx.grid)
        except Exception as exc:  # noqa: BLE001 -- one bad map must not stop the rest
            from ecosim.ingestion.file_access import describe_read_error

            failed.append(describe_read_error(exc, src) if isinstance(exc, OSError) else str(exc))
            continue
        row["_stamp"] = stamp
        for a, stats in zip(plan.areas, map_stats(values, cell_km2, plan.areas), strict=True):
            pending[a.key][row["id"]] = {"raster_id": row["id"], "source_path": row["source_path"], "size": stamp[0], "mtime_ns": stamp[1], **stats}
        if i % _FLUSH_EVERY == 0:
            flush()
        progress.done = i
        if i % 20 == 0:
            report()
    flush()
    progress.phase = "done"
    report()
    out = result(plan)
    out["problems"] = failed[:20] + ([f"... and {len(failed) - 20} more"] if len(failed) > 20 else [])
    out["cancelled"] = cancelled()
    return out


# --------------------------------------------------------------------------- result


def _one(stats: dict, semantics: str, area_cells: int) -> dict:
    n = stats["n_cells"]
    mean = stats["wsum"] / stats["area_km2"] if n else None
    out = {"mean": mean, "min": stats["vmin"], "max": stats["vmax"], "n_cells": n,
           "coverage": n / area_cells if area_cells else None}
    if semantics == "density":
        out["total"] = stats["wsum"] if n else None
    return out


def _summarise(values: list[tuple[str, float | None]]) -> tuple[float | None, float | None, float | None, int]:
    """``(kind, value)`` per run -> (value, p05, p95, n_samples), as
    query_timeseries: baseline, else single/main run, else the samples' median."""
    samples = np.array([v for k, v in values if k == "sample" and v is not None], dtype=float)
    pick = next((v for k, v in values if k == "baseline" and v is not None), None)
    if pick is None:
        pick = next((v for k, v in values if k in ("single", "main") and v is not None), None)
    if pick is None and samples.size:
        pick = float(np.median(samples))
    if not samples.size:
        return pick, None, None, 0
    return pick, float(np.quantile(samples, 0.05)), float(np.quantile(samples, 0.95)), int(samples.size)


def result(plan: ZonalPlan) -> dict:
    """Per area, group/fleet and year: the statistics of the maps cached so
    far (maps not read -- failed or cancelled -- are left out and counted)."""
    req = plan.request
    semantics = aggregation(req.variable)
    summarise = req.run == "all" and bool(plan.run_kinds)
    out_rows: list[dict] = []
    missing: set[str] = set()
    for a in plan.areas:
        cache = plan.cached[a.key]
        points: dict[tuple, list[tuple[str, dict]]] = {}
        for r in plan.rows:
            stats = cache.get(r["id"])
            if stats is None:
                missing.add(r["id"])
                continue
            kind = plan.run_kinds.get(r.get("run_id"), "single")
            points.setdefault((_entity(r), r["year"]), []).append((kind, _one(stats, semantics, a.cells)))
        for (entity, year), runs in sorted(points.items(), key=lambda p: (p[0][0] or "", p[0][1])):
            base = {"area_id": a.id, "entity": entity, "year": year}
            if not summarise:
                out_rows.append({**base, **runs[0][1]})
                continue
            row = dict(base)
            for stat in ("mean", "total") if semantics == "density" else ("mean",):
                value, p05, p95, n = _summarise([(k, s.get(stat)) for k, s in runs])
                row[stat], row[f"{stat}_p05"], row[f"{stat}_p95"], row["n_samples"] = value, p05, p95, n
            ref = next((s for k, s in runs if k == "baseline"), runs[0][1])
            row["n_cells"], row["coverage"] = ref["n_cells"], ref["coverage"]
            out_rows.append(row)
    return {
        "variable": req.variable,
        "semantics": semantics,
        "run": req.run,
        "grid": plan.grid,
        "areas": [{"id": a.id, "name": a.name, "cells": a.cells,
                   "area_km2": round(float(cell_areas_km2(plan.ctx.grid, plan.ctx.crs)[a.mask].sum()), 1)}
                  for a in plan.areas],
        "rows": out_rows,
        "maps": len(plan.rows),
        "maps_missing": len(missing),
    }


# --------------------------------------------------------------------------- jobs


@dataclass
class ZonalJob:
    id: str
    request_key: str
    status: str = "running"  # running | done | cancelled | error
    progress: Progress = field(default_factory=Progress)
    result: dict | None = None
    error: str | None = None
    started: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict:
        p = self.progress
        return {"id": self.id, "status": self.status, "phase": p.phase, "done": p.done, "total": p.total,
                "paused": p.paused, "error": self.error, "result": self.result}


_jobs: dict[str, ZonalJob] = {}
_jobs_lock = threading.Lock()
_MAX_JOBS_KEPT = 20


def _request_key(plan: ZonalPlan) -> str:
    req = plan.request
    payload = [req.scenario, req.domain, req.variable, sorted(req.entities), req.year_from, req.year_to,
               req.run, [a.key for a in plan.areas]]
    return hashlib.sha1(json.dumps(payload).encode()).hexdigest()


def start_job(plan: ZonalPlan) -> ZonalJob:
    """Run :func:`compute` in a background thread; the same request already
    running is joined instead of started twice."""
    key = _request_key(plan)
    with _jobs_lock:
        for job in _jobs.values():
            if job.request_key == key and job.status == "running":
                return job
        job = ZonalJob(uuid.uuid4().hex[:12], key)
        _jobs[job.id] = job
        for old in sorted(_jobs.values(), key=lambda j: j.started)[:-_MAX_JOBS_KEPT]:
            if old.status != "running":
                del _jobs[old.id]

    def on_progress(p: Progress) -> None:
        job.progress = Progress(p.phase, p.done, p.total, p.paused)

    def run() -> None:
        try:
            job.result = compute(plan, on_progress=on_progress, cancel_event=job.cancel_event)
            job.status = "cancelled" if job.result.get("cancelled") else "done"
        except Exception as exc:  # noqa: BLE001 -- shown to the user
            job.error = str(exc)
            job.status = "error"

    threading.Thread(target=run, daemon=True, name=f"zonal-{job.id}").start()
    return job


def get_job(job_id: str) -> ZonalJob | None:
    return _jobs.get(job_id)
