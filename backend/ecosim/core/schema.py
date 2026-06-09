"""Canonical tidy schema for Ecosim time series.

Every raw CSV shape (wide-by-id, wide-by-name, long fleet-group, single series)
is normalised into rows with these columns. ``group_*``, ``fleet_*`` and
``partner_*`` are nullable and only populated for the dimensions a variable has.
"""

from __future__ import annotations

import re

import pyarrow as pa

# Ordered list of canonical columns for the tidy time-series table.
TIMESERIES_COLUMNS: list[str] = [
    "scenario",       # canonical scenario id, e.g. "baseline_cumulative"
    "domain",         # "output" | "input"
    "variable",       # canonical slug, e.g. "biomass", "catch_fleet_group", "predation"
    "freq",           # "annual" | "monthly"
    "date",           # ISO date (first day of the period)
    "year",           # int
    "month",          # int (1 for annual)
    "group_id",       # nullable int (functional group)
    "group_name",     # nullable str
    "fleet_id",       # nullable int
    "fleet_name",     # nullable str
    "partner_id",     # nullable int (interacting group, e.g. predator in predation)
    "partner_name",   # nullable str
    "value",          # float
    "unit",           # nullable str
]

# Arrow schema used when writing Parquet so column types stay stable even when
# a particular slice has all-null dimension columns.
TIMESERIES_ARROW_SCHEMA = pa.schema(
    [
        ("scenario", pa.string()),
        ("domain", pa.string()),
        ("variable", pa.string()),
        ("freq", pa.string()),
        ("date", pa.string()),
        ("year", pa.int32()),
        ("month", pa.int32()),
        ("group_id", pa.int32()),
        ("group_name", pa.string()),
        ("fleet_id", pa.int32()),
        ("fleet_name", pa.string()),
        ("partner_id", pa.int32()),
        ("partner_name", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
    ]
)


def slugify(text: str) -> str:
    """Lower-case, ascii-friendly slug used for scenario/variable identifiers."""
    text = text.strip().lower()
    text = re.sub(r"[^\w]+", "_", text)
    return text.strip("_")
