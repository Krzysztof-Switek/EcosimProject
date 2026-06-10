"""Build the DuckDB catalog from the Parquet store and exported dictionaries.

The catalog is the navigable index the UI browses *before* running analyses:
one row per (scenario, domain, variable, freq) dataset plus the dimension
tables (groups, fleets, scenarios) and a ``timeseries`` view over the store.
"""

from __future__ import annotations

from ecosim.catalog.categories import CATEGORY_SQL
from ecosim.core.config import Settings, get_settings
from ecosim.core.db import connect, parquet_scan


def build_catalog(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    dict_dir = settings.dictionaries_dir
    con = connect(settings)
    try:
        con.execute(f"CREATE OR REPLACE VIEW timeseries AS SELECT * FROM {parquet_scan(settings)}")

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
                    any_value(unit)            AS label,
                    count(*)                   AS n_rows,
                    min(year)                  AS year_min,
                    max(year)                  AS year_max,
                    count(DISTINCT group_id)   AS n_groups,
                    count(DISTINCT fleet_id)   AS n_fleets,
                    count(DISTINCT partner_id) AS n_partners
                FROM timeseries
                GROUP BY scenario, domain, variable, freq
            )
            SELECT *, """ + CATEGORY_SQL + """ AS category
            FROM agg
            """
        )

        _load_dim(con, "dim_groups", dict_dir / "groups.csv")
        _load_dim(con, "dim_fleets", dict_dir / "fleets.csv")
        _load_dim(con, "dim_scenarios", dict_dir / "scenarios.csv")
        _load_dim(con, "dim_models", dict_dir / "models.csv")
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
