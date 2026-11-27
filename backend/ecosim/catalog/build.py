"""Build the DuckDB catalog from the Parquet store and exported dimension tables.

The catalog is the navigable index the UI browses *before* running analyses:
one row per (scenario, domain, variable, freq) dataset plus the dimension
tables (scenarios, models) and a ``timeseries`` view over the store.

``settings`` supplies the LIVE locations this reads/writes (``catalog_db``,
``dictionaries_dir``, ``spatial_dir``) -- as of 2026-08-28 these are expected
to already hold the *combined* dictionaries/raster_index.csv for whichever
source(s) are currently active (built by ``ingestion.activation``'s
``combine_and_rebuild``, which merges each active source's own per-source
cache -- see ``core/config.py``'s module docstring -- before calling this;
this function itself stays focused on DDL, not on knowing what "active"
means). ``timeseries_dirs`` is the separate list of per-source
``timeseries_dir``s the ``timeseries`` view unions over -- defaults to just
``[settings.timeseries_dir]`` (today's single-store behavior) for simple
callers/tests that don't need a multi-source union.
"""

from __future__ import annotations

from pathlib import Path

from ecosim.catalog.categories import CATEGORY_SQL
from ecosim.catalog.runs import RUN_KIND_SQL
from ecosim.core.config import Settings, get_settings
from ecosim.core.db import connect, parquet_scan


def build_catalog(settings: Settings | None = None, timeseries_dirs: list[Path] | None = None) -> None:
    settings = settings or get_settings()
    if timeseries_dirs is None:
        timeseries_dirs = [settings.timeseries_dir]
    dict_dir = settings.dictionaries_dir
    con = connect(settings)
    try:
        con.execute(f"CREATE OR REPLACE VIEW timeseries AS SELECT * FROM {parquet_scan(timeseries_dirs)}")

        # Aggregate per dataset first (CTE), then derive the Results-Extractor
        # category from the already-aggregated dimension counts in an outer
        # SELECT (keeps the classification rule a plain CASE, no nested aggregates).
        con.execute(
            """
            CREATE OR REPLACE TABLE catalog_datasets AS
            WITH agg AS (
                SELECT
                    scenario,
                    any_value(model)           AS model,
                    any_value(model_name)      AS model_name,
                    domain,
                    variable,
                    freq,
                    -- predation_<prey>/prey_<predator> files are one per species and
                    -- their Data label names it ("PredationMortality of Acartia sp.");
                    -- the variable spans all of them, so drop that suffix.
                    CASE WHEN variable IN ('predation', 'prey')
                         THEN regexp_replace(any_value(unit), ' of .*$', '')
                         ELSE any_value(unit) END AS label,
                    count(*)                   AS n_rows,
                    min(year)                  AS year_min,
                    max(year)                  AS year_max,
                    -- By number or, where the file names them instead (predation/
                    -- prey), by name -- counting numbers alone gave those 0 groups.
                    count(DISTINCT coalesce(CAST(group_id AS VARCHAR), lower(group_name)))     AS n_groups,
                    count(DISTINCT coalesce(CAST(fleet_id AS VARCHAR), lower(fleet_name)))     AS n_fleets,
                    count(DISTINCT coalesce(CAST(partner_id AS VARCHAR), lower(partner_name))) AS n_partners
                FROM timeseries
                GROUP BY scenario, domain, variable, freq
            )
            SELECT *, """ + CATEGORY_SQL + """ AS category
            FROM agg
            """
        )

        # Monte Carlo / Ecosampler runs per scenario (run_id is set only when a
        # scenario's files came from 2+ run folders), with their role: the
        # Ecosampler "Sample_baseline" (base parameters, UG p.50-51), the
        # perturbed "Sample_N", or a run outside the sample folders ("main").
        con.execute(
            """
            CREATE OR REPLACE TABLE catalog_runs AS
            SELECT scenario, run_id, """ + RUN_KIND_SQL + """ AS kind, count(*) AS n_rows
            FROM timeseries WHERE run_id IS NOT NULL
            GROUP BY scenario, run_id
            """
        )

        _load_dim(con, "dim_scenarios", dict_dir / "scenarios.csv")
        _load_dim(con, "dim_models", dict_dir / "models.csv")
        _load_dim(con, "catalog_rasters", settings.spatial_dir / "raster_index.csv")
    finally:
        con.close()


def _load_dim(con, table: str, csv_path) -> None:
    if csv_path.exists():
        con.execute(
            f"CREATE OR REPLACE TABLE {table} AS "
            f"SELECT * FROM read_csv_auto('{csv_path.as_posix()}', header => true)"
        )
    else:
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER)")
