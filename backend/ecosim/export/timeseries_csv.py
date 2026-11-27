"""Export of selected Ecosim time series as CSV -- the platform's counterpart of
the Results Extractor's "Save Results" (.CSV) (UG p.127-131).

One CSV per variable, holding exactly the selection: its scenarios, the
groups/fleets (and, in an "attached" box, their partners) picked in its
Results-Extractor box, and the year/month range. Tidy, one value per row, with
the group/fleet columns named after their role in the box (e.g. ``prey`` and
``predator`` for "Prey with attached predators") so a file reads on its own.
"Yearly" is the Results Extractor's option: "the mean over the year" of the
monthly values (UG p.131), here with ``n_months`` -- how many months each mean
covers (fewer than 12 for a month range or a part year). Monte Carlo data carries
``p05``/``p95``/``n_samples`` next to the baseline ``value`` (catalog/runs.py), or
is one run's.

File names encode the selection (``file_stem``), and the archive carries a
README.txt and selection.json, as the spatial export does.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd

from ecosim.export.spatial_ascii import name_part

_FIELD_SEP = "__"

# Each box's dimension columns and the role they play in it (see
# catalog/categories.py CATEGORY_DIMS for which column is which).
ROLE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "functional_groups": [("group", "group")],
    "predators_with_prey": [("group", "predator"), ("partner", "prey")],
    "prey_with_predators": [("group", "prey"), ("partner", "predator")],
    "fleets_only": [("fleet", "fleet")],
    "fleets_with_prey": [("fleet", "fleet"), ("group", "group")],
    # age_id = age in months
    "age_structure": [("group", "group"), ("partner", "age")],
}


def time_label(freq: str, yearly: bool) -> str:
    if freq == "monthly" and yearly:
        return "yearly-mean"
    return freq


def range_label(year_from: int | None, year_to: int | None,
                month_from: int | None = None, month_to: int | None = None) -> str:
    years = f"{year_from if year_from is not None else 'start'}-{year_to if year_to is not None else 'end'}"
    if (month_from or 1, month_to or 12) != (1, 12):  # a season, e.g. "_m06-08"
        years += f"_m{month_from or 1:02d}-{month_to or 12:02d}"
    return years


def file_stem(*, model: str | None, scenarios: list[str], variable: str, time: str, years: str) -> str:
    """``<model>__<scenario or N-scenarios>__<variable>__<annual|monthly|yearly-mean>__<years>``."""
    scenario = scenarios[0] if len(scenarios) == 1 else f"{len(scenarios)}-scenarios"
    return _FIELD_SEP.join(name_part(p) for p in (model or "no-model", scenario, variable, time, years))


def _role_columns(category: str | None, rows: list[dict]) -> list[tuple[str, str]]:
    if category in ROLE_COLUMNS:
        return ROLE_COLUMNS[category]
    # Indicators, fitting statistics, drivers: whatever dimension the data has.
    return [(d, d) for d in ("group", "fleet", "partner")
            if any(r.get(f"{d}_id") is not None or r.get(f"{d}_name") is not None for r in rows)]


def table(rows: list[dict], *, category: str | None, freq: str, yearly: bool) -> pd.DataFrame:
    """The CSV of one variable's rows (as ``service.query_timeseries`` returns them)."""
    roles = _role_columns(category, rows)
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "model": df["model_name"].fillna(df["model"]),
        "scenario": df["scenario"],
        "year": df["year"],
    })
    if freq == "monthly":
        out["month"] = df["month"]
    for dim, role in roles:
        out[f"{role}_id"] = df[f"{dim}_id"].astype("Int64")
        out[role] = df[f"{dim}_name"]
    out["value"] = df["value"]
    bands = [c for c in ("p05", "p95") if c in df.columns]
    for c in bands:
        out[c] = df[c]
    if "n_samples" in df.columns:
        out["n_samples"] = df["n_samples"]
    if freq == "monthly" and yearly:
        # The yearly mean of each monthly percentile -- not a percentile of
        # yearly means, which the runs' rows would be needed for.
        values = ["value", *bands]
        keys = [c for c in out.columns if c not in ("month", *values, "n_samples")]
        grouped = out.groupby(keys, dropna=False, sort=False)
        means = grouped[values].mean()
        means["n_months"] = grouped["value"].count()
        if "n_samples" in out.columns:
            means["n_samples"] = grouped["n_samples"].min()
        out = means.reset_index()
    return out


def _readme(selection: dict, files: list[tuple[str, dict]]) -> str:
    lines = [
        "Ecosim time series -- selected data",
        "===================================",
        "",
        f"Exported: {selection['exported']}",
        f"Data source: {selection.get('data_source') or '-'}",
        f"Time step: {selection['time_step']}",
        f"Years: {selection['years']}",
        f"Monte Carlo runs: {selection.get('runs') or 'baseline run with the samples 5th-95th percentile (p05, p95), where the data has runs'}",
        "",
        "File names: <model>__<scenario>__<variable>__<time step>__<years>.csv",
        "  (a file of several scenarios is named <N>-scenarios; its 'scenario' column tells them apart).",
        "",
        "Columns: model, scenario, year[, month], the group/fleet columns of the variable's",
        "Results-Extractor box -- an EwE number (<role>_id) and name each (e.g. prey_id, prey,",
        "predator_id, predator) -- and value. Names and numbers missing from an EwE file are",
        "completed from the model's Ecopath output where it was loaded.",
    ]
    if selection["time_step"] == "yearly-mean":
        lines += [
            "",
            "Yearly: each value is the mean over the year of the monthly values, as the EwE",
            "Results Extractor's 'Yearly' option computes it (EwE User Guide, Results Extractor);",
            "n_months is the number of months averaged (fewer than 12 for a month range or a part year).",
        ]
    lines += ["", "Files:"]
    for name, item in files:
        lines.append(f"  {name}")
        lines.append(f"    {item['label']} ({item['variable']}) -- box: {item['box'] or '-'}; "
                     f"scenarios: {', '.join(item['scenarios'])}; selection: {item['selection']}; "
                     f"rows: {item['rows']}")
    lines += ["", "selection.json holds the same selection in machine-readable form."]
    return "\n".join(lines) + "\n"


def write_timeseries_zip(out, items: list[dict], *, selection: dict) -> int:
    """Write the zip to ``out``. ``items``: ``{variable, label, box, category, scenarios,
    selection, rows}`` per variable; ``selection``: ``freq``, ``yearly``, ``years`` and
    ``data_source``. Returns the number of CSV files written."""
    freq, yearly = selection["freq"], selection["yearly"]
    time = time_label(freq, yearly)
    meta = {
        **{k: v for k, v in selection.items() if k not in ("freq", "yearly")},
        "time_step": time,
        "exported": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    files: list[tuple[str, dict]] = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            if not item["rows"]:
                continue
            df = table(item["rows"], category=item["category"], freq=freq, yearly=yearly)
            models = sorted({m for m in df["model"].dropna()})
            name = file_stem(
                model=models[0] if len(models) == 1 else f"{len(models)}-models",
                scenarios=item["scenarios"], variable=item["variable"], time=time, years=selection["years"],
            ) + ".csv"
            buf = io.StringIO()
            df.to_csv(buf, index=False, float_format="%.10g")
            zf.writestr(name, buf.getvalue())
            files.append((name, {**{k: v for k, v in item.items() if k != "rows"}, "rows": len(df)}))
        zf.writestr("README.txt", _readme(meta, files))
        zf.writestr("selection.json", json.dumps(
            {**meta, "files": [{"file": n, **i} for n, i in files]}, indent=2, ensure_ascii=False,
        ))
    return len(files)
