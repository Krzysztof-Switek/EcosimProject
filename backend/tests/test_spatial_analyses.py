"""R analyses of maps within areas (analyses/runner.prepare_spatial, the
spatial_* plugins in rkit/analyses, ecosimkit.R's ecosim_load_zonal)."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pandas as pd
import pytest

from ecosim.analyses import registry, runner
from ecosim.core.config import Settings
from ecosim.regions import zonal
from test_regions import SD, SUBDIVISIONS, _area, _write_asc, imported  # noqa: F401 -- fixture


def test_complement_is_the_rest_of_the_grid(imported, tmp_path, monkeypatch):
    monkeypatch.setattr(zonal, "cache_dir", lambda: tmp_path / "cache")
    _, ctx = imported
    (inside,) = zonal.build_areas([{"id": "a", "name": "SD 25", "area": _area([SD("25")])}], ctx)
    outside = zonal.complement(inside, ctx)
    assert outside.id == "a__outside" and outside.name == "SD 25 (outside)"
    assert not (inside.mask & outside.mask).any() and (inside.mask | outside.mask).all()
    # land holds no value, so only water outside SD 25 counts: 25 - 7 cells
    values = np.where(SUBDIVISIONS == -9999, np.nan, 2.0)
    stats = zonal.map_stats(values, np.full(values.shape, 16.0), [inside, outside])
    assert stats[0]["n_cells"] == 7 and stats[1]["n_cells"] == 25 - 7


def test_zonal_table_marks_inside_and_outside():
    rows = [{"area_id": "a", "entity": None, "year": 2004, "mean": 2.0},
            {"area_id": "a__outside", "entity": None, "year": 2004, "mean": 1.0}]
    t = runner.zonal_table(rows, {"a": "SD 25", "a__outside": "SD 25 (outside)"})
    assert list(t["area"]) == ["a", "a"] and list(t["side"]) == ["inside", "outside"]
    assert list(t["area_name"]) == ["SD 25", "SD 25 (outside)"]


def test_spatial_analyses_listed_for_the_spatial_view_only():
    specs = {s.id: s for s in registry.list_analyses()}
    assert specs["spatial_aoi_summary"].context == "spatial"
    assert specs["spatial_inside_outside"].requires.get("outside") is True
    assert specs["biomass_trend_compare"].context == "timeseries"


def test_spatial_analysis_needs_maps_and_areas(tmp_path):
    spec = registry.get_analysis("spatial_aoi_summary")
    with pytest.raises(runner.AnalysisRunError, match="Spatial data"):
        runner.prepare_spatial(spec, {}, tmp_path)
    with pytest.raises(runner.AnalysisRunError, match="at least one area"):
        runner.prepare_spatial(spec, {"spatial": {"scenario": "s", "variable": "biomass"}}, tmp_path)


def _job_with_zonal(tmp_path, *, outside: bool, band: bool) -> tuple:
    job = tmp_path / "job"
    (job / "data").mkdir(parents=True)
    (job / "out").mkdir()
    rows = []
    for year in range(2004, 2010):
        for area_id, base in [("a", 10.0), *([("a__outside", 6.0)] if outside else [])]:
            r = {"area_id": area_id, "entity": "Cod", "year": year, "mean": base + 0.5 * (year - 2004),
                 "total": (base + 0.5 * (year - 2004)) * 112, "n_cells": 7, "coverage": 1.0}
            if band:
                r.update(mean_p05=r["mean"] - 1, mean_p95=r["mean"] + 1, n_samples=20)
            rows.append(r)
    t = runner.zonal_table(rows, {"a": "SD 25", "a__outside": "SD 25 (outside)"})
    t["scenario"], t["variable"], t["semantics"] = "s", "biomass", "density"
    t.to_parquet(job / "data" / "zonal.parquet", index=False)
    (job / "manifest.json").write_text("{}", encoding="utf-8")
    return job, t


@pytest.mark.skipif(not shutil.which("Rscript"), reason="Rscript not installed")
@pytest.mark.parametrize("statistic", ["mean", "total"])
def test_aoi_summary_plugin_end_to_end(tmp_path, statistic):
    job, _ = _job_with_zonal(tmp_path, outside=False, band=True)
    (job / "params.json").write_text(json.dumps({"statistic": statistic}), encoding="utf-8")
    spec = registry.get_analysis("spatial_aoi_summary")
    runner.run_job(job, spec.entry_path, Settings())
    result = runner.read_result(job)
    assert {a["type"] for a in result["artifacts"]} == {"figure", "table"}
    trend = pd.read_csv(job / "out" / "tables" / "area_trend.csv")
    expected_slope = 0.5 if statistic == "mean" else 0.5 * 112
    assert trend.loc[0, "slope_per_year"] == pytest.approx(expected_slope)
    assert trend.loc[0, "years"] == "2004-2009"


@pytest.mark.skipif(not shutil.which("Rscript"), reason="Rscript not installed")
def test_inside_outside_plugin_end_to_end(tmp_path):
    job, _ = _job_with_zonal(tmp_path, outside=True, band=False)
    (job / "params.json").write_text("{}", encoding="utf-8")
    spec = registry.get_analysis("spatial_inside_outside")
    runner.run_job(job, spec.entry_path, Settings())
    stats = pd.read_csv(job / "out" / "tables" / "inside_outside.csv")
    assert stats.loc[0, "years"] == 6
    assert stats.loc[0, "mean_difference"] == pytest.approx(4.0)
    assert stats.loc[0, "ratio"] == pytest.approx(11.25 / 7.25)
