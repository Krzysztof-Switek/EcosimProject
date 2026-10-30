"""Read-only query layer over the DuckDB catalog and Parquet store.

Used by the API. Every call opens a short-lived read-only connection so the
ingestion pipeline can rewrite the store without locking out readers.
"""

from __future__ import annotations

from contextlib import contextmanager

from ecosim.core.config import Settings, get_settings
from ecosim.core.db import connect
from ecosim.core.workspace import get_workspace_registry


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


def _ecopath_per_model(key: str, conflicts_key: str) -> dict[str, dict[int, object]]:
    """``{Ecopath model name: {group number: value}}`` merged from every
    registered output source's Ecopath results (``basic_estimates.csv``,
    collected by ingestion.model_origin when a source is identified) -- so an
    Ecosim run whose own folder has no Ecopath output gets it from any source
    holding the same model's. A model whose sources disagree gets nothing."""
    merged: dict[str, dict[int, object]] = {}
    conflicts: set[str] = set()
    for source in get_workspace_registry().list_sources("output"):
        ecopath = (source.models or {}).get("ecopath") or {}
        conflicts.update(ecopath.get(conflicts_key, []))
        for model, values in (ecopath.get(key) or {}).items():
            known = merged.setdefault(model, {})
            for gid, value in values.items():
                if known.get(int(gid), value) != value:
                    conflicts.add(model)
                known[int(gid)] = value
    return {m: v for m, v in merged.items() if m not in conflicts}


def ecopath_group_names() -> dict[str, dict[int, str]]:
    """Group names per Ecopath model (see ``_ecopath_per_model``)."""
    return _ecopath_per_model("groups", "group_conflicts")  # type: ignore[return-value]


def ecopath_baseline_biomass() -> dict[str, dict[int, float]]:
    """Ecopath biomass B per group per model -- the baseline Ecosim starts
    from (see ``_ecopath_per_model``)."""
    return _ecopath_per_model("baseline_biomass", "baseline_conflicts")  # type: ignore[return-value]


# Ecosim variables measured in the same units as Ecopath's B (t/km^2) -- the
# only ones an Ecopath baseline applies to.
_BASELINE_VARIABLES = {"biomass"}


def _annotate_from_ecopath(rows: list[dict]) -> list[dict]:
    """Name the groups EwE wrote only as numbers, and give biomass rows their
    group's Ecopath ``baseline`` (None where unknown)."""
    if not rows:
        return rows
    names = ecopath_group_names() if any(r.get("group_name") is None for r in rows) else {}
    baseline = ecopath_baseline_biomass() if rows[0].get("variable") in _BASELINE_VARIABLES else {}
    for r in rows:
        gid = r.get("group_id")
        model = r.get("model_name")
        if r.get("group_name") is None and gid is not None:
            r["group_name"] = names.get(model, {}).get(int(gid))
        r["baseline"] = baseline.get(model, {}).get(int(gid)) if gid is not None else None
    return rows


def list_scenarios(settings: Settings | None = None) -> list[dict]:
    settings = settings or get_settings()
    with _ro(settings) as con:
        return _rows(
            con,
            """
            SELECT cd.scenario,
                   any_value(s.label)      AS label,
                   any_value(cd.domain)    AS domain,
                   any_value(cd.model)     AS model,
                   any_value(cd.model_name) AS model_name,
                   count(*)                AS n_datasets,
                   min(cd.year_min)        AS year_min,
                   max(cd.year_max)        AS year_max
            FROM catalog_datasets cd
            LEFT JOIN dim_scenarios s ON cd.scenario = s.id
            GROUP BY cd.scenario
            ORDER BY cd.scenario
            """,
        )


def list_models(settings: Settings | None = None) -> list[dict]:
    """Ecopath models (output only) with the Ecosim scenarios that belong to each.

    This is the top of the navigation hierarchy: step 1 picks models, step 2
    picks scenarios from within those models. Input drivers have no model and
    are excluded here.
    """
    settings = settings or get_settings()
    with _ro(settings) as con:
        rows = _rows(
            con,
            """
            SELECT cd.model,
                   any_value(cd.model_name) AS model_name,
                   cd.scenario,
                   any_value(s.label)       AS scenario_label,
                   min(cd.year_min)         AS year_min,
                   max(cd.year_max)         AS year_max,
                   count(*)                 AS n_datasets
            FROM catalog_datasets cd
            LEFT JOIN dim_scenarios s ON cd.scenario = s.id
            WHERE cd.domain = 'output' AND cd.model IS NOT NULL
            GROUP BY cd.model, cd.scenario
            ORDER BY cd.model, cd.scenario
            """,
        )
    models: dict[str, dict] = {}
    for r in rows:
        m = models.setdefault(r["model"], {
            "model": r["model"], "model_name": r["model_name"],
            "scenarios": [], "year_min": r["year_min"], "year_max": r["year_max"],
            "n_datasets": 0,
        })
        m["scenarios"].append({"scenario": r["scenario"], "label": r["scenario_label"] or r["scenario"]})
        m["year_min"] = min(m["year_min"], r["year_min"])
        m["year_max"] = max(m["year_max"], r["year_max"])
        m["n_datasets"] += r["n_datasets"]
    return list(models.values())


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
    """Nested navigation tree: (model, scenario) -> domain -> [variables].

    Each scenario node carries its parent Ecopath ``model``/``model_name`` (null
    for input drivers) so the UI can group scenarios by model and know, per
    variable, which (model, scenario) series are available.
    """
    settings = settings or get_settings()
    datasets = list_datasets(settings)
    tree: dict[str, dict] = {}
    for ds in datasets:
        scn = tree.setdefault(ds["scenario"], {
            "scenario": ds["scenario"],
            "model": ds.get("model"),
            "model_name": ds.get("model_name"),
            "domains": {},
        })
        dom = scn["domains"].setdefault(ds["domain"], {"domain": ds["domain"], "variables": []})
        dom["variables"].append({
            "variable": ds["variable"], "freq": ds["freq"], "label": ds["label"],
            "category": ds.get("category"),
            "year_min": ds["year_min"], "year_max": ds["year_max"],
            "n_groups": ds["n_groups"], "n_fleets": ds["n_fleets"], "n_partners": ds["n_partners"],
        })
    return [
        {
            "scenario": s["scenario"], "model": s["model"], "model_name": s["model_name"],
            "domains": list(s["domains"].values()),
        }
        for s in tree.values()
    ]


def query_timeseries(
    settings: Settings | None = None,
    *,
    model: list[str] | None = None,
    scenario: list[str] | None = None,
    variable: str,
    freq: str = "annual",
    group: list[str] | None = None,
    group_id: list[int] | None = None,
    fleet: list[str] | None = None,
    fleet_id: list[int] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
) -> list[dict]:
    """Return tidy rows for charting. ``group``/``fleet`` match names case-insensitively;
    ``group_id``/``fleet_id`` match EwE's own numbers -- the usual way to pick them, since
    most EwE outputs (e.g. ``catch_annual.csv``, ``year\\group,1,2,...``) carry only the
    number and no name (see ``list_dimension``).

    Range filtering: ``year_from``/``year_to`` bound by calendar year; for monthly
    data ``month_from``/``month_to`` additionally bound by month-of-year (1–12),
    so a seasonal subset (e.g. June–August across all years) can be selected.
    """
    settings = settings or get_settings()
    clauses = ["variable = ?", "freq = ?"]
    params: list = [variable, freq]
    if model:
        clauses.append(f"model IN ({_placeholders(model)})")
        params += model
    if scenario:
        clauses.append(f"scenario IN ({_placeholders(scenario)})")
        params += scenario
    if group:
        clauses.append(f"lower(group_name) IN ({_placeholders(group)})")
        params += [g.lower() for g in group]
    if group_id:
        clauses.append(f"group_id IN ({_placeholders(group_id)})")
        params += group_id
    if fleet:
        clauses.append(f"lower(fleet_name) IN ({_placeholders(fleet)})")
        params += [f.lower() for f in fleet]
    if fleet_id:
        clauses.append(f"fleet_id IN ({_placeholders(fleet_id)})")
        params += fleet_id
    if year_from is not None:
        clauses.append("year >= ?")
        params.append(year_from)
    if year_to is not None:
        clauses.append("year <= ?")
        params.append(year_to)
    if month_from is not None:
        clauses.append("month >= ?")
        params.append(month_from)
    if month_to is not None:
        clauses.append("month <= ?")
        params.append(month_to)
    sql = (
        "SELECT model, model_name, scenario, variable, freq, date, year, month, "
        "group_id, group_name, fleet_id, fleet_name, partner_id, partner_name, value "
        "FROM timeseries WHERE " + " AND ".join(clauses) +
        " ORDER BY model, scenario, group_id, group_name, fleet_id, fleet_name, partner_name, year, month"
    )
    with _ro(settings) as con:
        return _annotate_from_ecopath(_rows(con, sql, params))


# Dimensions list_dimension can enumerate -> their (id, name) columns. A fixed map,
# so nothing caller-supplied is ever interpolated into SQL.
_DIMENSION_COLUMNS = {"group": ("group_id", "group_name"), "fleet": ("fleet_id", "fleet_name")}


def list_dimension(
    settings: Settings | None = None,
    *,
    dimension: str,
    variable: list[str],
    freq: str = "annual",
    scenario: list[str] | None = None,
) -> list[dict]:
    """Functional groups or fleets (``dimension``) present in the data of ``variable``
    (one or more) for the given scenarios -- the options for picking them. One row
    per EwE number (``id``) with the variables it occurs in, and its ``name`` only
    where EwE wrote one into the file itself (no id->name dictionary exists; EwE
    numbers groups and fleets per model, in the order the modeller entered them --
    docs/ewe-data-formats.md, section 5). A group with no name in the file gets
    the one from its model's Ecopath output, if known (``ecopath_group_names``);
    if the selected scenarios mix models that name a number differently, the
    names are joined with " / "."""
    id_col, name_col = _DIMENSION_COLUMNS[dimension]
    settings = settings or get_settings()
    clauses = [f"variable IN ({_placeholders(variable)})", "freq = ?", f"{id_col} IS NOT NULL"]
    params: list = [*variable, freq]
    if scenario:
        clauses.append(f"scenario IN ({_placeholders(scenario)})")
        params += scenario
    sql = (
        f"SELECT {id_col} AS id, any_value({name_col}) AS name, "
        "list(DISTINCT variable ORDER BY variable) AS variables, "
        "list(DISTINCT model_name) AS model_names "
        "FROM timeseries WHERE " + " AND ".join(clauses) +
        f" GROUP BY {id_col} ORDER BY {id_col}"
    )
    with _ro(settings) as con:
        rows = _rows(con, sql, params)
    lookup = ecopath_group_names() if dimension == "group" and any(r["name"] is None for r in rows) else {}
    for r in rows:
        models = r.pop("model_names") or []
        if r["name"] is None and lookup:
            found = sorted({lookup[m][r["id"]] for m in models if m in lookup and r["id"] in lookup[m]})
            r["name"] = " / ".join(found) or None
    return rows


def list_raster_layers(settings: Settings | None = None) -> list[dict]:
    """Spatial layers available per (model, scenario): one row per variable.

    Mirrors :func:`get_scenario_tree` but for the raster store — the index the
    UI browses before picking a year to render. Groups/fleets are counted by
    id *or* name: map rasters carry only the name (it's in the ``.asc``
    filename, e.g. ``EcospaceMapBiomass-Acartia sp.-00001.asc``) and no id,
    so counting ids alone reported 0 groups and the map's group step vanished.
    """
    settings = settings or get_settings()
    with _ro(settings) as con:
        return _rows(
            con,
            """
            SELECT scenario, any_value(model) AS model, any_value(model_name) AS model_name,
                   domain, variable,
                   count(DISTINCT coalesce(CAST(group_id AS VARCHAR), group_name)) AS n_groups,
                   count(DISTINCT coalesce(CAST(fleet_id AS VARCHAR), fleet_name)) AS n_fleets,
                   min(year) AS year_min, max(year) AS year_max, count(*) AS n_rasters
            FROM catalog_rasters
            GROUP BY scenario, domain, variable
            ORDER BY scenario, domain, variable
            """,
        )


def list_rasters(
    settings: Settings | None = None,
    *,
    scenario: str,
    variable: str,
    group: str | None = None,
    fleet: str | None = None,
    year: int | None = None,
) -> list[dict]:
    """Raster index rows for one (scenario, variable), optionally narrowed further."""
    settings = settings or get_settings()
    clauses = ["scenario = ?", "variable = ?"]
    params: list = [scenario, variable]
    if group:
        clauses.append("lower(group_name) = ?")
        params.append(group.lower())
    if fleet:
        clauses.append("lower(fleet_name) = ?")
        params.append(fleet.lower())
    if year is not None:
        clauses.append("year = ?")
        params.append(year)
    with _ro(settings) as con:
        return _rows(
            con,
            "SELECT * FROM catalog_rasters WHERE " + " AND ".join(clauses) + " ORDER BY year",
            params,
        )


def get_raster(raster_id: str, settings: Settings | None = None) -> dict | None:
    settings = settings or get_settings()
    with _ro(settings) as con:
        rows = _rows(con, "SELECT * FROM catalog_rasters WHERE id = ?", [raster_id])
    return rows[0] if rows else None


def _placeholders(values: list) -> str:
    return ", ".join("?" for _ in values)
