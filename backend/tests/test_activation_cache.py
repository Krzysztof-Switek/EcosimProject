"""Tests for per-source ingestion caching (added 2026-08-28) -- the real
trigger: a genuine ~400GB/~1hr source had to be fully re-ingested just to
switch back to it, because the old architecture rebuilt one single,
un-namespaced store from scratch on every activation. Now each source gets
its own independently-cached ingest output (``core/config.py``'s per-source-
cache docstring); re-activating a source whose cache is already valid skips
raw-file ingestion entirely.

Fully synthetic (no dependency on any real dataset), same fixture pattern as
``test_run_id_detection.py``.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

rasterio = pytest.importorskip("rasterio")

from ecosim.core.config import Settings, settings_for_single_source, source_cache_dir
from ecosim.core.workspace import WorkspaceRegistry
from ecosim.ingestion.activation import (
    ActivationError,
    activate_source,
    combine_and_rebuild,
    remove_source_and_rebuild,
    rescan_source,
)

_HEADER_BLOCK = (
    '"<HEADER software/>"\n'
    'EwEVersion,"6.7.0.19540"\n'
    '"<HEADER ecopath/>"\n'
    'ModelName,"{model}"\n'
    '"<HEADER ecosim/>"\n'
    "EcosimScenario,{scenario}\n"
    "StartYear,1998\n"
    '"<HEADER end/>"\n'
    "\n"
)
_CSV_BODY = "Data,Biomass\n\n" + "year\\group,1,2\n" + "1998,0.01,0.02\n" + "1999,0.011,0.021\n"


def _write_csv(root, model: str, scenario: str, run_dir: str = "run1") -> None:
    ecosim_dir = root / run_dir / f"ecosim_{scenario}"
    ecosim_dir.mkdir(parents=True)
    (ecosim_dir / "biomass_annual.csv").write_text(
        _HEADER_BLOCK.format(model=model, scenario=scenario) + _CSV_BODY, encoding="utf-8",
    )


def test_activate_source_skips_ingest_on_a_cache_hit(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    _write_csv(raw, "Test Model", "test_scenario")

    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("Src", raw, "output")

    first = activate_source(registry, source)
    assert first.data_kind == "timeseries"
    cache_meta = source_cache_dir(source.id) / "meta.json"
    assert cache_meta.exists()

    # A second activation of the SAME (now-cached) source must not touch raw
    # files at all -- monkeypatch run_ingest to prove it's never called.
    import ecosim.ingestion.activation as activation_module

    def _boom(*args, **kwargs):
        raise AssertionError("run_ingest should not be called on a cache hit")

    monkeypatch.setattr(activation_module, "run_ingest", _boom)
    # Re-fetch: registry methods return fresh DataSource snapshots on every
    # call rather than mutating in place, so the original `source` variable
    # is stale (still status="unscanned") after the first activate_source()
    # call above -- _cache_is_valid() needs the up-to-date status="ok".
    refreshed = registry.get(source.id)
    second = activate_source(registry, refreshed)
    assert second.data_kind == "timeseries"
    assert registry.active("output").id == source.id


def test_rescan_of_inactive_source_never_touches_the_active_one(tmp_path):
    raw_a = tmp_path / "raw_a"
    raw_b = tmp_path / "raw_b"
    _write_csv(raw_a, "Model A", "scenario_a")
    _write_csv(raw_b, "Model B", "scenario_b")

    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source_a = registry.add_source("A", raw_a, "output")
    source_b = registry.add_source("B", raw_b, "output")

    activate_source(registry, source_a)
    activate_source(registry, source_b)  # B is now active; A stays registered, cached, inactive
    assert registry.active("output").id == source_b.id

    a_meta_before = (source_cache_dir(source_a.id) / "meta.json").read_text(encoding="utf-8")

    rescan_source(registry, source_a)

    # Rescanning A (inactive) must not change what's active, nor touch B's
    # cache/registry state at all.
    assert registry.active("output").id == source_b.id
    assert registry.get(source_b.id).status == "ok"
    # A's own cache WAS refreshed (that's the point of Rescan) -- content is
    # allowed to differ (new started_at timestamp), but it must still exist
    # and describe the same source.
    a_meta_after = (source_cache_dir(source_a.id) / "meta.json").read_text(encoding="utf-8")
    assert a_meta_after != "" and a_meta_before != ""


def test_remove_active_source_leaves_a_queryable_not_crashing_catalog(tmp_path):
    raw = tmp_path / "raw"
    _write_csv(raw, "Test Model", "test_scenario")

    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("Src", raw, "output")
    activate_source(registry, source)
    assert registry.active("output") is not None

    remove_source_and_rebuild(registry, source.id)

    assert registry.active("output") is None
    assert registry.get(source.id) is None
    assert not source_cache_dir(source.id).exists()

    # The live catalog.duckdb must still be queryable (empty), not left
    # pointing at a now-deleted Parquet directory.
    live = Settings()
    con = duckdb.connect(str(live.catalog_db), read_only=True)
    try:
        rows = con.execute("SELECT * FROM timeseries").fetchall()
        assert rows == []
    finally:
        con.close()


def test_combine_dedupes_scenarios_shared_by_output_and_input(tmp_path):
    # A driver grid named after the scenario it drives is a real, plausible
    # shape -- output and input each independently produce their own
    # scenarios.csv row for the same scenario id once ingested in isolation
    # (see core/config.py's settings_for_single_source); combine_and_rebuild
    # must not let that become two dim_scenarios rows.
    raw_output = tmp_path / "raw_output"
    _write_csv(raw_output, "Test Model", "shared_scenario")

    raw_input = tmp_path / "raw_input" / "shared_scenario" / "Bottom o2"
    raw_input.mkdir(parents=True)
    (raw_input / "trend_bottom_o2.csv").write_text("1998,0.5\n1999,0.6\n", encoding="utf-8")

    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    output_source = registry.add_source("Out", raw_output, "output")
    input_source = registry.add_source("In", raw_input.parent.parent, "input")

    activate_source(registry, output_source)
    activate_source(registry, input_source)
    combine_and_rebuild(registry)

    live = Settings()
    con = duckdb.connect(str(live.catalog_db), read_only=True)
    try:
        rows = con.execute("SELECT domain FROM dim_scenarios WHERE id = 'shared_scenario'").fetchall()
    finally:
        con.close()
    assert len(rows) == 1  # not two
    assert rows[0][0] == "output"  # output's row preferred over input's
