"""Which EwE model a source's files come from (ingestion/model_origin.py).

Output headers are copied in shape from a real EwE 6.7 export (2026-10-29,
FuMa_SSP1_SCEN); the input time-series CSV follows the manual's own example
(Ecosystem Modelling with EwE, PDF p.270)."""

from __future__ import annotations

from ecosim.core.workspace import WorkspaceRegistry
from ecosim.ingestion.model_origin import (
    ewe_header, has_recognised_input, identify_input, identify_output, is_timeseries_input,
)
from ecosim.ingestion.pipeline import validate_input_root

_SOFTWARE = '"<HEADER software/>"\nEwEVersion,"6.7.0.19431"\nDate,"8/16/2026 2:02:21 PM"\n'
_ECOPATH = '"<HEADER ecopath/>"\nModelName,FuMa\nModelSource,C:\\models\\FuMa.eweaccdb\n'
_ECOSIM = '"<HEADER ecosim/>"\nEcosimScenario,SSP1\nTimeSeries,TS\nStartYear,2004\n'
_ECOSPACE = '"<HEADER ecospace/>"\nEcospaceScenario,SSP1_space\nMapRows,3\nMapCols,4\n'
_END = '"<HEADER end/>"\n\n'


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_header_blocks_and_fields():
    blocks, fields = ewe_header(_SOFTWARE + _ECOPATH + _ECOSIM + _END + "Data,Catch\nyear\\group,1\n2004,0.1\n")
    assert blocks == ["software", "ecopath", "ecosim"]
    assert fields["ModelName"] == "FuMa" and fields["EcosimScenario"] == "SSP1"
    assert ewe_header("year,value\n2004,1\n") is None


def test_output_layers_from_the_deepest_header_block(tmp_path):
    run = tmp_path / "Sample_00001"
    _write(run / "basic_estimates.csv", _SOFTWARE + _ECOPATH + _END + "GroupNo,Group,B\n1,Seal,0.006\n")
    _write(run / "ecosim_SSP1" / "catch_annual.csv", _SOFTWARE + _ECOPATH + _ECOSIM + _END + "Data,Catch\n")
    _write(run / "SSP1" / "csv" / "EcospaceMapBiomass-Cod.csv",
           _SOFTWARE + _ECOPATH + _ECOSIM + _ECOSPACE + _END + "1,2\n")
    # RunInfo has a title line before its header (as EwE writes it).
    _write(run / "SSP1" / "asc" / "Ecospace RunInfo.txt",
           "EcoSpace .asc map output\n" + _SOFTWARE + _ECOPATH + _ECOSIM + _ECOSPACE + _END)
    _write(run / "SSP1" / "asc" / "EcospaceMapBiomass-Cod-00001.asc", "ncols 1\n")
    _write(run / "notes.csv", "a,b\n1,2\n")  # not an EwE file: ignored

    found = identify_output(tmp_path)
    assert found["ecopath"] == {
        "files": 1, "models": ["FuMa"],
        "groups": {"FuMa": {"1": "Seal"}}, "baseline_biomass": {"FuMa": {"1": 0.006}},
    }
    assert found["ecosim"] == {"files": 1, "models": ["FuMa"], "scenarios": ["SSP1"]}
    assert found["ecospace"] == {"files": 3, "maps": 1, "models": ["FuMa"], "scenarios": ["SSP1_space"]}
    assert found["not_checked"] == 0


def test_ecosim_only_output_has_no_other_layers(tmp_path):
    _write(tmp_path / "biomass_annual.csv", _SOFTWARE + _ECOPATH + _ECOSIM + _END + "Data,Biomass\n")
    found = identify_output(tmp_path)
    assert set(found) == {"ecosim", "not_checked", "version"}


_TIMESERIES = (
    "Title,Sealers,Seal B,Shrimp C\n"
    "Weight,0,1,1\n"
    "Pool code,1,2,7\n"
    "Type,3,0,6\n"
    "1970,1,1,0.3\n"
    "1971,1,1.05,\n"
)


def test_timeseries_input_is_recognised_by_its_labelled_rows():
    assert is_timeseries_input(_TIMESERIES)
    # Weight is optional (PM PDF p.270), "Pool code 2" may follow.
    assert is_timeseries_input("Title,A\nPool code,1\nPool code 2,2\nType,14\n2000,1\n")
    assert not is_timeseries_input("Title,A\nfoo,1\n")
    assert not is_timeseries_input("year,value\n2000,1\n")


def test_input_kinds(tmp_path):
    _write(tmp_path / "model" / "Anchovy Bay.ewemdb", "x")
    _write(tmp_path / "ts" / "fitting.csv", _TIMESERIES)
    _write(tmp_path / "maps" / "depth.asc", "ncols 1\n")
    _write(tmp_path / "maps" / "mpa.shp", "x")
    _write(tmp_path / "input" / "BAU" / "sst" / "trend_BAU.csv", "year,value\n")
    found = identify_input(tmp_path)
    assert found["ecopath_model"] == {"files": 1, "names": ["Anchovy Bay.ewemdb"]}
    assert found["ecosim_timeseries"] == {"files": 1, "series": 3}
    assert found["ecospace_maps"] == {"files": 1, "shapefiles": 1}
    assert found["driver_trends"] == {"files": 1}


def test_an_input_folder_with_only_the_model_file_can_be_added(tmp_path):
    _write(tmp_path / "FuMa.eweaccdb", "x")
    assert has_recognised_input(tmp_path)
    assert validate_input_root(tmp_path) == []
    empty = tmp_path / "empty"
    empty.mkdir()
    assert validate_input_root(empty)  # still refuses a folder with nothing recognisable


def test_models_survive_registry_round_trip(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("run", tmp_path, "output")
    assert registry.get(source.id).models is None
    registry.set_models(source.id, {"ecosim": {"files": 2}, "not_checked": 0})
    assert registry.get(source.id).models["ecosim"]["files"] == 2


_BASIC_ESTIMATES = "GroupNo,Group,B,PB\n1,\"Grey seal\",0.006,0.1\n2,JuvCod,0.34,1.06\n"


def test_ecopath_group_names_are_collected_per_model(tmp_path):
    for run in ("Sample_00001", "Sample_00002"):  # same model, same names in every run
        _write(tmp_path / run / "basic_estimates.csv", _SOFTWARE + _ECOPATH + _END + _BASIC_ESTIMATES)
    _write(tmp_path / "ecopath_stats.csv", _SOFTWARE + _ECOPATH + _END + "parameter,value\nTST,3807\n")
    ecopath = identify_output(tmp_path)["ecopath"]
    assert ecopath["groups"] == {"FuMa": {"1": "Grey seal", "2": "JuvCod"}}
    assert "group_conflicts" not in ecopath


def test_a_model_whose_files_disagree_on_a_name_gets_no_names(tmp_path):
    _write(tmp_path / "a" / "basic_estimates.csv", _SOFTWARE + _ECOPATH + _END + _BASIC_ESTIMATES)
    _write(tmp_path / "b" / "basic_estimates.csv",
           _SOFTWARE + _ECOPATH + _END + "GroupNo,Group,B\n1,\"Ringed seal\",0.1\n")
    ecopath = identify_output(tmp_path)["ecopath"]
    assert "FuMa" not in ecopath.get("groups", {})
    assert ecopath["group_conflicts"] == ["FuMa"]


def test_ecopath_baseline_biomass_is_collected_and_dropped_on_disagreement(tmp_path):
    _write(tmp_path / "run" / "basic_estimates.csv", _SOFTWARE + _ECOPATH + _END + _BASIC_ESTIMATES)
    ecopath = identify_output(tmp_path / "run")["ecopath"]
    assert ecopath["baseline_biomass"] == {"FuMa": {"1": 0.006, "2": 0.34}}
    # A Monte Carlo sample with B drawn anew: which run's baseline would apply? None.
    _write(tmp_path / "Sample_2" / "basic_estimates.csv",
           _SOFTWARE + _ECOPATH + _END + "GroupNo,Group,B,PB\n1,\"Grey seal\",0.009,0.1\n2,JuvCod,0.34,1.06\n")
    ecopath = identify_output(tmp_path)["ecopath"]
    assert "FuMa" not in ecopath.get("baseline_biomass", {})
    assert ecopath["baseline_conflicts"] == ["FuMa"]
    assert ecopath["groups"]["FuMa"]["1"] == "Grey seal"  # names still agree
