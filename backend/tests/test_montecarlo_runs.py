"""Monte Carlo / Ecosampler runs in time series (catalog/runs.py): one row per
point with the baseline run's value and the samples' 5th-95th percentile, or one
chosen run -- never the runs' rows mixed together. Layout as in a real Ecosampler
export (RU_SSP1_Calib, 2026-10-30): Sample_baseline + Sample_NNNNN folders."""

from __future__ import annotations

import pytest

from ecosim.catalog import service
from ecosim.catalog.build import build_catalog
from ecosim.catalog.runs import run_label, run_roots
from ecosim.core.config import Settings
from ecosim.ingestion.pipeline import run_ingest

_HEADER_BLOCK = (
    '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
    '"<HEADER ecosim/>"\nEcosimScenario,mc\nStartYear,2004\n'
    '"<HEADER end/>"\n\n'
)


@pytest.fixture
def store(tmp_path) -> Settings:
    raw = tmp_path / "raw"
    runs = {"Sample_baseline": 1.0, **{f"Sample_{i:05d}": 1.0 + i / 100 for i in range(1, 21)}}
    for folder, b in runs.items():
        run = raw / "Calib" / folder / "ecosim_mc"
        run.mkdir(parents=True)
        (run / "biomass_annual.csv").write_text(
            _HEADER_BLOCK + f"Data,Biomass\n\nyear\\group,1\n2004,{b}\n2005,{2 * b}\n", encoding="utf-8",
        )
    settings = Settings(output_raw_dir=raw, store_dir=tmp_path / "store")
    assert not run_ingest(settings).errors
    build_catalog(settings)
    return settings


def test_runs_are_listed_baseline_first(store):
    runs = service.list_runs(store, scenario=["mc"])
    assert [r["label"] for r in runs][:3] == ["Sample_baseline", "Sample_00001", "Sample_00002"]
    assert [r["kind"] for r in runs].count("sample") == 20


def test_summary_is_the_baseline_with_the_samples_percentiles(store):
    rows = service.query_timeseries(store, variable="biomass", scenario=["mc"])
    assert len(rows) == 2  # one per year, not one per run
    r2004 = next(r for r in rows if r["year"] == 2004)
    assert r2004["value"] == 1.0  # the baseline run, not a mean of the samples
    assert r2004["n_samples"] == 20
    # samples 1.01 .. 1.20: linear-interpolated 5th/95th percentiles
    assert r2004["p05"] == pytest.approx(1.0195)
    assert r2004["p95"] == pytest.approx(1.1905)


def test_one_run_on_request(store):
    run = next(r["run_id"] for r in service.list_runs(store) if r["label"] == "Sample_00007")
    rows = service.query_timeseries(store, variable="biomass", scenario=["mc"], run=run)
    assert [r["value"] for r in rows] == [1.07, 2.14]
    assert "p05" not in rows[0]


def test_run_labels():
    assert run_label("Calib\\Sample_00012\\ecosim_SSP1") == "Sample_00012"
    assert run_label("Calib/Sample_baseline/ecosim_SSP1") == "Sample_baseline"
    assert run_label("RU_SSP1_Calib") == "RU_SSP1_Calib (main run)"
    assert run_label(".") == "Main run"


def test_one_sample_writing_into_several_folders_is_one_run():
    folders = {
        "Calib\\Sample_00001\\ecosim_SSP1", "Calib\\Sample_00001\\SSP1\\RegionAgeStructure",
        "Calib\\Sample_baseline\\ecosim_SSP1", "Calib\\ecosim_SSP1", "Calib\\SSP1\\RegionAgeStructure",
    }
    assert run_roots(folders) == {
        "Calib\\Sample_00001\\ecosim_SSP1": "Calib\\Sample_00001",
        "Calib\\Sample_00001\\SSP1\\RegionAgeStructure": "Calib\\Sample_00001",
        "Calib\\Sample_baseline\\ecosim_SSP1": "Calib\\Sample_baseline",
        "Calib\\ecosim_SSP1": "Calib",  # outside the samples: the main run
        "Calib\\SSP1\\RegionAgeStructure": "Calib",
    }
    # Runs not in Ecosampler folders keep a folder each.
    assert run_roots({"a/run1", "a/run2"}) == {"a/run1": "a/run1", "a/run2": "a/run2"}


def test_yearly_mean_keeps_the_band():
    from ecosim.export.timeseries_csv import table

    rows = [
        {"model": "m", "model_name": "M", "scenario": "s", "year": 2004, "month": m, "group_id": 1,
         "group_name": "Cod", "fleet_id": None, "fleet_name": None, "partner_id": None,
         "partner_name": None, "value": 1.0, "p05": 0.5 + m, "p95": 2.0, "n_samples": 20}
        for m in (1, 2)
    ]
    df = table(rows, category="functional_groups", freq="monthly", yearly=True)
    assert df[["value", "p05", "p95", "n_months", "n_samples"]].values.tolist() == [[1.0, 2.0, 2.0, 2, 20]]
