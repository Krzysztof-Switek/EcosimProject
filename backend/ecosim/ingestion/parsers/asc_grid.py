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

Geo-reference (WGS84) is not embedded in the raw ``.asc`` files themselves, so
it is attached when converting to the canonical Cloud-Optimized GeoTIFF --
:func:`write_cog` checks this assumption against each run's own
``CoordinateSystemWKT`` (from ``Ecospace RunInfo.txt``) when it's known,
rather than assuming it silently. See docs/ewe-data-formats.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ecosim.core.schema import slugify

WGS84 = "EPSG:4326"

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


def write_cog(src_path: Path, out_path: Path, *, source_crs_wkt: str | None = None) -> dict:
    """Convert one ``.asc`` grid to a WGS84 Cloud-Optimized GeoTIFF.

    ``source_crs_wkt`` is the ``CoordinateSystemWKT`` this raster's Ecospace
    ``RunInfo.txt`` reported, if known -- verified against our hardcoded WGS84
    assumption before stamping it, since Ecospace can also run in a local
    UTM/metres "Assume Square Cells" mode that this pipeline does not support
    (see docs/ewe-data-formats.md). Pass ``None`` (e.g. input driver grids,
    which have no RunInfo.txt) to skip the check and keep today's behaviour.

    Returns raster metadata (width/height/cellsize/bounds) for the raster index.
    Requires the ``spatial`` extra (``rasterio``), imported lazily so the rest of
    the platform has no hard dependency on GDAL.
    """
    import rasterio
    from rasterio.crs import CRS

    if source_crs_wkt:
        # EwE's own RunInfo.txt export quotes WKT string literals with ' rather
        # than the " standard OGC WKT requires (confirmed against a real file:
        # rasterio's parser rejects it as-is, "OGR Error code 5") -- normalize
        # before parsing.
        reported = CRS.from_wkt(source_crs_wkt.replace("'", '"'))
        if reported.to_epsg() != 4326:
            raise ValueError(
                f"{src_path.name}: source Ecospace RunInfo.txt reports CRS "
                f"{reported.to_string()!r} (EPSG:{reported.to_epsg()}), not WGS84/EPSG:4326 -- "
                "likely built with Ecospace's 'Assume Square Cells' (local UTM/metres) mode, "
                "which this pipeline does not support. Converting it as WGS84 would silently "
                "mis-georeference it."
            )

    with rasterio.open(src_path) as src:
        data = src.read(1)
        profile = src.profile.copy()
        bounds = src.bounds

    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile.update(driver="COG", crs=CRS.from_string(WGS84), compress="DEFLATE")
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data, 1)

    return {
        "width": profile["width"],
        "height": profile["height"],
        "cellsize": abs(profile["transform"].a),
        "xmin": bounds.left, "ymin": bounds.bottom,
        "xmax": bounds.right, "ymax": bounds.top,
        "crs": WGS84,
    }
