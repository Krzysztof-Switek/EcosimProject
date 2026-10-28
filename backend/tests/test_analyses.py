"""Tests for the Etap 3 analysis registry + job runner."""

from __future__ import annotations

import json
import shutil

import pandas as pd
import pytest

from ecosim.analyses import registry, runner
from ecosim.catalog.build import build_catalog
from ecosim.core.config import Settings
from ecosim.ingestion.pipeline import run_ingest


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


# Each job test builds its own small canonical store under tmp_path (synthetic
# EwE biomass output, numbers-only header like the real biomass_annual.csv)
# rather than querying whatever real data source happens to be active on this
# machine -- they used to, with group *names* and a scenario from a dataset
# that no longer exists, and failed for months as a result.
_HEADER_BLOCK = (
    '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
    '"<HEADER ecosim/>"\nEcosimScenario,test_scenario\nStartYear,1998\n'
    '"<HEADER end/>"\n\n'
)


@pytest.fixture
def store(tmp_path) -> Settings:
    run = tmp_path / "raw" / "ecosim_test_scenario"
    run.mkdir(parents=True)
    years = "".join(f"{y},{1 + y % 7},{2 + y % 5},{3 + y % 3}\n" for y in range(1998, 2006))
    (run / "biomass_annual.csv").write_text(
        _HEADER_BLOCK + "Data,Biomass\n\nyear\\group,1,2,3\n" + years, encoding="utf-8",
    )
    settings = Settings(output_raw_dir=tmp_path / "raw", store_dir=tmp_path / "store")
    assert not run_ingest(settings).errors
    build_catalog(settings)
    return settings


def _manifest(**overrides) -> dict:
    manifest = {
        "variables": [{"variable": "biomass", "domain": "output", "scenarios": ["test_scenario"]}],
        "freq": "annual",
        "group_ids": [2, 3],
        "year_from": 1998,
        "year_to": 2000,
    }
    manifest.update(overrides)
    return manifest


def test_prepare_job_writes_sandbox_contract(store):
    spec = registry.get_analysis("biomass_trend_compare")
    job_dir = runner.prepare_job(spec, _manifest(), {"smoothing": 3, "relative": False}, store)
    assert (job_dir / "manifest.json").exists()
    assert (job_dir / "params.json").exists()
    assert (job_dir / "data" / "timeseries.parquet").exists()
    # No groups.csv/fleets.csv any more -- that external dictionary was
    # removed entirely 2026-08-28 (see
    # docs/Plans and TO_DO lists/28.08_session_summary.md); only real
    # Ecosim structure (scenarios) is exported into the sandbox.
    assert not (job_dir / "data" / "dictionaries" / "groups.csv").exists()
    assert not (job_dir / "data" / "dictionaries" / "fleets.csv").exists()
    assert (job_dir / "data" / "dictionaries" / "scenarios.csv").exists()
    assert (job_dir / "out").is_dir()

    written_manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    assert written_manifest["analysis_id"] == "biomass_trend_compare"
    assert written_manifest["created_at"]  # non-empty ISO timestamp, added by prepare_job()

    df = pd.read_parquet(job_dir / "data" / "timeseries.parquet")
    assert (df["variable"] == "biomass").all()
    assert (df["scenario"] == "test_scenario").all()
    assert set(df["group_id"]) == {2, 3}  # selected by EwE group number
    assert set(df["year"]) == {1998, 1999, 2000}


def test_prepare_job_empty_selection_raises_clear_error(store):
    # A selection that matches zero rows (e.g. a group with no data for this
    # variable/scenario) used to reach R and blow up deep inside dplyr/stats
    # with a cryptic traceback -- confirm it's now caught before R ever runs.
    spec = registry.get_analysis("biomass_trend_compare")
    with pytest.raises(runner.AnalysisRunError, match="No data matched"):
        runner.prepare_job(spec, _manifest(group_ids=[99]), {"smoothing": 3, "relative": False}, store)
    # No partially-materialized timeseries.parquet left behind for any job dir.
    assert not list(store.jobs_dir.glob("job_*/data/timeseries.parquet"))


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


@pytest.mark.skipif(not shutil.which("Rscript"), reason="Rscript not installed")
def test_run_analysis_end_to_end_produces_real_artifacts(store):
    spec = registry.get_analysis("biomass_trend_compare")
    outcome = runner.run_analysis(spec, _manifest(year_to=2005), {"smoothing": 3, "relative": False}, store)
    job_dir = store.jobs_dir / outcome["job_id"]
    result = outcome["result"]
    assert result["status"] == "ok"
    assert {a["type"] for a in result["artifacts"]} == {"figure", "table"}
    for artifact in result["artifacts"]:
        assert (job_dir / "out" / artifact["path"]).exists()
    # The summary is per EwE group number, labelled "Group N" (the file has no names).
    table = next(a for a in result["artifacts"] if a["type"] == "table")
    summary = pd.read_csv(job_dir / "out" / table["path"])
    assert sorted(summary["group_id"]) == [2, 3]
    assert sorted(summary["group"]) == ["Group 2", "Group 3"]
