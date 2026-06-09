"""DuckDB connection helpers for the catalog and ad-hoc Parquet queries."""

from __future__ import annotations

from pathlib import Path

import duckdb

from ecosim.core.config import Settings


def connect(settings: Settings, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    settings.catalog_db.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(settings.catalog_db), read_only=read_only)


def timeseries_glob(settings: Settings) -> str:
    """Forward-slash glob over every Parquet slice (DuckDB-friendly on Windows)."""
    return (settings.timeseries_dir / "**" / "*.parquet").as_posix()


def parquet_scan(settings: Settings) -> str:
    """SQL snippet that reads the whole tidy store with stable column names."""
    return f"read_parquet('{timeseries_glob(settings)}', union_by_name => true)"
