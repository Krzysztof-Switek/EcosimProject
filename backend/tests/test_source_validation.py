"""Tests for the cheap, synchronous, content-driven checks run at
source-registration time (``ingestion.pipeline.validate_output_root``/
``validate_input_root``) -- catching a genuinely empty/unrelated folder
instantly instead of only failing deep inside ingestion.

Deliberately test NO folder-name or nesting-depth assumptions (no "output/"
or "input/" subfolder requirement, no "ecosim_<scenario>/" requirement) --
redesigned 27.08 after two rounds of user-reported bugs: first, a real
Monte Carlo results folder organised differently than our one example was
wrongly rejected; then, pointing this at re-verified EwE manual sections
(User Guide p.50-51, p.79-81, p.265, p.275) confirmed EwE's own output
location has no fixed folder name at all, so *any* folder-name requirement
can only ever match how one example happened to be packaged. See this
module's own docstring and docs/data-contract.md's "Oczekiwany układ
katalogów źródłowych".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ecosim.ingestion.pipeline import validate_input_root, validate_output_root

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "DataEcosim"

pytestmark = pytest.mark.skipif(not RAW.exists(), reason="DataEcosim/ not present")


def test_validate_output_root_accepts_the_real_dataset():
    assert validate_output_root(RAW) == []


def test_validate_input_root_accepts_the_real_dataset():
    # The real DataEcosim/ root has both 'output' and 'input' as siblings,
    # so it's simultaneously a valid root for either kind.
    assert validate_input_root(RAW) == []


def test_validate_output_root_also_accepts_pointing_directly_at_output_subfolder():
    # No folder-name assumption any more -- there is no wrong "level" to
    # select, since discovery just recurses from wherever you point it and
    # matches on file content. This is the fix for the specific bug that
    # started this redesign (was previously rejected outright).
    assert validate_output_root(RAW / "output") == []


def test_validate_input_root_also_accepts_pointing_directly_at_input_subfolder():
    assert validate_input_root(RAW / "input") == []


def test_validate_output_root_accepts_real_data_in_an_arbitrary_folder_shape(tmp_path):
    # Regression test for the real bug (2026-08-27) that started this: a user
    # pointed this tile at genuine Monte Carlo output organised differently
    # than our one example dataset, and got rejected with an error citing a
    # file (Mapa_grupy_fleets.xlsx) EwE itself has never heard of and that
    # this project no longer has any code path to even look for (removed
    # 2026-08-28). Real, discoverable scenario data must be accepted
    # regardless of what folder it's organised under (no "output/" folder
    # here either -- straight in the root).
    ecosim_dir = tmp_path / "some_arbitrary_folder_name" / "nested_again"
    ecosim_dir.mkdir(parents=True)
    (ecosim_dir / "biomass_annual.csv").write_text(
        '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
        '"<HEADER ecosim/>"\nEcosimScenario,"test scenario"\nStartYear,1998\n'
        '"<HEADER end/>"\nData,Biomass\nyear\\group,1\n1998,10.5\n',
        encoding="utf-8",
    )
    assert validate_output_root(tmp_path) == []


def test_validate_output_root_flags_completely_empty_folder(tmp_path):
    empty = tmp_path / "not_a_model_export"
    empty.mkdir()
    problems = validate_output_root(empty)
    assert any("No EwE output was found" in p for p in problems)


def test_validate_output_root_flags_folder_with_only_unrelated_csvs(tmp_path):
    # A .csv exists, but it has no EcosimScenario header at all -- content,
    # not just file extension, is what's checked.
    root = tmp_path / "export_with_unrelated_csv"
    root.mkdir()
    (root / "not_ewe_data.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    problems = validate_output_root(root)
    assert any("No EwE output was found" in p for p in problems)


def test_validate_input_root_flags_completely_empty_folder(tmp_path):
    empty = tmp_path / "not_a_model_export"
    empty.mkdir()
    problems = validate_input_root(empty)
    assert any("No driver data was found" in p for p in problems)
