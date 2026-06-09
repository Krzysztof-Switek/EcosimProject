"""Parser for Ecosim time-series CSV exports.

A single function, :func:`parse_ecosim_csv`, normalises every shape EwE emits
into the canonical tidy schema (see :mod:`ecosim.core.schema`). Shapes handled,
dispatched on the *data header row* (not the filename, so it is robust):

* wide-by-id     ``year\\group`` / ``timestep\\group`` + numeric columns 1..N
* wide-by-name   ``year\\group`` + quoted group names  (the ``predation_*`` files)
* long           ``year, fleet, group, value``
* single series  ``year, value`` / ``timestep, value``  (fib, kemptonsq)

Each file is prefixed with a metadata header block delimited by
``"<HEADER .../>"`` lines and a ``Data,<Label>`` marker; both are parsed out.

The data section is reshaped with vectorised pandas (``melt``/``map``) rather
than per-row Python loops so monthly files with millions of cells ingest fast.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ecosim.core.schema import TIMESERIES_COLUMNS, slugify
from ecosim.ingestion.parsers.group_map import Dictionaries

_DEFAULT_START_YEAR = 1998


@dataclass
class EcosimCsvMeta:
    variable: str
    freq: str                        # "annual" | "monthly"
    start_year: int
    data_label: str | None = None
    target_group: str | None = None  # for predation_* files
    headers: dict[str, str] = field(default_factory=dict)


def _read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.reader(fh)]


def read_header(path: Path) -> dict[str, str]:
    """Read only the ``"<HEADER .../>"`` metadata block (stops at ``end``).

    Cheap way to get authoritative fields like ``EcosimScenario`` without
    loading a whole (possibly large) CSV.
    """
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            rows.append(row)
            if row and row[0].strip().startswith("<HEADER") and "end" in row[0]:
                break
    meta, _ = _parse_header_block(rows)
    return meta


def _parse_header_block(rows: list[list[str]]) -> tuple[dict[str, str], int]:
    """Return (key->value metadata, index of first row after the header block)."""
    meta: dict[str, str] = {}
    end = 0
    for i, row in enumerate(rows):
        if not row:
            continue
        first = row[0].strip()
        if first.startswith("<HEADER") and first.endswith("/>"):
            if "end" in first:
                end = i + 1
                break
            continue
        if len(row) >= 2:
            meta[first] = row[1].strip()
    return meta, end


def _find_data_section(rows: list[list[str]], start: int) -> tuple[str | None, int]:
    """Find the ``Data,<Label>`` marker; return (label, index of header row)."""
    label = None
    for i in range(start, len(rows)):
        if rows[i] and rows[i][0].strip() == "Data":
            label = rows[i][1].strip() if len(rows[i]) > 1 else None
            for j in range(i + 1, len(rows)):
                if any(cell.strip() for cell in rows[j]):
                    return label, j
    return label, start


def _variable_and_target(path: Path) -> tuple[str, str, str | None]:
    """Derive (variable_slug, freq, target_group) from the file name."""
    stem = path.stem
    freq = "monthly" if stem.endswith("_monthly") else "annual"
    for suffix in ("_annual", "_monthly"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    # Relational wide-by-name files: the species named in the file is the
    # "owner" (target → group) and the columns are the attached species
    # (partner). predation_<prey> = mortality of prey by each predator;
    # prey_<predator> = diet/consumption of a predator from each prey.
    if stem.startswith("predation_"):
        return "predation", freq, stem[len("predation_"):].strip()
    if stem.startswith("prey_"):
        return "prey", freq, stem[len("prey_"):].strip()
    return slugify(stem), freq, None


def _period(freq: str, time_value: pd.Series, start_year: int) -> pd.DataFrame:
    """Vectorised (date, year, month) from an annual year or monthly timestep series."""
    t = pd.to_numeric(time_value, errors="coerce").round().astype("int64")
    if freq == "annual":
        year = t
        month = pd.Series(1, index=t.index, dtype="int64")
    else:
        year = start_year + (t - 1) // 12
        month = (t - 1) % 12 + 1
    date = year.astype(str).str.zfill(4) + "-" + month.astype(str).str.zfill(2) + "-01"
    return pd.DataFrame({"date": date, "year": year, "month": month})


def parse_ecosim_csv(
    path: Path,
    dicts: Dictionaries,
    *,
    scenario: str,
    domain: str = "output",
) -> tuple[EcosimCsvMeta, pd.DataFrame]:
    rows = _read_rows(path)
    headers, after_header = _parse_header_block(rows)
    data_label, hdr_idx = _find_data_section(rows, after_header)
    variable, freq, target = _variable_and_target(path)
    start_year = int(headers.get("StartYear", _DEFAULT_START_YEAR))
    meta = EcosimCsvMeta(
        variable=variable, freq=freq, start_year=start_year,
        data_label=data_label, target_group=target, headers=headers,
    )

    header_row = [c.strip() for c in rows[hdr_idx]]
    data_rows = [r for r in rows[hdr_idx + 1:] if any(c.strip() for c in r)]
    first = header_row[0].lower() if header_row else ""

    if not data_rows:
        df = pd.DataFrame(columns=TIMESERIES_COLUMNS)
    elif first in {"year", "timestep"} and header_row[1:4] == ["fleet", "group", "value"]:
        df = _parse_long(header_row, data_rows, freq, start_year, dicts)
    elif len(header_row) == 2 and header_row[1].lower() == "value":
        df = _parse_single(data_rows, freq, start_year)
    elif first.endswith("\\group"):
        df = _parse_wide(header_row, data_rows, freq, start_year, dicts, target)
    else:
        raise ValueError(f"Unrecognised Ecosim CSV layout in {path.name}: header={header_row[:5]}")

    df["scenario"] = scenario
    df["domain"] = domain
    df["variable"] = variable
    df["freq"] = freq
    df["unit"] = data_label
    return meta, df.reindex(columns=TIMESERIES_COLUMNS)


def _frame(data_rows: list[list[str]], ncols: int, columns: list[str]) -> pd.DataFrame:
    """Build a string DataFrame from ragged CSV rows, padded/truncated to ncols."""
    padded = [(r + [""] * ncols)[:ncols] for r in data_rows]
    return pd.DataFrame(padded, columns=columns)


def _parse_single(data_rows, freq, start_year) -> pd.DataFrame:
    raw = _frame(data_rows, 2, ["t", "value"])
    out = _period(freq, raw["t"], start_year)
    out["value"] = pd.to_numeric(raw["value"], errors="coerce")
    return out


def _parse_long(header_row, data_rows, freq, start_year, dicts: Dictionaries) -> pd.DataFrame:
    raw = _frame(data_rows, 4, ["t", "fleet_id", "group_id", "value"])
    out = _period(freq, raw["t"], start_year)
    out["fleet_id"] = pd.to_numeric(raw["fleet_id"], errors="coerce").astype("Int64")
    out["group_id"] = pd.to_numeric(raw["group_id"], errors="coerce").astype("Int64")
    out["value"] = pd.to_numeric(raw["value"], errors="coerce")
    out["fleet_name"] = out["fleet_id"].map(_id_to_name(dicts.fleets))
    out["group_name"] = out["group_id"].map(_id_to_name(dicts.groups))
    return out


def _parse_wide(header_row, data_rows, freq, start_year, dicts, target) -> pd.DataFrame:
    ncols = len(header_row)
    time_col, *value_cols = header_row
    value_cols = [c for c in value_cols if c.strip()]
    raw = _frame(data_rows, ncols, header_row)

    long = raw.melt(id_vars=[time_col], value_vars=value_cols,
                    var_name="col", value_name="value")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long[long["value"].notna()].reset_index(drop=True)

    out = _period(freq, long[time_col], start_year)
    out["value"] = long["value"].values

    if all(c.strip().isdigit() for c in value_cols):  # wide-by-id
        out["group_id"] = pd.to_numeric(long["col"], errors="coerce").astype("Int64")
        out["group_name"] = out["group_id"].map(_id_to_name(dicts.groups))
    else:  # wide-by-name (predation): column = predator (partner)
        target_id = dicts.group_id_by_name(target) if target else None
        target_name = dicts.group_name(target_id) if target_id is not None else target
        out["group_id"] = target_id
        out["group_name"] = target_name
        name_to_id = {row["slug"]: int(row["id"]) for _, row in dicts.groups.iterrows()}
        slug = long["col"].map(slugify)
        out["partner_id"] = slug.map(name_to_id).astype("Int64")
        out["partner_name"] = long["col"].values
    return out


def _id_to_name(dim: pd.DataFrame) -> dict[int, str]:
    return {int(r["id"]): str(r["name"]) for _, r in dim.iterrows()}
