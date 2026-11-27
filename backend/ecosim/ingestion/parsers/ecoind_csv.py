"""Parser for the ECOIND plug-in's Ecosim indicator table (``biodiv_ind_Ecosim.csv``).

ECOIND "calculates a series of widely-used ecological indicators in a
standardized way, including biomass-based, catch-based, trophic-based,
size-based and species-based indicators", for Ecopath, Ecosim and Ecospace
(UG p.229-231, Table 3). The manual doesn't describe its files; the Ecosim one,
as written by EwE 6.7 (RU_SSP1_Calib, 2026-10-30), is the usual
``"<HEADER .../>"`` block (ecopath + ecosim) and then no ``Data,`` marker but a
table: ``Time`` -- the Ecosim monthly time step, 1..N -- and one column per
indicator (``"Total B"``, ``"Kempton's Q"``, ``"TL catch"``, ``MTI`` ...).

Each indicator becomes its own whole-ecosystem variable ``ecoind_<slug>`` (no
group or fleet -- the "Indicators" box), monthly as written, and annual as the
mean over each year's months -- the Results Extractor's "Yearly" ("the mean
over the year", UG p.131); EwE writes no annual table of its own.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ecosim.core.schema import TIMESERIES_COLUMNS, slugify
from ecosim.ingestion.parsers.ecosim_csv import (
    _DEFAULT_START_YEAR, UnsupportedCsvShape, _parse_header_block, _period, _read_rows,
)

ECOIND_PREFIX = "ecoind_"


def parse_ecoind_csv(
    path: Path,
    *,
    scenario: str,
    model: str | None = None,
    model_name: str | None = None,
    run_id: str | None = None,
) -> list[tuple[str, str, pd.DataFrame]]:
    """``[(variable, freq, tidy rows)]``, monthly and annual per indicator.
    Raises ``UnsupportedCsvShape`` when the file is not such a table."""
    rows = _read_rows(path)
    headers, after = _parse_header_block(rows)
    hdr_idx = next((i for i in range(after, len(rows)) if any(c.strip() for c in rows[i])), None)
    if hdr_idx is None or rows[hdr_idx][0].strip() != "Time" or "EcosimScenario" not in headers:
        raise UnsupportedCsvShape(f"{path.name}: not an ECOIND Ecosim indicator table")
    names = [c.strip() for c in rows[hdr_idx][1:]]
    width = 1 + len(names)
    data = [(r + [""] * width)[:width] for r in rows[hdr_idx + 1:] if r and r[0].strip()]
    table = pd.DataFrame(data, columns=["Time", *names]).apply(pd.to_numeric, errors="coerce")
    table = table[table["Time"].notna()]
    start_year = int(headers.get("StartYear", _DEFAULT_START_YEAR))
    period = _period("monthly", table["Time"], start_year)
    if model_name is None:
        model_name = headers.get("ModelName")
    if model is None and model_name:
        model = slugify(model_name)

    out: list[tuple[str, str, pd.DataFrame]] = []
    for name in names:
        if not name:
            continue
        monthly = period.assign(value=table[name].values)
        monthly = monthly[monthly["value"].notna()]
        if monthly.empty:
            continue
        annual = monthly.groupby("year", as_index=False)["value"].mean()
        annual = annual.assign(month=1, date=annual["year"].astype(str).str.zfill(4) + "-01-01")
        variable = ECOIND_PREFIX + slugify(name)
        for freq, df in (("monthly", monthly), ("annual", annual)):
            df = df.copy()
            df["model"] = model
            df["model_name"] = model_name
            df["scenario"] = scenario
            df["domain"] = "output"
            df["variable"] = variable
            df["freq"] = freq
            # The catalog shows a variable's unit column as its label.
            df["unit"] = f"{name} (ECOIND{', yearly mean' if freq == 'annual' else ''})"
            df["run_id"] = run_id
            out.append((variable, freq, df.reindex(columns=TIMESERIES_COLUMNS)))
    return out
