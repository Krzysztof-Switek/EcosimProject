"""Parser for Ecospace's per-region age-structure tables
(``RegionAgeStructure/AgeStructure_<stanza>_Region_<region>_{Number,Weight}.csv``).

Multi-stanza groups are modelled by monthly cohorts -- Ecospace keeps "monthly
numbers-at-age and weight-at-age" (UG p.174), and Ecospace "summarizes the
output by region" (UG p.184). The manual doesn't describe these files; as EwE
6.7 writes them (RU_SSP1_Calib, 2026-10-30): the usual ``"<HEADER .../>"``
block (ecopath + ecosim + ecospace), ``Max Age,<months>``, then
``Timestep, Region, <stanza group>_<age in months>, ...`` (e.g. ``JuvCod_0`` ..
``JuvCod_35``, ``AdCod_3_36`` .. ``AdCod_3_176``); a first row ``0, Ecosim
Base Values`` (the initial state, not a time step -- not loaded), then one row
per written time step (1, 13, 25 ... -- each January) and region.

Rows become the variables ``age_structure_number`` / ``age_structure_weight``
(``_region_<n>`` added for a region other than 0 -- the files named
``Region_All``) with the
stanza group as ``group`` and the age as the partner -- ``partner_id`` the age
in months -- so a group's ages are picked like a predator's prey
(catalog/categories.py, box "age_structure"). One row per January is annual
data; other time steps make it monthly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ecosim.core.schema import TIMESERIES_COLUMNS, slugify
from ecosim.ingestion.parsers.ecosim_csv import (
    _DEFAULT_START_YEAR, UnsupportedCsvShape, _parse_header_block, _period, _read_rows,
)

_KIND = re.compile(r"_(Number|Weight)$", re.IGNORECASE)
_COHORT = re.compile(r"^(.+)_(\d+)$")
_LABELS = {"number": "Numbers at age", "weight": "Weight at age"}


def parse_age_structure_csv(
    path: Path,
    *,
    scenario: str,
    model: str | None = None,
    model_name: str | None = None,
    run_id: str | None = None,
) -> list[tuple[str, str, pd.DataFrame]]:
    """``[(variable, freq, tidy rows)]``; raises ``UnsupportedCsvShape`` when the
    file is not such a table."""
    kind = _KIND.search(path.stem)
    rows = _read_rows(path)
    headers, after = _parse_header_block(rows)
    body = [r for r in rows[after:] if any(c.strip() for c in r)]
    if kind is None or len(body) < 2 or body[0][0].strip() != "Max Age" or body[1][0].strip() != "Timestep":
        raise UnsupportedCsvShape(f"{path.name}: not an Ecospace region age-structure table")
    header = [c.strip() for c in body[1]]
    cohorts: list[tuple[int, str, int]] = []  # (column, stanza group, age in months)
    for i, col in enumerate(header[2:], start=2):
        m = _COHORT.match(col)
        if m:
            cohorts.append((i, m.group(1), int(m.group(2))))
    data = [r for r in body[2:] if r and r[0].strip().isdigit() and r[1].strip().lstrip("-").isdigit()]
    if not cohorts or not data:
        raise UnsupportedCsvShape(f"{path.name}: no age-structure rows")

    start_year = int(headers.get("StartYear", _DEFAULT_START_YEAR))
    if model_name is None:
        model_name = headers.get("ModelName")
    if model is None and model_name:
        model = slugify(model_name)
    width = len(header)
    table = pd.DataFrame([(r + [""] * width)[:width] for r in data], columns=range(width))
    steps = pd.to_numeric(table[0], errors="coerce").astype("int64")
    regions = table[1].str.strip()
    freq = "annual" if ((steps - 1) % 12 == 0).all() else "monthly"
    period = _period("monthly", steps, start_year)

    out: list[tuple[str, str, pd.DataFrame]] = []
    base = "age_structure_" + kind.group(1).lower()
    for region in sorted(regions.unique(), key=lambda r: int(r)):
        mask = (regions == region).values
        frames = []
        for col, group, age in cohorts:
            frames.append(period[mask].assign(
                value=pd.to_numeric(table.loc[mask, col], errors="coerce").values,
                group_name=group, partner_id=age, partner_name=f"{age} months",
            ))
        df = pd.concat(frames, ignore_index=True)
        df = df[df["value"].notna()]
        variable = base if region == "0" else f"{base}_region_{region}"
        df["model"] = model
        df["model_name"] = model_name
        df["scenario"] = scenario
        df["domain"] = "output"
        df["variable"] = variable
        df["freq"] = freq
        where = "all regions" if region == "0" else f"region {region}"
        df["unit"] = f"{_LABELS[kind.group(1).lower()]} ({where})"
        df["run_id"] = run_id
        out.append((variable, freq, df.reindex(columns=TIMESERIES_COLUMNS)))
    return out
