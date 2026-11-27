"""Read-only query layer over the DuckDB catalog and Parquet store.

Used by the API. Every call opens a short-lived read-only connection so the
ingestion pipeline can rewrite the store without locking out readers.
"""

from __future__ import annotations

from contextlib import contextmanager

from ecosim.catalog.categories import CATEGORY_DIMS
from ecosim.catalog.runs import RUN_KIND_SQL, run_label
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


def _ecopath_numbers(names: dict[str, dict[int, str]]) -> dict[str, dict[str, int]]:
    """``{model: {lower-cased group name: group number}}`` -- the inverse of
    ``ecopath_group_names`` for files that name groups instead of numbering them."""
    return {m: {n.lower(): gid for gid, n in groups.items()} for m, groups in names.items()}


def _resolve_group(model: str | None, gid, name, names, numbers) -> tuple[int | None, str | None]:
    """A functional group's (number, name), each completed from the model's
    Ecopath output where the file had only the other: most EwE outputs carry
    only numbers, predation/prey files only names (lower-cased in their file
    names, so the Ecopath spelling is preferred)."""
    if gid is not None:
        return int(gid), name if name is not None else names.get(model, {}).get(int(gid))
    if name is not None:
        found = numbers.get(model, {}).get(name.lower())
        if found is not None:
            return found, names[model][found]
    return None, name


def _annotate_from_ecopath(rows: list[dict]) -> list[dict]:
    """Complete group (and predator/prey partner) numbers and names from the
    model's Ecopath output, and give biomass rows their group's Ecopath
    ``baseline`` (None where unknown)."""
    if not rows:
        return rows
    incomplete = any(
        (r.get(f"{d}_id") is None) != (r.get(f"{d}_name") is None)
        for r in rows for d in ("group", "partner")
    )
    names = ecopath_group_names() if incomplete else {}
    numbers = _ecopath_numbers(names)
    baseline = ecopath_baseline_biomass() if rows[0].get("variable") in _BASELINE_VARIABLES else {}
    for r in rows:
        model = r.get("model_name")
        for d in ("group", "partner"):
            r[f"{d}_id"], r[f"{d}_name"] = _resolve_group(
                model, r.get(f"{d}_id"), r.get(f"{d}_name"), names, numbers,
            )
        gid = r["group_id"]
        r["baseline"] = baseline.get(model, {}).get(gid) if gid is not None else None
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
    picks: list[list[str]] | None = None,
    run: str | None = None,
) -> list[dict]:
    """Return tidy rows for charting. ``group``/``fleet`` match names case-insensitively;
    ``group_id``/``fleet_id`` match EwE's own numbers -- most EwE outputs (e.g.
    ``catch_annual.csv``, ``year\\group,1,2,...``) carry only the number and no name.

    ``picks`` is the selection made in the variable's Results-Extractor box (see
    ``list_selection_options``): ``[parent]`` or ``[parent, partner]`` entity keys.
    Ignored for a variable whose box has no selection window; an empty list
    selects nothing.

    Range filtering: ``year_from``/``year_to`` bound by calendar year; for monthly
    data ``month_from``/``month_to`` additionally bound by month-of-year (1–12),
    so a seasonal subset (e.g. June–August across all years) can be selected.

    Monte Carlo scenarios (several runs, see catalog/runs.py): ``run`` returns that
    one run's rows; without it, one row per point summarising the runs --
    ``value`` from the Ecosampler baseline run (else the run outside the sample
    folders, else the median), ``p05``/``p95`` the 5th/95th percentile over the
    samples and ``n_samples`` how many there were. Ordinary rows get no such keys.
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
    if run is not None:
        clauses.append("run_id = ?")
        params.append(run)
    with _ro(settings) as con:
        if picks is not None:
            dims = CATEGORY_DIMS.get(variable_category(con, variable))
            if dims is not None:
                clause, keys = _picks_clause(dims, picks)
                clauses.append(clause)
                params += keys
        where = " AND ".join(clauses)
        order = " ORDER BY model, scenario, group_id, group_name, fleet_id, fleet_name, partner_id, partner_name, year, month"
        if run is None and _has_runs(con, scenario):
            sql = (
                f"SELECT {_POINT_COLUMNS}, "
                "coalesce(any_value(value) FILTER (WHERE kind = 'baseline'), "
                "any_value(value) FILTER (WHERE kind IN ('single', 'main')), median(value)) AS value, "
                "quantile_cont(value, 0.05) FILTER (WHERE kind = 'sample') AS p05, "
                "quantile_cont(value, 0.95) FILTER (WHERE kind = 'sample') AS p95, "
                "count(*) FILTER (WHERE kind = 'sample') AS n_samples "
                f"FROM (SELECT *, {RUN_KIND_SQL} AS kind FROM timeseries WHERE {where}) "
                f"GROUP BY {_POINT_COLUMNS}" + order
            )
        else:
            sql = f"SELECT {_POINT_COLUMNS}, value FROM timeseries WHERE {where}" + order
        return _annotate_from_ecopath(_rows(con, sql, params))


_POINT_COLUMNS = (
    "model, model_name, scenario, variable, freq, date, year, month, "
    "group_id, group_name, fleet_id, fleet_name, partner_id, partner_name"
)


def _has_runs(con, scenario: list[str] | None) -> bool:
    """Whether these scenarios (all, if None) hold Monte Carlo runs."""
    sql = "SELECT 1 FROM catalog_runs" + (f" WHERE scenario IN ({_placeholders(scenario)})" if scenario else "")
    try:
        return bool(con.execute(sql + " LIMIT 1", scenario or []).fetchall())
    except Exception:  # noqa: BLE001 -- a catalog built before catalog_runs existed
        return False


def list_runs(settings: Settings | None = None, *, scenario: list[str] | None = None) -> list[dict]:
    """The Monte Carlo runs of these scenarios: ``{scenario, run_id, kind, label}``,
    baseline first, then the main run, then the samples in order."""
    settings = settings or get_settings()
    sql = "SELECT scenario, run_id, kind FROM catalog_runs"
    if scenario:
        sql += f" WHERE scenario IN ({_placeholders(scenario)})"
    with _ro(settings) as con:
        try:
            rows = _rows(con, sql, scenario or [])
        except Exception:  # noqa: BLE001 -- a catalog built before catalog_runs existed
            return []
    rank = {"baseline": 0, "main": 1, "sample": 2}
    for r in rows:
        r["label"] = run_label(r["run_id"])
    return sorted(rows, key=lambda r: (r["scenario"], rank.get(r["kind"], 3), r["label"]))


# Each dimension's (id, name) columns. A fixed map, so nothing caller-supplied
# is ever interpolated into SQL.
_DIM_COLUMNS = {
    "group": ("group_id", "group_name"),
    "fleet": ("fleet_id", "fleet_name"),
    "partner": ("partner_id", "partner_name"),
}
_KEY_SEP = chr(31)  # between parent and partner key (SQL: chr(31)); in no EwE name


def _key_sql(dim: str) -> str:
    """A row's entity key in ``dim``: EwE's number where the file has one, else
    the lower-cased name (predation/prey files name species, never number them)."""
    id_col, name_col = _DIM_COLUMNS[dim]
    return f"coalesce(CAST({id_col} AS VARCHAR), lower({name_col}))"


def _picks_clause(dims: tuple[str, str | None], picks: list[list[str]]) -> tuple[str, list[str]]:
    parent, child = dims
    if child is None:
        keys, expr = [p[0] for p in picks if p], _key_sql(parent)
    else:
        keys = [f"{p[0]}{_KEY_SEP}{p[1]}" for p in picks if len(p) > 1]
        expr = f"{_key_sql(parent)} || chr(31) || {_key_sql(child)}"
    if not keys:
        return "FALSE", []
    return f"{expr} IN ({_placeholders(keys)})", keys


def variable_category(con, variable: str) -> str | None:
    """The Results-Extractor box of an output variable (``catalog_datasets``)."""
    rows = _rows(con, "SELECT any_value(category) AS category FROM catalog_datasets WHERE variable = ?", [variable])
    return rows[0]["category"] if rows else None


def list_selection_options(
    settings: Settings | None = None,
    *,
    category: str,
    variable: list[str],
    freq: str = "annual",
    scenario: list[str] | None = None,
) -> list[dict]:
    """The selection window of one Results-Extractor box (UG p.128-129): the
    entities of its parent dimension present in the data of ``variable`` (the
    box's checked variables) for the given scenarios -- and, in an "attached"
    box, each one's partners (``children``). Every entity is
    ``{key, id, name, variables}``: ``key`` is what ``picks`` take, ``id``/``name``
    are EwE's number and name, each completed from the model's Ecopath output
    where the file had only the other (if the scenarios mix models that name a
    number differently, the names are joined with " / "); ``variables`` are the
    ones it occurs in. Ordered by EwE number, unnumbered ones last by name."""
    dims = CATEGORY_DIMS.get(category)
    if dims is None:
        return []
    parent, child = dims
    settings = settings or get_settings()
    clauses = [f"variable IN ({_placeholders(variable)})", "freq = ?"]
    params: list = [*variable, freq]
    if scenario:
        clauses.append(f"scenario IN ({_placeholders(scenario)})")
        params += scenario
    pid, pname = _DIM_COLUMNS[parent]
    cols = [f"{_key_sql(parent)} AS pk", f"{pid} AS p_id", f"{pname} AS p_name"]
    keys = ["pk"]
    if child:
        cid, cname = _DIM_COLUMNS[child]
        cols += [f"{_key_sql(child)} AS ck", f"{cid} AS c_id", f"{cname} AS c_name"]
        keys.append("ck")
    values = ", ".join(f"any_value({c}) AS {c}" for c in ("p_id", "p_name", "c_id", "c_name")[: 2 * len(keys)])
    sql = (
        f"SELECT {', '.join(keys)}, {values}, list(DISTINCT variable ORDER BY variable) AS variables, "
        "list(DISTINCT model_name) AS model_names "
        f"FROM (SELECT {', '.join(cols)}, variable, model_name FROM timeseries WHERE {' AND '.join(clauses)}) "
        f"WHERE {' AND '.join(f'{k} IS NOT NULL' for k in keys)} GROUP BY {', '.join(keys)}"
    )
    with _ro(settings) as con:
        rows = _rows(con, sql, params)

    names = ecopath_group_names() if rows else {}
    numbers = _ecopath_numbers(names)

    def entity(dim: str, key: str, eid, name, models: list[str], variables: list[str]) -> dict:
        if dim != "fleet":  # groups, predators and prey are all functional groups
            found = {_resolve_group(m, eid, name, names, numbers) for m in models} or {(eid, name)}
            ids = {i for i, _ in found if i is not None}
            eid = ids.pop() if len(ids) == 1 else eid
            name = " / ".join(sorted({n for _, n in found if n})) or None
        return {"key": key, "id": eid, "name": name, "variables": variables}

    def order(e: dict):
        return (e["id"] is None, e["id"] or 0, (e["name"] or "").lower())

    parents: dict[str, dict] = {}
    for r in rows:
        models = r["model_names"] or []
        p = parents.get(r["pk"])
        if p is None:
            p = parents[r["pk"]] = entity(parent, r["pk"], r["p_id"], r["p_name"], models, [])
            if child:
                p["children"] = []
        p["variables"] = sorted(set(p["variables"]) | set(r["variables"]))
        if child:
            p["children"].append(entity(child, r["ck"], r["c_id"], r["c_name"], models, r["variables"]))
    result = sorted(parents.values(), key=order)
    for p in result:
        if child:
            p["children"].sort(key=order)
    return result


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
                   -- The time-series label where the same variable exists there
                   -- (e.g. ECOIND "Total B (ECOIND)"; its slug alone loses the case).
                   (SELECT any_value(d.label) FROM catalog_datasets d
                    WHERE d.variable = catalog_rasters.variable AND d.freq = 'monthly') AS label,
                   count(DISTINCT coalesce(CAST(group_id AS VARCHAR), group_name)) AS n_groups,
                   count(DISTINCT coalesce(CAST(fleet_id AS VARCHAR), fleet_name)) AS n_fleets,
                   min(year) AS year_min, max(year) AS year_max, count(*) AS n_rasters,
                   count(DISTINCT run_id) AS n_runs
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
    run: str | None = None,
) -> list[dict]:
    """Raster index rows for one (scenario, variable), optionally narrowed further
    -- for Monte Carlo maps (several runs, see ``list_raster_runs``) to one run."""
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
    if run is not None:
        clauses.append("run_id = ?")
        params.append(run)
    with _ro(settings) as con:
        return _rows(
            con,
            "SELECT * FROM catalog_rasters WHERE " + " AND ".join(clauses) + " ORDER BY year",
            params,
        )


def list_raster_runs(settings: Settings | None = None, *, scenario: str, variable: str) -> list[dict]:
    """The Monte Carlo runs one (scenario, variable)'s maps exist for --
    ``{run_id, kind, label}``, the baseline or main run first (see catalog/runs.py);
    empty for ordinary single-run maps."""
    settings = settings or get_settings()
    with _ro(settings) as con:
        rows = _rows(
            con,
            f"SELECT DISTINCT run_id, {RUN_KIND_SQL} AS kind FROM catalog_rasters "
            "WHERE scenario = ? AND variable = ? AND run_id IS NOT NULL",
            [scenario, variable],
        )
    rank = {"baseline": 0, "main": 1, "sample": 2}
    for r in rows:
        r["label"] = run_label(r["run_id"])
        r["scenario"] = scenario
    return sorted(rows, key=lambda r: (rank.get(r["kind"], 3), r["label"]))


def raster_sources(scenario: str, domain: str = "output", settings: Settings | None = None) -> list[dict]:
    """``{source_path, source_crs_wkt}`` of every map of one scenario -- to find
    the grid its maps share (regions/datagrid.py)."""
    settings = settings or get_settings()
    with _ro(settings) as con:
        return _rows(
            con,
            "SELECT DISTINCT source_path, source_crs_wkt FROM catalog_rasters WHERE scenario = ? AND domain = ?",
            [scenario, domain],
        )


def get_raster(raster_id: str, settings: Settings | None = None) -> dict | None:
    settings = settings or get_settings()
    with _ro(settings) as con:
        rows = _rows(con, "SELECT * FROM catalog_rasters WHERE id = ?", [raster_id])
    return rows[0] if rows else None


def _placeholders(values: list) -> str:
    return ", ".join("?" for _ in values)
