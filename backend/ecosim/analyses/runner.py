"""Job sandbox prep + execution for R analysis plugins.

Implements the contract in docs/data-contract.md: for each run, build
``job_<id>/{manifest.json, params.json, data/, out/}``, invoke the plugin's
entry script against it, then read back ``out/result.json``.

``run_job`` only cares about a script path on disk -- it has no idea whether
that path came from a registered plugin (today) or, later, a script an
in-browser editor wrote to a temp file. That door is left open by not baking
"resolve from the registry" into execution itself.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ecosim.analyses.registry import AnalysisSpec
from ecosim.catalog import service
from ecosim.core.config import Settings, get_settings

RSCRIPT_TIMEOUT_S = 300


class AnalysisRunError(RuntimeError):
    """Rscript exited non-zero, or out/result.json was never written."""


def _variable_names(manifest: dict) -> list[str]:
    """Manifest ``variables`` can be a flat list of slugs (docs/data-contract.md's
    own example) or a list of ``{variable, domain, scenarios}`` objects (what the
    time-series basket actually builds, since it lets each variable carry its own
    scenario selection) -- accept either."""
    names = []
    for v in manifest.get("variables") or []:
        names.append(v["variable"] if isinstance(v, dict) else v)
    return names


def rows_for_manifest(manifest: dict, settings: Settings | None = None) -> list[dict]:
    """Query the canonical store for exactly what a manifest selects -- the one
    place "manifest -> filtered tidy rows" is implemented. A variable object may
    carry ``picks``, the selection of its Results-Extractor box (see
    ``service.query_timeseries``); manifest-level ``group_ids``/``fleet_ids``
    still filter every variable."""
    settings = settings or get_settings()
    freq = manifest.get("freq", "annual")
    rows: list[dict] = []
    for v in manifest.get("variables") or []:
        variable = v["variable"] if isinstance(v, dict) else v
        scenarios = v.get("scenarios") if isinstance(v, dict) else manifest.get("scenarios")
        rows += service.query_timeseries(
            settings,
            scenario=scenarios,
            variable=variable,
            freq=freq,
            group=manifest.get("groups"),
            group_id=manifest.get("group_ids"),
            fleet=manifest.get("fleets"),
            fleet_id=manifest.get("fleet_ids"),
            year_from=manifest.get("year_from"),
            year_to=manifest.get("year_to"),
            month_from=manifest.get("month_from"),
            month_to=manifest.get("month_to"),
            picks=v.get("picks") if isinstance(v, dict) else None,
            run=manifest.get("run"),
        )
    return rows


def prepare_job(
    spec: AnalysisSpec,
    manifest: dict,
    params: dict,
    settings: Settings | None = None,
) -> Path:
    """Create a fresh job sandbox with filtered data + manifest/params, per the
    data contract. Returns the job directory; one that can't be prepared
    (nothing selected, maps not on this computer...) is removed again."""
    settings = settings or get_settings()
    job_dir = settings.jobs_dir / f"job_{uuid.uuid4().hex[:12]}"
    try:
        _fill_job(job_dir, spec, manifest, params, settings)
    except BaseException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    return job_dir


def _fill_job(job_dir: Path, spec: AnalysisSpec, manifest: dict, params: dict, settings: Settings) -> None:
    data_dir = job_dir / "data"
    dict_dir = data_dir / "dictionaries"
    dict_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "out").mkdir(parents=True, exist_ok=True)

    # created_at/analysis_id: not part of the selection itself (that's the
    # rest of the manifest), but recorded here rather than left to the job
    # dir's own filesystem mtime -- that's fragile across backups/restores,
    # and this is the one place every run already passes through, so future
    # per-profile usage analytics (which analyses run, how often, when) has
    # a durable source to read instead of needing a schema migration later.
    manifest_with_meta = {
        **manifest,
        "analysis_id": spec.id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (job_dir / "manifest.json").write_text(json.dumps(manifest_with_meta, indent=2), encoding="utf-8")
    (job_dir / "params.json").write_text(json.dumps(params, indent=2), encoding="utf-8")

    if manifest.get("variables") or not manifest.get("spatial"):
        rows = rows_for_manifest(manifest, settings)
        if not rows:
            raise AnalysisRunError(
                "No data matched your selection (0 rows) -- check the scenario/variable/"
                "group/year filters and try a broader selection."
            )
        pd.DataFrame(rows).to_parquet(data_dir / "timeseries.parquet", index=False)
    prepare_spatial(spec, manifest, data_dir)

    pd.DataFrame(service.list_scenarios(settings)).to_csv(dict_dir / "scenarios.csv", index=False)


def _safe_name(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)[:80] or "area"


def prepare_spatial(spec: AnalysisSpec, manifest: dict, data_dir: Path) -> None:
    """Areas and their statistics for an analysis of Ecospace maps
    (docs/data-contract.md, "Obszary i mapy"): manifest ``spatial`` =
    {scenario, variable, entities?, year_from?, year_to?, run?} and ``areas``
    = [{id, name, area}] (regions/masks.py). Writes ``data/areas/`` (outlines
    as GeoJSON, one 0/1 GeoTIFF mask per area on the model's grid,
    areas.csv) and ``data/zonal.parquet`` (+ .csv): the variable per area,
    group/fleet and year, computed here so R never handles masks itself. With
    ``requires.outside`` each area's complement is summarised too."""
    from ecosim.regions import zonal
    from ecosim.regions.masks import AreaError, mask_outline

    req = spec.requires or {}
    spatial = manifest.get("spatial")
    areas = manifest.get("areas") or []
    if req.get("domain") == "spatial" and not spatial:
        raise AnalysisRunError('This analysis works on Ecospace maps -- run it from "Spatial data".')
    if req.get("areas") and not areas:
        raise AnalysisRunError("Check at least one area of interest first.")
    if not spatial or not areas:
        return
    request = zonal.ZonalRequest(
        scenario=spatial["scenario"], variable=spatial["variable"], areas=areas,
        entities=spatial.get("entities") or [], year_from=spatial.get("year_from"),
        year_to=spatial.get("year_to"), run=spatial.get("run"), complements=bool(req.get("outside")),
    )
    try:
        plan = zonal.make_plan(request)
    except AreaError as exc:
        raise AnalysisRunError(str(exc)) from exc
    if plan.to_download:
        missing = plan.sync_app_missing()
        raise AnalysisRunError(
            f"{len(plan.to_download)} of the maps this needs are stored only online"
            + (f" and {missing} isn't running. Start {missing}, then summarise these areas"
               if missing else ". Summarise these areas")
            + ' in the "Area summary" panel first (it downloads them), then run the analysis again.')
    result = zonal.compute(plan)

    area_dir = data_dir / "areas"
    area_dir.mkdir(parents=True, exist_ok=True)
    km2 = {a["id"]: a["area_km2"] for a in result["areas"]}
    features, listing = [], []
    for a in plan.areas:
        if a.id.endswith(zonal.OUTSIDE_SUFFIX):
            continue
        mask_file = f"{_safe_name(a.id)}_mask.tif"
        _write_mask(area_dir / mask_file, a.mask, plan.ctx)
        for f in mask_outline(a.mask, plan.ctx)["features"]:
            props = {"id": a.id, "name": a.name, "cells": a.cells, "area_km2": km2.get(a.id)}
            features.append({**f, "properties": props})
        listing.append({"id": a.id, "name": a.name, "cells": a.cells, "area_km2": km2.get(a.id),
                        "mask_file": mask_file})
    (area_dir / "areas.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                                            encoding="utf-8")
    pd.DataFrame(listing).to_csv(area_dir / "areas.csv", index=False)

    rows = result["rows"]
    if not rows:
        raise AnalysisRunError("The maps have no values in these areas for this selection.")
    table = zonal_table(rows, {a.id: a.name for a in plan.areas})
    table["scenario"], table["variable"], table["semantics"] = request.scenario, request.variable, result["semantics"]
    table.to_parquet(data_dir / "zonal.parquet", index=False)
    table.to_csv(data_dir / "zonal.csv", index=False)


def zonal_table(rows: list[dict], names: dict[str, str]) -> pd.DataFrame:
    """Zonal rows with ``area_name``, ``area`` (the area's own id, also for
    its complement) and ``side`` (inside / outside)."""
    from ecosim.regions.zonal import OUTSIDE_SUFFIX

    table = pd.DataFrame(rows)
    outside = table["area_id"].str.endswith(OUTSIDE_SUFFIX)
    table.insert(1, "area_name", table["area_id"].map(names))
    table.insert(2, "area", table["area_id"].where(~outside, table["area_id"].str[: -len(OUTSIDE_SUFFIX)]))
    table.insert(3, "side", outside.map({True: "outside", False: "inside"}))
    return table


def _write_mask(path: Path, mask, ctx) -> None:
    import rasterio

    with rasterio.open(path, "w", driver="GTiff", width=ctx.grid.ncols, height=ctx.grid.nrows, count=1,
                       dtype="uint8", crs=ctx.crs, transform=ctx.grid.transform(), compress="deflate") as dst:
        dst.write(mask.astype("uint8"), 1)


def run_job(job_dir: Path, entry_path: Path, settings: Settings | None = None) -> None:
    """Invoke an R entry script against an already-prepared job sandbox.

    Only touches ``settings.ecosimkit_path``, which depends solely on
    ``project_root`` -- not on any active data source -- so a bare
    ``Settings()`` (not ``get_settings()``) is enough here; the sandbox at
    ``job_dir`` was already fully prepared (with real data) by
    ``prepare_job()`` before this runs.
    """
    settings = settings or Settings()
    env = {
        **os.environ,
        "ECOSIM_JOB_DIR": str(job_dir),
        "ECOSIM_KIT_PATH": str(settings.ecosimkit_path),
        # R's own error messages ("Error:", "Execution halted", ...) follow the
        # system locale by default -- force English so a raw R error surfaced
        # in the UI stays consistent with the English-only UI rule.
        "LANGUAGE": "en",
        "LC_MESSAGES": "C",
    }
    try:
        proc = subprocess.run(
            ["Rscript", str(entry_path)],
            cwd=job_dir,
            env=env,
            capture_output=True,
            # Explicit UTF-8, not text=True's locale-default decoding -- R's own
            # traceback rendering (box-drawing chars in dplyr/rlang errors) is
            # UTF-8 and came out as mojibake under Windows' default codepage.
            encoding="utf-8",
            errors="replace",
            timeout=RSCRIPT_TIMEOUT_S,
        )
    except FileNotFoundError as e:
        raise AnalysisRunError(
            "Rscript not found on PATH -- R must be installed to run analyses."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise AnalysisRunError(f"Analysis timed out after {RSCRIPT_TIMEOUT_S}s") from e
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-20:])
        raise AnalysisRunError(f"Rscript exited {proc.returncode}:\n{tail}")


def read_result(job_dir: Path) -> dict:
    result_path = job_dir / "out" / "result.json"
    if not result_path.exists():
        raise AnalysisRunError("Analysis did not write out/result.json")
    return json.loads(result_path.read_text(encoding="utf-8"))


def run_analysis(
    spec: AnalysisSpec,
    manifest: dict,
    params: dict,
    settings: Settings | None = None,
) -> dict:
    """Prepare a sandbox, run the entry script, return {job_id, result}."""
    settings = settings or get_settings()
    job_dir = prepare_job(spec, manifest, params, settings)
    run_job(job_dir, spec.entry_path, settings)
    result = read_result(job_dir)
    return {"job_id": job_dir.name, "result": result}
