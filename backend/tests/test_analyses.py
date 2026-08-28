"""Tests for the Etap 3 analysis registry + job runner."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ecosim.analyses import registry, runner
from ecosim.core.config import get_settings
from ecosim.core.workspace import NoActiveDataSourceError

ROOT = Path(__file__).resolve().parents[2]


def test_list_analyses_finds_biomass_trend_compare():
    specs = registry.list_analyses()
    ids = [s.id for s in specs]
    assert "biomass_trend_compare" in ids


def test_get_analysis_spec_fields():
    spec = registry.get_analysis("biomass_trend_compare")
    assert spec is not None
    assert spec.name == "Biomass trend comparison"
    assert spec.requires["variables"] == ["biomass"]
    assert spec.entry == "entry.R"
    assert {p.key for p in spec.params} == {"smoothing", "relative"}
    assert spec.entry_path.exists()


def test_get_analysis_unknown_returns_none():
    assert registry.get_analysis("does_not_exist") is None


# prepare_job needs the real, already-ingested canonical store (DuckDB catalog +
# Parquet timeseries) -- skip if there's no active data source, or the dev
# store hasn't been built yet, same spirit as the raw-data-dependent tests
# elsewhere in this suite.
try:
    _settings = get_settings()
    _catalog_built = _settings.catalog_db.exists()
except NoActiveDataSourceError:
    _catalog_built = False
pytestmark_catalog = pytest.mark.skipif(
    not _catalog_built,
    reason="no active data source / canonical catalog not built (activate a source, run `ecosim ingest` first)",
)


@pytestmark_catalog
def test_prepare_job_writes_sandbox_contract():
    spec = registry.get_analysis("biomass_trend_compare")
    manifest = {
        "scenarios": ["baseline_cumulative"],
        "variables": ["biomass"],
        "freq": "annual",
        "groups": ["Ringed seal"],
        "year_from": 1998,
        "year_to": 2000,
    }
    job_dir = runner.prepare_job(spec, manifest, {"smoothing": 3, "relative": False})
    try:
        assert (job_dir / "manifest.json").exists()
        assert (job_dir / "params.json").exists()
        assert (job_dir / "data" / "timeseries.parquet").exists()
        assert (job_dir / "data" / "dictionaries" / "groups.csv").exists()
        assert (job_dir / "data" / "dictionaries" / "fleets.csv").exists()
        assert (job_dir / "data" / "dictionaries" / "scenarios.csv").exists()
        assert (job_dir / "out").is_dir()

        import pandas as pd

        df = pd.read_parquet(job_dir / "data" / "timeseries.parquet")
        assert (df["variable"] == "biomass").all()
        assert (df["scenario"] == "baseline_cumulative").all()
        assert set(df["year"]).issubset({1998, 1999, 2000})
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


@pytestmark_catalog
def test_prepare_job_empty_selection_raises_clear_error():
    # A selection that matches zero rows (e.g. a group with no data for this
    # variable/scenario) used to reach R and blow up deep inside dplyr/stats
    # with a cryptic traceback -- confirm it's now caught before R ever runs.
    spec = registry.get_analysis("biomass_trend_compare")
    manifest = {
        "scenarios": ["baseline_cumulative"],
        "variables": ["biomass"],
        "freq": "annual",
        "groups": ["Definitely Not A Real Group"],
        "year_from": 1998,
        "year_to": 2000,
    }
    jobs_before = set(get_settings().jobs_dir.glob("job_*"))
    with pytest.raises(runner.AnalysisRunError, match="No data matched"):
        runner.prepare_job(spec, manifest, {"smoothing": 3, "relative": False})
    # No partially-materialized timeseries.parquet left behind for any new job dir.
    for d in set(get_settings().jobs_dir.glob("job_*")) - jobs_before:
        assert not (d / "data" / "timeseries.parquet").exists()
        shutil.rmtree(d, ignore_errors=True)


def test_run_job_missing_rscript_raises_clear_error(tmp_path, monkeypatch):
    # Confirms the failure is a clear AnalysisRunError, not a confusing raw
    # OSError/traceback, when Rscript truly can't be found -- exercised by
    # pointing PATH at an empty directory regardless of whether R is actually
    # installed in this environment.
    empty_path_dir = tmp_path / "empty_path"
    empty_path_dir.mkdir()
    monkeypatch.setenv("PATH", str(empty_path_dir))
    with pytest.raises(runner.AnalysisRunError, match="Rscript not found"):
        runner.run_job(tmp_path, tmp_path / "entry.R")


@pytestmark_catalog
@pytest.mark.skipif(not shutil.which("Rscript"), reason="Rscript not installed")
def test_run_analysis_end_to_end_produces_real_artifacts():
    spec = registry.get_analysis("biomass_trend_compare")
    manifest = {
        "scenarios": ["baseline_cumulative"],
        "variables": ["biomass"],
        "freq": "annual",
        "groups": ["Ringed seal"],
        "year_from": 1998,
        "year_to": 2005,
    }
    outcome = runner.run_analysis(spec, manifest, {"smoothing": 3, "relative": False})
    job_dir = get_settings().jobs_dir / outcome["job_id"]
    try:
        result = outcome["result"]
        assert result["status"] == "ok"
        kinds = {a["type"] for a in result["artifacts"]}
        assert kinds == {"figure", "table"}
        for artifact in result["artifacts"]:
            assert (job_dir / "out" / artifact["path"]).exists()
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
