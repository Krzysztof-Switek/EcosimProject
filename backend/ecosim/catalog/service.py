"""Read-only query layer over the DuckDB catalog and Parquet store.

Used by the API. Every call opens a short-lived read-only connection so the
ingestion pipeline can rewrite the store without locking out readers.
"""

from __future__ import annotations

from contextlib import contextmanager

from ecosim.core.config import Settings, get_settings
from ecosim.core.db import connect


@contextmanager
def _ro(settings: Settings):
    con = connect(settings, read_only=True)
    try:
        yield con
    finally:
        con.close()


def _rows(con, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def list_scenarios(settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    with _ro(settings) as con:
        return _rows(
            con,
            """
            SELECT cd.scenario,
                   any_value(s.label)   AS label,
                   any_value(cd.domain) AS domain,
                   count(*)             AS n_datasets,
                   min(cd.year_min)     AS year_min,
                   max(cd.year_max)     AS year_max
            FROM catalog_datasets cd
            LEFT JOIN dim_scenarios s ON cd.scenario = s.id
            GROUP BY cd.scenario
            ORDER BY cd.scenario
            """,
        )


def list_datasets(settings: Settings | None = None, *, scenario: str | None = None) -> list[dict]:
    settings = settings or get_settings()
    where, params = ("WHERE scenario = ?", [scenario]) if scenario else ("", [])
    with _ro(settings) as con:
        return _rows(
            con,
            f"SELECT * FROM catalog_datasets {where} "
            "ORDER BY scenario, domain, variable, freq",
            params,
        )


def get_scenario_tree(settings: Settings | None = None) -> list[dict]:
    """Nested navigation tree: scenario -> domain -> [variables]."""
    settings = settings or get_settings()
    datasets = list_datasets(settings)
    tree: dict[str, dict] = {}
    for ds in datasets:
        scn = tree.setdefault(ds["scenario"], {"scenario": ds["scenario"], "domains": {}})
        dom = scn["domains"].setdefault(ds["domain"], {"domain": ds["domain"], "variables": []})
        dom["variables"].append({
            "variable": ds["variable"], "freq": ds["freq"], "label": ds["label"],
            "category": ds.get("category"),
            "year_min": ds["year_min"], "year_max": ds["year_max"],
            "n_groups": ds["n_groups"], "n_fleets": ds["n_fleets"], "n_partners": ds["n_partners"],
        })
    return [
        {"scenario": s["scenario"], "domains": list(s["domains"].values())}
        for s in tree.values()
    ]


def list_groups(settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    with _ro(settings) as con:
        return _rows(con, "SELECT * FROM dim_groups ORDER BY id")


def list_fleets(settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    with _ro(settings) as con:
        return _rows(con, "SELECT * FROM dim_fleets ORDER BY id")


def query_timeseries(
    settings: Settings | None = None,
    *,
    scenario: list[str] | None = None,
    variable: str,
    freq: str = "annual",
    group: list[str] | None = None,
    fleet: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict]:
    """Return tidy rows for charting. ``group``/``fleet`` match names case-insensitively."""
    settings = settings or get_settings()
    clauses = ["variable = ?", "freq = ?"]
    params: list = [variable, freq]
    if scenario:
        clauses.append(f"scenario IN ({_placeholders(scenario)})")
        params += scenario
    if group:
        clauses.append(f"lower(group_name) IN ({_placeholders(group)})")
        params += [g.lower() for g in group]
    if fleet:
        clauses.append(f"lower(fleet_name) IN ({_placeholders(fleet)})")
        params += [f.lower() for f in fleet]
    if year_from is not None:
        clauses.append("year >= ?")
        params.append(year_from)
    if year_to is not None:
        clauses.append("year <= ?")
        params.append(year_to)
    sql = (
        "SELECT scenario, variable, freq, date, year, month, "
        "group_id, group_name, fleet_id, fleet_name, partner_id, partner_name, value "
        "FROM timeseries WHERE " + " AND ".join(clauses) +
        " ORDER BY scenario, group_name, fleet_name, partner_name, year, month"
    )
    with _ro(settings) as con:
        return _rows(con, sql, params)


def _placeholders(values: list) -> str:
    return ", ".join("?" for _ in values)
