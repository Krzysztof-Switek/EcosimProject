"""Grid identity and geometry for ESRI ASCII grids.

Two grids are "the same" when their header numbers match (columns, rows,
lower-left corner, cell size). The CRS is deliberately NOT part of the match:
EwE's own maps can declare the wrong CRS (e.g. WGS 84 on a metric grid, see
docs/ewe-data-formats.md section 3), while a region pack carries its own,
checked ``.prj``.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

_EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class GridSignature:
    ncols: int
    nrows: int
    xll: float  # lower-left corner (not centre) of the lower-left cell
    yll: float
    cellsize: float

    def matches(self, other: "GridSignature") -> bool:
        if (self.ncols, self.nrows) != (other.ncols, other.nrows):
            return False
        tol = max(self.cellsize, other.cellsize) * 1e-6
        return (
            math.isclose(self.cellsize, other.cellsize, rel_tol=1e-9, abs_tol=tol)
            and math.isclose(self.xll, other.xll, abs_tol=tol)
            and math.isclose(self.yll, other.yll, abs_tol=tol)
        )

    def transform(self):
        from rasterio.transform import from_origin

        return from_origin(self.xll, self.yll + self.nrows * self.cellsize, self.cellsize, self.cellsize)

    def bounds(self) -> tuple[float, float, float, float]:
        return (self.xll, self.yll, self.xll + self.ncols * self.cellsize, self.yll + self.nrows * self.cellsize)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GridSignature":
        return cls(int(d["ncols"]), int(d["nrows"]), float(d["xll"]), float(d["yll"]), float(d["cellsize"]))

    def describe(self) -> str:
        return f"{self.ncols}×{self.nrows}, cell {self.cellsize:g}"


def read_asc_header(path: Path) -> GridSignature:
    """The six-line ESRI ASCII header only -- never the cell values."""
    header: dict[str, float] = {}
    with open(path, encoding="latin-1") as f:
        for _ in range(6):
            parts = f.readline().split()
            if len(parts) != 2:
                break
            header[parts[0].lower()] = float(parts[1])
    try:
        cellsize = header["cellsize"]
        ncols, nrows = int(header["ncols"]), int(header["nrows"])
        xll = header["xllcorner"] if "xllcorner" in header else header["xllcenter"] - cellsize / 2
        yll = header["yllcorner"] if "yllcorner" in header else header["yllcenter"] - cellsize / 2
    except KeyError as exc:
        raise ValueError(f"{path.name}: not an ESRI ASCII grid header (missing {exc.args[0]})") from exc
    return GridSignature(ncols, nrows, xll, yll, cellsize)


def cell_areas_km2(grid: GridSignature, crs) -> np.ndarray:
    """Area of every cell, shape (nrows, ncols), row 0 = north.

    Projected CRS: cellsize² in the CRS's linear unit (the Baltic packs use
    EPSG:3035, equal-area, so this is exact). Geographic CRS: spherical cell
    area R²·Δλ·(sin φ₂ − sin φ₁), which shrinks with cos(latitude).
    """
    if crs.is_geographic:
        top = grid.yll + grid.nrows * grid.cellsize
        edges = np.radians(top - np.arange(grid.nrows + 1) * grid.cellsize)
        per_row = _EARTH_RADIUS_KM**2 * math.radians(grid.cellsize) * np.abs(np.sin(edges[:-1]) - np.sin(edges[1:]))
        return np.repeat(per_row[:, None], grid.ncols, axis=1)
    metres = crs.linear_units_factor[1] if crs.linear_units_factor else 1.0
    side_km = grid.cellsize * metres / 1000.0
    return np.full((grid.nrows, grid.ncols), side_km * side_km)
