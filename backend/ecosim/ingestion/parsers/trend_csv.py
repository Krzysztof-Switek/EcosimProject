"""Parser for input-driver trend CSVs (``trend_<scenario>.csv``).

These hold the spatial-mean of an environmental driver as an annual series, e.g.::

    "","mr.mean"
    "Obott_1998",260.0056...
    "Obott_1999",251.2123...

The row label embeds the year; the driver name comes from the containing folder.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from ecosim.core.schema import TIMESERIES_COLUMNS, slugify

_YEAR_RE = re.compile(r"(\d{4})")


def parse_trend_csv(path: Path, *, scenario: str, variable: str) -> pd.DataFrame:
    records: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header row ("", "mr.mean")
        for row in reader:
            if len(row) < 2 or not row[1].strip():
                continue
            match = _YEAR_RE.search(row[0])
            if not match:
                continue
            year = int(match.group(1))
            try:
                value = float(row[1])
            except ValueError:
                continue
            records.append({
                "date": f"{year}-01-01", "year": year, "month": 1, "value": value,
            })
    df = pd.DataFrame.from_records(records)
    df["scenario"] = scenario
    df["domain"] = "input"
    df["variable"] = slugify(variable)
    df["freq"] = "annual"
    df["unit"] = variable
    return df.reindex(columns=TIMESERIES_COLUMNS)
