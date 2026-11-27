"""Zonal statistics over areas (regions/zonal.py), on the synthetic pack of
test_regions.py: the 6x5 EPSG:3035 grid with 4 km (16 km²) cells."""

from __future__ import annotations

import os

import numpy as np
import pytest

from ecosim.regions import zonal
from regions_helpers import SD, SUBDIVISIONS, _area, _write_asc


@pytest.fixture(autouse=True)
def _cache_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(zonal, "cache_dir", lambda: tmp_path / "zonal_cache")


def _map(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_asc(path, values, crs_epsg=4326)  # EwE declares WGS 84; the pack's CRS is used
    return path


def _plan(ctx, rows, *, variable="biomass", run=None, run_kinds=None, areas=None):
    areas = areas or [{"id": "a", "name": "SD 25", "area": _area([SD("25")])}]
    req = zonal.ZonalRequest(scenario="s", variable=variable, areas=areas, run=run)
    built = zonal.build_areas(areas, ctx)
    for r in rows:
        r["_stamp"] = zonal._file_stamp(r["source_path"])
    cached = {a.key: zonal.load_cache(a.key) for a in built}
    todo = [r for r in rows if not all(zonal._fresh(cached[a.key].get(r["id"]), r) for a in built)]
    return zonal.ZonalPlan(req, {"status": "matched"}, ctx, built, rows, run_kinds or {}, cached, todo, [])


def _row(rid, path, year, run_id=None):
    return {"id": rid, "source_path": str(path), "year": year, "run_id": run_id, "group_name": "Cod"}


def test_density_mean_total_and_coverage(imported, tmp_path):
    _, ctx = imported
    values = np.where(SUBDIVISIONS == -9999, -9999, 2.0)
    values[1, 0] = -9999  # one SD 25 water cell with no value in the model map
    p = _map(tmp_path / "m" / "EcospaceMapBiomass-Cod-00001.asc", values)
    out = zonal.compute(_plan(ctx, [_row("r1", p, 2004)]))
    (row,) = out["rows"]
    assert row["n_cells"] == 6 and row["coverage"] == pytest.approx(6 / 7)
    assert row["mean"] == pytest.approx(2.0)
    assert row["total"] == pytest.approx(2.0 * 6 * 16)  # t/km² x km²
    assert out["areas"][0] == {"id": "a", "name": "SD 25", "cells": 7, "area_km2": 112.0}
    assert out["semantics"] == "density" and out["maps_missing"] == 0


def test_indicator_has_mean_only(imported, tmp_path):
    _, ctx = imported
    p = _map(tmp_path / "m" / "biodiv_ind_Shannon diversity-0012.asc", np.where(SUBDIVISIONS == -9999, -9999, 3.0))
    out = zonal.compute(_plan(ctx, [_row("r1", p, 2004)], variable="ecoind_shannon_diversity"))
    assert "total" not in out["rows"][0] and out["semantics"] == "indicator"


def test_cache_reused_and_refreshed_when_the_file_changes(imported, tmp_path, monkeypatch):
    _, ctx = imported
    p = _map(tmp_path / "m" / "a.asc", np.where(SUBDIVISIONS == -9999, -9999, 1.0))
    zonal.compute(_plan(ctx, [_row("r1", p, 2004)]))
    plan = _plan(ctx, [_row("r1", p, 2004)])
    assert plan.todo == [] and plan.inline  # cached: nothing to read
    reads = []
    real_read = zonal.read_values
    monkeypatch.setattr(zonal, "read_values", lambda *a: reads.append(a) or real_read(*a))
    assert zonal.compute(plan)["rows"][0]["mean"] == pytest.approx(1.0) and not reads
    _map(p, np.where(SUBDIVISIONS == -9999, -9999, 5.0))
    os.utime(p, ns=(1, 1))  # a different modification time
    plan = _plan(ctx, [_row("r1", p, 2004)])
    assert len(plan.todo) == 1
    assert zonal.compute(plan)["rows"][0]["mean"] == pytest.approx(5.0) and len(reads) == 1


def test_same_cells_share_a_cache_key(imported):
    _, ctx = imported
    a = zonal.build_areas([{"id": "x", "name": "x", "area": _area([SD("25", "26")])}], ctx)[0]
    b = zonal.build_areas([{"id": "y", "name": "y", "area": _area([SD("26"), SD("25")])}], ctx)[0]
    c = zonal.build_areas([{"id": "z", "name": "z", "area": _area([SD("25")])}], ctx)[0]
    assert a.key == b.key != c.key


def test_monte_carlo_summary_baseline_and_percentiles(imported, tmp_path):
    _, ctx = imported
    rows, kinds = [], {}
    for i, (run, kind, v) in enumerate([("Sample_baseline", "baseline", 10.0)]
                                        + [(f"Sample_{n:05d}", "sample", float(n)) for n in range(1, 21)]):
        p = _map(tmp_path / run / "m.asc", np.where(SUBDIVISIONS == -9999, -9999, v))
        rows.append(_row(f"r{i}", p, 2004, run))
        kinds[run] = kind
    out = zonal.compute(_plan(ctx, rows, run="all", run_kinds=kinds))
    (row,) = out["rows"]
    assert row["mean"] == pytest.approx(10.0)  # the baseline, not the samples' median
    assert row["n_samples"] == 20
    assert row["mean_p05"] == pytest.approx(np.quantile(np.arange(1, 21), 0.05))
    assert row["mean_p95"] == pytest.approx(np.quantile(np.arange(1, 21), 0.95))
    assert row["total"] == pytest.approx(10.0 * 7 * 16)


def test_map_on_another_grid_is_reported_not_counted(imported, tmp_path):
    _, ctx = imported
    good = _map(tmp_path / "m" / "a.asc", np.where(SUBDIVISIONS == -9999, -9999, 1.0))
    bad = tmp_path / "m" / "b.asc"
    _write_asc(bad, np.zeros((3, 3)), crs_epsg=4326, xll=10.0, yll=54.0, cs=0.1)
    out = zonal.compute(_plan(ctx, [_row("r1", good, 2004), _row("r2", bad, 2005)]))
    assert [r["year"] for r in out["rows"]] == [2004]
    assert out["maps_missing"] == 1 and "different grid" in out["problems"][0]


def test_area_without_cells_is_rejected(imported):
    _, ctx = imported
    empty = _area([SD("28.2")], [{"kind": "regions", "layer": "03_natura2000_2024"}])
    with pytest.raises(zonal.AreaError, match="no cells"):
        zonal.build_areas([{"id": "e", "name": "Empty", "area": empty}], ctx)


def test_cancel_keeps_what_was_done(imported, tmp_path):
    import threading

    _, ctx = imported
    p = _map(tmp_path / "m" / "a.asc", np.where(SUBDIVISIONS == -9999, -9999, 1.0))
    stop = threading.Event()
    stop.set()
    out = zonal.compute(_plan(ctx, [_row("r1", p, 2004)]), cancel_event=stop)
    assert out["cancelled"] and out["rows"] == [] and out["maps_missing"] == 1


def test_cache_is_per_source_file(imported, tmp_path):
    _, ctx = imported
    a = _map(tmp_path / "src1" / "m.asc", np.where(SUBDIVISIONS == -9999, -9999, 1.0))
    b = _map(tmp_path / "src2" / "m.asc", np.where(SUBDIVISIONS == -9999, -9999, 4.0))
    os.utime(b, ns=(os.stat(a).st_atime_ns, os.stat(a).st_mtime_ns))  # same size and time
    zonal.compute(_plan(ctx, [_row("r1", a, 2004)]))
    plan = _plan(ctx, [_row("r1", b, 2004)])  # same raster id, another source's file
    assert len(plan.todo) == 1 and zonal.compute(plan)["rows"][0]["mean"] == pytest.approx(4.0)
