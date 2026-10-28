"""Parser/converter for Ecospace ``.asc`` grid exports.

Two raw shapes, both plain ESRI ASCII grids read via ``rasterio``:

* **output** ``EcospaceMap{Biomass|Catch|Discards|Effort}-<entity>-<timestep>.asc``
  and ``LayerHabitatCapacity-<entity>-<timestep>.asc`` — one map per functional
  group (or fleet, for Effort) per annual snapshot. ``<timestep>`` is a 5-digit
  monthly step (the model runs monthly; maps are only emitted every 12th step),
  converted to a calendar year via the same ``StartYear + (t-1)//12`` rule used
  for monthly CSVs.
* **input** ``<code>_<year>.asc`` under an ``input/<scenario>/<driver>/`` folder
  — one map per year, no group/fleet dimension.

Geo-reference is not embedded in the raw ``.asc`` files themselves, so it is
attached when converting to the canonical Cloud-Optimized GeoTIFF (always
WGS84, what the map shows). The source CRS is, in order: the one the user set
for the data source (``DataSource.map_crs``), else each run's own
``CoordinateSystemWKT`` (from ``Ecospace RunInfo.txt``), else WGS84.

That declared CRS can be plainly wrong (real case, 2026-10-28): the
FuMa_SSP1_SCEN model's maps have ``xllcorner 4535378``/``cellsize 4000`` --
metres -- while its RunInfo.txt and the ``.prj`` files EwE writes next to its
ECOIND maps both say WGS 84 (degrees). Stamped as WGS84 that is a longitude of
4.5 million degrees, which Leaflet wraps around the world many times over (the
map showed up duplicated). :func:`write_cog` therefore refuses coordinates
that are impossible in a degree-based CRS (``MapCrsError``) and offers
candidate CRSs with the extent each would give, for the user to pick from --
the data itself never says which one is right. See docs/ewe-data-formats.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ecosim.core.schema import slugify

WGS84 = "EPSG:4326"

# Offered when a map's declared CRS can't be right (see MapCrsError): common
# projected CRSs for European seas, each shown with the lon/lat extent it would
# give so the user can see which one puts the grid where the model is. Only a
# shortlist to choose from, never picked automatically; any EPSG code can be
# entered instead.
CANDIDATE_CRS: list[tuple[str, str]] = [
    ("EPSG:3035", "ETRS89 / LAEA Europe"),
    ("EPSG:3034", "ETRS89 / LCC Europe"),
    ("EPSG:3857", "WGS 84 / Pseudo-Mercator"),
    ("EPSG:32633", "WGS 84 / UTM zone 33N"),
    ("EPSG:32634", "WGS 84 / UTM zone 34N"),
    ("EPSG:32635", "WGS 84 / UTM zone 35N"),
    ("EPSG:2180", "ETRS89 / Poland CS92"),
    ("EPSG:3006", "SWEREF99 TM"),
]


class MapCrsError(ValueError):
    """A map's coordinates are impossible in the CRS it is taken to be in
    (e.g. metres stamped as degrees). Carries what the UI needs to let the
    user choose the real CRS: the CRS used, the raw bounds, and candidates."""

    def __init__(self, message: str, *, crs: str, bounds: tuple[float, float, float, float]):
        super().__init__(message)
        self.crs = crs
        self.bounds = bounds
        self.candidates = [
            {"crs": code, "name": name, "extent": lonlat_extent(code, bounds)}
            for code, name in CANDIDATE_CRS
        ]


def _plausible_in_degrees(bounds: tuple[float, float, float, float]) -> bool:
    left, bottom, right, top = bounds
    return -180 <= left <= 180 and -180 <= right <= 180 and -90 <= bottom <= 90 and -90 <= top <= 90


def lonlat_extent(crs: str, bounds: tuple[float, float, float, float]) -> list[float] | None:
    """[west, south, east, north] in degrees of a grid with ``bounds`` in
    ``crs``, or None if it can't be placed on the globe at all."""
    import math

    from rasterio.errors import CRSError
    from rasterio.warp import transform_bounds

    try:
        west, south, east, north = transform_bounds(crs, WGS84, *bounds, densify_pts=21)
    except (CRSError, ValueError, RuntimeError):
        return None
    out = [west, south, east, north]
    if not all(math.isfinite(v) for v in out) or not _plausible_in_degrees((west, south, east, north)):
        return None
    return [round(v, 2) for v in out]

# prefix (lower-case) -> (canonical variable slug, entity dimension)
_OUTPUT_PREFIXES: dict[str, tuple[str, str]] = {
    "ecospacemapbiomass": ("biomass", "group"),
    "ecospacemapcatch": ("catch", "group"),
    "ecospacemapdiscards": ("discards", "group"),
    "ecospacemapeffort": ("effort", "fleet"),
    "layerhabitatcapacity": ("habitat_capacity", "group"),
}
_OUTPUT_RE = re.compile(r"^([A-Za-z]+)-(.+)-(\d+)\.asc$", re.IGNORECASE)
# Most drivers: "<code>_<year>.asc". CodRV uses a different export naming,
# "HIST_Baltic_all__yy<year>_map_....asc" — search for a year-like run of
# digits anywhere rather than anchoring to the filename's tail.
_INPUT_YEAR_RE = re.compile(r"(19|20)\d{2}")


@dataclass
class AscGridMeta:
    variable: str
    domain: str                # "output" | "input"
    entity_type: str | None    # "group" | "fleet" | None
    entity_name: str | None    # raw name from the filename (output only)
    year: int


def parse_output_filename(name: str, *, start_year: int) -> AscGridMeta | None:
    """Parse an Ecospace output map filename; ``None`` if not a recognised layer."""
    m = _OUTPUT_RE.match(name)
    if not m:
        return None
    mapped = _OUTPUT_PREFIXES.get(m.group(1).lower())
    if mapped is None:
        return None
    variable, entity_type = mapped
    entity_name, timestep = m.group(2).strip(), int(m.group(3))
    year = start_year + (timestep - 1) // 12
    return AscGridMeta(variable=variable, domain="output", entity_type=entity_type,
                        entity_name=entity_name, year=year)


def parse_input_filename(name: str, *, driver: str) -> AscGridMeta | None:
    """Parse an input-driver yearly grid filename; ``None`` if no year is found."""
    m = _INPUT_YEAR_RE.search(name)
    if not m:
        return None
    return AscGridMeta(variable=slugify(driver), domain="input", entity_type=None,
                        entity_name=None, year=int(m.group(0)))


def write_cog(
    src_path: Path,
    out_path: Path,
    *,
    source_crs_wkt: str | None = None,
    map_crs: str | None = None,
) -> dict:
    """Convert one ``.asc`` grid to a WGS84 Cloud-Optimized GeoTIFF.

    The grid's own CRS is ``map_crs`` (set by the user for the data source,
    e.g. ``"EPSG:3035"``) if given, else ``source_crs_wkt`` (the
    ``CoordinateSystemWKT`` from this run's Ecospace ``RunInfo.txt``), else
    WGS84 (input driver grids have no RunInfo.txt). A grid in a projected CRS
    (Ecospace's "Assume Square Cells" mode, or a model built on a metric grid)
    is reprojected to WGS84 with nearest-neighbour resampling, so cell values
    are copied, never interpolated. Raises ``MapCrsError`` if the coordinates
    can't be degrees although the CRS says they are.

    Returns raster metadata (width/height/cellsize/bounds of the written COG).
    Requires the ``spatial`` extra (``rasterio``), imported lazily so the rest
    of the platform has no hard dependency on GDAL.
    """
    import numpy as np
    import rasterio
    from rasterio.crs import CRS
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    if map_crs:
        src_crs = CRS.from_user_input(map_crs)
    elif source_crs_wkt:
        # EwE's own RunInfo.txt export quotes WKT string literals with ' rather
        # than the " standard OGC WKT requires (confirmed against a real file:
        # rasterio's parser rejects it as-is, "OGR Error code 5") -- normalize
        # before parsing.
        src_crs = CRS.from_wkt(source_crs_wkt.replace("'", '"'))
    else:
        src_crs = CRS.from_string(WGS84)

    with rasterio.open(src_path) as src:
        data = src.read(1)
        profile = src.profile.copy()
        bounds = tuple(src.bounds)

    crs_label = map_crs or (f"EPSG:{src_crs.to_epsg()}" if src_crs.to_epsg() else src_crs.to_string())
    if src_crs.is_geographic and not _plausible_in_degrees(bounds):
        raise MapCrsError(
            f"{src_path.name}: the map's coordinates (x {bounds[0]:,.0f} to {bounds[2]:,.0f}, "
            f"y {bounds[1]:,.0f} to {bounds[3]:,.0f}) can't be degrees, but its coordinate system "
            f"is {crs_label} ({src_crs.to_string() if map_crs else 'as declared by EwE'}), which is "
            "in degrees. The map is most likely on a metric grid -- choose the coordinate system "
            "it was built on.",
            crs=crs_label,
            bounds=bounds,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if src_crs.to_epsg() != 4326:
        nodata = profile.get("nodata")
        if nodata is None:
            nodata = -9999.0
        transform, width, height = calculate_default_transform(
            src_crs, WGS84, profile["width"], profile["height"], *bounds,
        )
        out = np.full((height, width), nodata, dtype=data.dtype)
        reproject(
            data, out,
            src_transform=profile["transform"], src_crs=src_crs, src_nodata=nodata,
            dst_transform=transform, dst_crs=WGS84, dst_nodata=nodata,
            resampling=Resampling.nearest,
        )
        data = out
        profile.update(width=width, height=height, transform=transform, nodata=nodata)

    profile.update(driver="COG", crs=CRS.from_string(WGS84), compress="DEFLATE")
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data, 1)
        out_bounds = dst.bounds

    return {
        "width": profile["width"],
        "height": profile["height"],
        "cellsize": abs(profile["transform"].a),
        "xmin": out_bounds.left, "ymin": out_bounds.bottom,
        "xmax": out_bounds.right, "ymax": out_bounds.top,
        "crs": WGS84,
    }
