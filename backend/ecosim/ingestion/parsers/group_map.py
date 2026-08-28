"""Parse ``Mapa_grupy_fleets.xlsx`` into the canonical group / fleet dictionaries.

The workbook has two sheets:
  * ``Grups``  -> columns ``No``, ``Group name``  (50 functional groups)
  * ``fleets`` -> columns ``No``, ``Name``         (9 fleets)

These dictionaries are the single source of truth for resolving the numeric
group/fleet ids used in the wide and long CSV outputs to human-readable names.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ecosim.core.schema import slugify


@dataclass(frozen=True)
class Dictionaries:
    groups: pd.DataFrame  # columns: id, name, slug
    fleets: pd.DataFrame  # columns: id, name, slug

    @classmethod
    def empty(cls) -> "Dictionaries":
        """No ``Mapa_grupy_fleets.xlsx`` was found nearby -- used instead of
        refusing to ingest. This dictionary is *this project's* own
        convention for resolving numeric group/fleet ids to names (EwE
        itself has no universal numbering convention, so numeric ids alone
        aren't meaningful across models -- see docs/ewe-data-formats.md
        §5) -- it was never something EwE packages with its own output, so
        its absence must not block ingesting output that's otherwise
        completely real and valid. Every caller of ``group_name``/
        ``fleet_name``/``*_id_by_name`` already handles "not found" as
        ``None`` (empty tables just mean everything is "not found"), and
        Ecospace raster filenames carry their entity name directly (see
        ``asc_grid.py``) so spatial data stays fully readable regardless."""
        empty = pd.DataFrame({
            "id": pd.Series(dtype="int64"),
            "name": pd.Series(dtype="object"),
            "slug": pd.Series(dtype="object"),
        })
        return cls(groups=empty.copy(), fleets=empty.copy())

    def group_name(self, group_id: int) -> str | None:
        row = self.groups.loc[self.groups["id"] == group_id, "name"]
        return None if row.empty else str(row.iloc[0])

    def fleet_name(self, fleet_id: int) -> str | None:
        row = self.fleets.loc[self.fleets["id"] == fleet_id, "name"]
        return None if row.empty else str(row.iloc[0])

    def group_id_by_name(self, name: str) -> int | None:
        """Resolve a group id from a (possibly differently-cased) name."""
        target = slugify(name)
        row = self.groups.loc[self.groups["slug"] == target, "id"]
        return None if row.empty else int(row.iloc[0])

    def fleet_id_by_name(self, name: str) -> int | None:
        """Resolve a fleet id from a (possibly differently-cased) name."""
        target = slugify(name)
        row = self.fleets.loc[self.fleets["slug"] == target, "id"]
        return None if row.empty else int(row.iloc[0])


def _read_sheet(path: Path, sheet: str, name_col_candidates: tuple[str, ...]) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=sheet)
    raw.columns = [str(c).strip() for c in raw.columns]
    id_col = next(c for c in raw.columns if c.lower() in {"no", "no.", "id"})
    name_col = next(c for c in raw.columns if c.strip() in name_col_candidates)
    df = raw[[id_col, name_col]].rename(columns={id_col: "id", name_col: "name"})
    df = df.dropna(subset=["id", "name"])
    df["id"] = df["id"].astype(int)
    df["name"] = df["name"].astype(str).str.strip()
    df["slug"] = df["name"].map(slugify)
    return df.reset_index(drop=True)


def parse_group_map(path: Path) -> Dictionaries:
    groups = _read_sheet(path, "Grups", ("Group name", "Group", "Name"))
    fleets = _read_sheet(path, "fleets", ("Name", "Fleet", "Fleet name"))
    return Dictionaries(groups=groups, fleets=fleets)
