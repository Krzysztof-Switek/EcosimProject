"""Picking functional groups and fleets by EwE's own numbers (steps 5 and 6 of the
time-series navigator). Most EwE outputs -- e.g. the real ``catch_annual.csv``
(``year\\group,1,2,...,22``) and ``catch-fleet-group_annual.csv``
(``year,fleet,group,value``) -- carry only the numbers, never names, so selecting
by name (the only filter that existed before) matched nothing at all."""

from __future__ import annotations

from ecosim.catalog import service
from ecosim.catalog.build import build_catalog
from ecosim.core.config import Settings
from ecosim.ingestion.pipeline import run_ingest

_HEADER_BLOCK = (
    '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
    '"<HEADER ecosim/>"\nEcosimScenario,test_scenario\nStartYear,2004\n'
    '"<HEADER end/>"\n\n'
)


def _ingested(tmp_path) -> Settings:
    run = tmp_path / "raw" / "ecosim_test_scenario"
    run.mkdir(parents=True)
    (run / "catch_annual.csv").write_text(
        _HEADER_BLOCK + "Data,Catch\n\nyear\\group,1,2,3\n2004,0,0.5,0.25\n2005,0,0.4,0.2\n",
        encoding="utf-8",
    )
    (run / "biomass_annual.csv").write_text(
        _HEADER_BLOCK + "Data,Biomass\n\nyear\\group,1,2,3,4\n2004,1,2,3,4\n2005,1,2,3,4\n",
        encoding="utf-8",
    )
    (run / "catch-fleet-group_annual.csv").write_text(
        _HEADER_BLOCK + "Data,CatchFleetGroup\n\nyear,fleet,group,value\n"
        "2004,1,2,0.1\n2004,1,3,0.2\n2004,2,2,0.3\n2004,5,3,0.4\n",
        encoding="utf-8",
    )
    settings = Settings(output_raw_dir=tmp_path / "raw", store_dir=tmp_path / "store")
    assert not run_ingest(settings).errors
    build_catalog(settings)
    return settings


def test_list_groups_returns_the_group_numbers_present_per_variable(tmp_path):
    settings = _ingested(tmp_path)
    groups = service.list_dimension(settings, dimension="group", variable=["catch", "biomass"])
    assert [g["id"] for g in groups] == [1, 2, 3, 4]
    assert all(g["name"] is None for g in groups)  # EwE wrote numbers only
    assert groups[3]["variables"] == ["biomass"]  # group 4 is absent from catch
    assert groups[0]["variables"] == ["biomass", "catch"]


def test_list_fleets_returns_the_fleet_numbers_present(tmp_path):
    settings = _ingested(tmp_path)
    fleets = service.list_dimension(
        settings, dimension="fleet", variable=["catch_fleet_group", "catch"],
    )
    assert [f["id"] for f in fleets] == [1, 2, 5]
    assert all(f["variables"] == ["catch_fleet_group"] for f in fleets)


def test_query_timeseries_filters_by_group_number(tmp_path):
    settings = _ingested(tmp_path)
    rows = service.query_timeseries(settings, variable="catch", freq="annual", group_id=[2, 3])
    assert {r["group_id"] for r in rows} == {2, 3}
    assert len(rows) == 4  # 2 groups x 2 years
    assert next(r["value"] for r in rows if r["group_id"] == 2 and r["year"] == 2004) == 0.5


def test_query_timeseries_filters_by_fleet_and_group_number_together(tmp_path):
    settings = _ingested(tmp_path)
    rows = service.query_timeseries(
        settings, variable="catch_fleet_group", freq="annual", fleet_id=[1, 2], group_id=[2],
    )
    assert sorted((r["fleet_id"], r["group_id"], r["value"]) for r in rows) == [(1, 2, 0.1), (2, 2, 0.3)]


def _register_ecopath_names(tmp_path, groups: dict, conflicts: list | None = None, baseline: dict | None = None) -> None:
    """An output source whose Ecopath results named the groups of "Test Model"."""
    from ecosim.core.workspace import get_workspace_registry

    folder = tmp_path / "ecopath_run"
    folder.mkdir()
    registry = get_workspace_registry()
    source = registry.add_source("ecopath run", folder, "output")
    ecopath = {"files": 1, "models": ["Test Model"], "groups": {"Test Model": groups}}
    if conflicts:
        ecopath["group_conflicts"] = conflicts
    if baseline:
        ecopath["baseline_biomass"] = {"Test Model": baseline}
    registry.set_models(source.id, {"ecopath": ecopath, "not_checked": 0, "version": 2})


def test_group_numbers_get_names_from_the_models_ecopath_output(tmp_path):
    settings = _ingested(tmp_path)
    _register_ecopath_names(tmp_path, {"2": "JuvCod", "3": "AdCod_3"})
    groups = service.list_dimension(settings, dimension="group", variable=["catch"])
    assert [(g["id"], g["name"]) for g in groups] == [(1, None), (2, "JuvCod"), (3, "AdCod_3")]
    rows = service.query_timeseries(settings, variable="catch", group_id=[3])
    assert {r["group_name"] for r in rows} == {"AdCod_3"}


def test_names_of_another_model_are_not_used(tmp_path):
    settings = _ingested(tmp_path)
    _register_ecopath_names(tmp_path, {"2": "JuvCod"}, conflicts=["Test Model"])
    groups = service.list_dimension(settings, dimension="group", variable=["catch"])
    assert all(g["name"] is None for g in groups)


def test_biomass_rows_carry_their_groups_ecopath_baseline(tmp_path):
    settings = _ingested(tmp_path)
    _register_ecopath_names(tmp_path, {"2": "JuvCod"}, baseline={"2": 1.9, "3": 3.1})
    rows = service.query_timeseries(settings, variable="biomass", group_id=[2, 4])
    assert {(r["group_id"], r["baseline"]) for r in rows} == {(2, 1.9), (4, None)}
    # Only biomass is in Ecopath B's units -- catch gets no baseline.
    assert all(r["baseline"] is None for r in service.query_timeseries(settings, variable="catch"))
