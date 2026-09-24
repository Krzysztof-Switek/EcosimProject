"""DuckDB connection helpers for the catalog and ad-hoc Parquet queries."""

from __future__ import annotations

from pathlib import Path

import duckdb

from ecosim.core.config import Settings
from ecosim.core.schema import TIMESERIES_ARROW_SCHEMA

_ARROW_TO_DUCKDB = {"string": "VARCHAR", "int32": "INTEGER", "double": "DOUBLE"}


def connect(settings: Settings, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    settings.catalog_db.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(settings.catalog_db), read_only=read_only)


def timeseries_globs(timeseries_dirs: list[Path]) -> list[str]:
    """Forward-slash globs (DuckDB-friendly on Windows), one per per-source
    ``timeseries_dir`` that actually has at least one ``.parquet`` file --
    directories with none are dropped rather than included, since DuckDB's
    ``read_parquet`` errors on a glob with zero matches (a genuinely
    possible case now that each source's timeseries dir is independent, not
    always backstopped by *some* other domain's data the way the old single
    combined store was -- e.g. a spatial-only source has no CSV output at all)."""
    return [
        (d / "**" / "*.parquet").as_posix()
        for d in timeseries_dirs
        if d.exists() and any(d.rglob("*.parquet"))
    ]


def _empty_timeseries_view_sql() -> str:
    """Correctly-typed, zero-row fallback for when no active source has any
    timeseries data at all -- keeps ``catalog_datasets``/downstream queries
    working against the right schema instead of erroring on an empty
    ``read_parquet`` call."""
    cols = ", ".join(
        f"NULL::{_ARROW_TO_DUCKDB[field.type.__str__()]} AS {field.name}"
        for field in TIMESERIES_ARROW_SCHEMA
    )
    return f"(SELECT {cols} WHERE false)"


def parquet_scan(timeseries_dirs: list[Path]) -> str:
    """SQL snippet that reads the combined tidy store across every given
    per-source ``timeseries_dir``, with stable column names -- one row per
    active source's own cache slot (see ``config.source_cache_dir``), unioned
    by name so genuinely different scenario/variable shapes across sources
    still line up. Falls back to an empty, correctly-typed view rather than
    erroring when the list is empty or none of the dirs have any data."""
    globs = timeseries_globs(timeseries_dirs)
    if not globs:
        return _empty_timeseries_view_sql()
    glob_list_sql = "[" + ", ".join(f"'{g}'" for g in globs) + "]"
    return f"read_parquet({glob_list_sql}, union_by_name => true)"
