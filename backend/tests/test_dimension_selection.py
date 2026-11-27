"""The selection window of each Results-Extractor box (step 5 of the time-series
navigator, UG p.128-129). Most EwE outputs -- e.g. the real ``catch_annual.csv``
(``year\\group,1,2,...,22``) and ``catch-fleet-group_annual.csv``
(``year,fleet,group,value``) -- carry only the numbers, never names; the
predation/prey files carry only names (species in the file name, partners in
the column headers)."""

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
    # Prey "juvcod" (named, lower-cased, by the file) eaten by two predators.
    (run / "predation_juvcod_annual.csv").write_text(
        _HEADER_BLOCK + "Data,PredationMortality of juvcod\n\nyear\\group,AdCod_3,Grey seal\n"
        "2004,0.2,0.05\n2005,0.3,0.06\n",
        encoding="utf-8",
    )
    settings = Settings(output_raw_dir=tmp_path / "raw", store_dir=tmp_path / "store")
    assert not run_ingest(settings).errors
    build_catalog(settings)
    return settings


def _keys(options):
    return [o["key"] for o in options]


def test_functional_groups_box_lists_the_group_numbers_present_per_variable(tmp_path):
    settings = _ingested(tmp_path)
    groups = service.list_selection_options(
        settings, category="functional_groups", variable=["catch", "biomass"],
    )
    assert [g["id"] for g in groups] == [1, 2, 3, 4]
    assert _keys(groups) == ["1", "2", "3", "4"]
    assert all(g["name"] is None for g in groups)  # EwE wrote numbers only
    assert groups[3]["variables"] == ["biomass"]  # group 4 is absent from catch
    assert groups[0]["variables"] == ["biomass", "catch"]
    assert "children" not in groups[0]


def test_fleets_with_attached_prey_lists_each_fleets_own_groups(tmp_path):
    settings = _ingested(tmp_path)
    fleets = service.list_selection_options(
        settings, category="fleets_with_prey", variable=["catch_fleet_group"],
    )
    assert [(f["id"], _keys(f["children"])) for f in fleets] == [(1, ["2", "3"]), (2, ["2"]), (5, ["3"])]


def test_prey_with_attached_predators_works_by_name(tmp_path):
    settings = _ingested(tmp_path)
    assert service.list_datasets(settings)  # catalog built
    prey = service.list_selection_options(settings, category="prey_with_predators", variable=["predation"])
    assert [(p["key"], p["id"], p["name"]) for p in prey] == [("juvcod", None, "juvcod")]
    assert [(c["key"], c["name"]) for c in prey[0]["children"]] == [("adcod_3", "AdCod_3"), ("grey seal", "Grey seal")]
    label = {d["variable"]: d for d in service.list_datasets(settings)}["predation"]
    assert label["label"] == "PredationMortality"  # not "... of juvcod"
    assert (label["n_groups"], label["n_partners"]) == (1, 2)


def test_a_box_without_a_selection_window_has_no_options(tmp_path):
    settings = _ingested(tmp_path)
    assert service.list_selection_options(settings, category="indicators", variable=["catch"]) == []


def test_picks_filter_one_level_and_attached_boxes(tmp_path):
    settings = _ingested(tmp_path)
    rows = service.query_timeseries(settings, variable="catch", picks=[["2"]])
    assert {r["group_id"] for r in rows} == {2}
    rows = service.query_timeseries(settings, variable="catch_fleet_group", picks=[["1", "3"], ["5", "3"]])
    assert sorted((r["fleet_id"], r["group_id"]) for r in rows) == [(1, 3), (5, 3)]
    rows = service.query_timeseries(settings, variable="predation", picks=[["juvcod", "grey seal"]])
    assert {(r["group_name"], r["partner_name"]) for r in rows} == {("juvcod", "Grey seal")}
    assert len(rows) == 2
    # An explicitly empty selection selects nothing; a box without a window ignores picks.
    assert service.query_timeseries(settings, variable="catch", picks=[]) == []


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
    groups = service.list_selection_options(settings, category="functional_groups", variable=["catch"])
    assert [(g["id"], g["name"]) for g in groups] == [(1, None), (2, "JuvCod"), (3, "AdCod_3")]
    rows = service.query_timeseries(settings, variable="catch", group_id=[3])
    assert {r["group_name"] for r in rows} == {"AdCod_3"}


def test_named_species_get_their_ecopath_numbers(tmp_path):
    settings = _ingested(tmp_path)
    _register_ecopath_names(tmp_path, {"1": "Grey seal", "2": "JuvCod", "3": "AdCod_3"})
    prey = service.list_selection_options(settings, category="prey_with_predators", variable=["predation"])
    # Ordered by number, in Ecopath's spelling; the key stays what the data holds.
    assert [(p["key"], p["id"], p["name"]) for p in prey] == [("juvcod", 2, "JuvCod")]
    assert [(c["id"], c["name"]) for c in prey[0]["children"]] == [(1, "Grey seal"), (3, "AdCod_3")]
    rows = service.query_timeseries(settings, variable="predation", picks=[["juvcod", "adcod_3"]])
    assert {(r["group_id"], r["group_name"], r["partner_id"], r["partner_name"]) for r in rows} == {
        (2, "JuvCod", 3, "AdCod_3"),
    }


def test_names_of_another_model_are_not_used(tmp_path):
    settings = _ingested(tmp_path)
    _register_ecopath_names(tmp_path, {"2": "JuvCod"}, conflicts=["Test Model"])
    groups = service.list_selection_options(settings, category="functional_groups", variable=["catch"])
    assert all(g["name"] is None for g in groups)


def test_biomass_rows_carry_their_groups_ecopath_baseline(tmp_path):
    settings = _ingested(tmp_path)
    _register_ecopath_names(tmp_path, {"2": "JuvCod"}, baseline={"2": 1.9, "3": 3.1})
    rows = service.query_timeseries(settings, variable="biomass", group_id=[2, 4])
    assert {(r["group_id"], r["baseline"]) for r in rows} == {(2, 1.9), (4, None)}
    # Only biomass is in Ecopath B's units -- catch gets no baseline.
    assert all(r["baseline"] is None for r in service.query_timeseries(settings, variable="catch"))


def test_export_writes_one_csv_per_variable_with_role_columns(tmp_path):
    import io
    import zipfile

    from ecosim.export.timeseries_csv import table, write_timeseries_zip

    settings = _ingested(tmp_path)
    rows = service.query_timeseries(settings, variable="predation", picks=[["juvcod", "grey seal"]])
    df = table(rows, category="prey_with_predators", freq="annual", yearly=False)
    assert list(df.columns) == ["model", "scenario", "year", "prey_id", "prey", "predator_id", "predator", "value"]
    assert df["predator"].tolist() == ["Grey seal", "Grey seal"]

    out = io.BytesIO()
    n = write_timeseries_zip(out, [
        {"variable": "predation", "label": "PredationMortality", "box": "Prey with attached predators",
         "category": "prey_with_predators", "scenarios": ["test_scenario"], "selection": "juvcod: Grey seal",
         "rows": rows},
        {"variable": "catch", "label": "Catch", "box": "Functional groups only", "category": "functional_groups",
         "scenarios": ["test_scenario"], "selection": "all", "rows": []},  # nothing selected: no file
    ], selection={"freq": "annual", "yearly": False, "years": "2004-2005", "data_source": "test"})
    assert n == 1
    names = zipfile.ZipFile(out).namelist()
    assert sorted(names) == [
        "README.txt", "Test-Model__test_scenario__predation__annual__2004-2005.csv", "selection.json",
    ]


def test_yearly_is_the_mean_over_the_months():
    from ecosim.export.timeseries_csv import table

    rows = [
        {"model": "m", "model_name": "M", "scenario": "s", "year": 2004, "month": m, "group_id": 1,
         "group_name": "Cod", "fleet_id": None, "fleet_name": None, "partner_id": None,
         "partner_name": None, "value": float(m)}
        for m in range(1, 13)
    ] + [
        {"model": "m", "model_name": "M", "scenario": "s", "year": 2005, "month": 1, "group_id": 1,
         "group_name": "Cod", "fleet_id": None, "fleet_name": None, "partner_id": None,
         "partner_name": None, "value": 4.0},
    ]
    df = table(rows, category="functional_groups", freq="monthly", yearly=True)
    assert list(df.columns) == ["model", "scenario", "year", "group_id", "group", "value", "n_months"]
    assert df[["year", "value", "n_months"]].values.tolist() == [[2004, 6.5, 12], [2005, 4.0, 1]]
