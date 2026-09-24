"""Tests for recognising (and cleanly skipping, not erroring on) CSV shapes
this pipeline doesn't turn into tidy rows -- added 2026-08-28 after a real
RU_SSP1 activation logged 3,765 "errors" that were actually two distinct,
harmless-to-skip shapes: Ecospace's own "export map as CSV" (a raw grid
dump, duplicate of the already-fully-indexed .asc raster of the same data)
and per-region age-structure breakdowns (a genuinely different, richer
shape -- Timestep x Region x age-cohort -- not yet representable in this
project's tidy schema, a real future feature, not a bug).

Both shapes share one clean structural signature, confirmed by reading the
real files directly: neither has a ``Data,<Label>`` marker row that every
real Ecosim tidy-CSV export has (the map-as-CSV shape uses ``Variable,``
instead; the age-structure shape has none at all, going straight from
``<HEADER end/>`` into its own data header row). Fully synthetic fixtures
below, built from the exact real headers/shapes -- no dependency on any real
dataset.
"""

from __future__ import annotations

import pytest

from ecosim.core.config import Settings
from ecosim.ingestion.parsers.ecosim_csv import UnsupportedCsvShape, parse_ecosim_csv
from ecosim.ingestion.pipeline import run_ingest

_HEADER_BLOCK = (
    '"<HEADER software/>"\n'
    'EwEVersion,"6.7.0.19431"\n'
    '"<HEADER ecopath/>"\n'
    'ModelName,"Test Model"\n'
    '"<HEADER ecosim/>"\n'
    "EcosimScenario,test_scenario\n"
    "StartYear,1998\n"
)

# Real shape, verbatim structure (RU_SSP1, 2026-08-28): Ecospace's own map-
# as-CSV export -- has an <HEADER ecospace/> block, then goes straight from
# <HEADER end/> into "Variable,<name>", never "Data,<label>".
_MAP_AS_CSV = (
    _HEADER_BLOCK
    + '"<HEADER ecospace/>"\n'
    + "EcospaceScenario,test_scenario\n"
    + "MapRows,2\nMapCols,2\n"
    + '"<HEADER end/>"\n'
    + "Variable,EcospaceMapBiomass\n"
    + 'Contaminant Concentrations,"Grey seal"\n'
    + "\n"
    + "Step,1\nYear,0.08\n"
    + "-9999,-9999\n-9999,-9999\n"
)

# Real shape, verbatim structure: region/age-structure breakdown -- goes
# straight from <HEADER end/> into "Max Age,<n>", never "Data,<label>".
_REGION_AGE_STRUCTURE = (
    _HEADER_BLOCK
    + '"<HEADER end/>"\n'
    + "Max Age,3\n"
    + "Timestep, Region,JuvCod_0,JuvCod_1\n"
    + "0,Ecosim Base Values,2.49,2.28\n"
    + "1,0,0.05,0.05\n"
)


def test_ecospace_map_as_csv_is_recognised_as_unsupported_not_an_error(tmp_path):
    path = tmp_path / "EcospaceMapBiomass-Grey seal.csv"
    path.write_text(_MAP_AS_CSV, encoding="utf-8")
    with pytest.raises(UnsupportedCsvShape):
        parse_ecosim_csv(path, scenario="test_scenario")


def test_region_age_structure_is_recognised_as_unsupported_not_an_error(tmp_path):
    path = tmp_path / "AgeStructure_Cod_Region_All_Number.csv"
    path.write_text(_REGION_AGE_STRUCTURE, encoding="utf-8")
    with pytest.raises(UnsupportedCsvShape):
        parse_ecosim_csv(path, scenario="test_scenario")


def test_run_ingest_counts_unsupported_shapes_separately_from_errors(tmp_path):
    # A folder with one REAL, parseable file alongside both unsupported
    # shapes -- proves run_ingest ingests the real one, and skips the other
    # two into `skipped_unsupported`, never into `errors`.
    ecosim_dir = tmp_path / "ecosim_test_scenario"
    ecosim_dir.mkdir()
    (ecosim_dir / "biomass_annual.csv").write_text(
        _HEADER_BLOCK + '"<HEADER end/>"\n\nData,Biomass\n\n'
        + "year\\group,1,2\n1998,0.01,0.02\n1999,0.011,0.021\n",
        encoding="utf-8",
    )
    (ecosim_dir / "EcospaceMapBiomass-Grey seal.csv").write_text(_MAP_AS_CSV, encoding="utf-8")
    (ecosim_dir / "AgeStructure_Cod_Region_All_Number.csv").write_text(_REGION_AGE_STRUCTURE, encoding="utf-8")

    settings = Settings(output_raw_dir=tmp_path, store_dir=tmp_path / "store")
    report = run_ingest(settings)

    assert report.files_read == 1  # only the real biomass_annual.csv
    assert report.skipped_unsupported == 2  # map-as-csv + age-structure
    assert report.errors == []  # neither counted as a real error
