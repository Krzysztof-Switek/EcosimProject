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
    "model",          # Ecopath model id (slug of ModelName); null for input drivers
    "model_name",     # authoritative Ecopath ModelName label; null for input drivers
    "scenario",       # canonical scenario id (slug of EcosimScenario), e.g. "baltic_ecosim"
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
        ("model", pa.string()),
        ("model_name", pa.string()),
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


# One row per known raster. Building this index only touches filenames + one
# RunInfo header per scenario folder (grid geometry is constant per model, not
# per file) -- no per-file I/O, no rasterio. The actual Cloud-Optimized GeoTIFF
# is materialized lazily (see ingestion.spatial_pipeline.materialize_raster) on
# first request and cached at ``path``; until then only ``source_path`` (the
# raw .asc) exists. A materialized COG carries its own georeferencing, so
# geo metadata (bounds/cellsize/crs) is read from the file when needed rather
# than duplicated here. ``group_*``/``fleet_*`` are the same entity dimension
# as the tidy schema (mutually exclusive here: a raster has at most one).
RASTER_INDEX_COLUMNS: list[str] = [
    "id",             # stable slug: scenario|domain|variable|entity_slug|year
    "model",          # Ecopath model id; null for input drivers
    "model_name",
    "scenario",       # canonical scenario id, matches the timeseries store
    "domain",         # "output" | "input"
    "variable",       # biomass, catch, discards, effort, habitat_capacity, or driver slug
    "group_id",
    "group_name",
    "fleet_id",
    "fleet_name",
    "year",
    "path",           # target COG path, relative to the spatial store root (data/spatial/)
    "source_path",    # absolute raw .asc path -- needed to materialize on demand
    "source_crs_wkt",  # CoordinateSystemWKT from this scenario's Ecospace RunInfo.txt, if any --
                        # checked against our hardcoded WGS84 assumption at materialize time
                        # (see asc_grid.write_cog); null for input drivers, which have no RunInfo.txt
]


def slugify(text: str) -> str:
    """Lower-case, ascii-friendly slug used for scenario/variable identifiers."""
    text = text.strip().lower()
    text = re.sub(r"[^\w]+", "_", text)
    return text.strip("_")
