"""Spatial ingestion: raw Ecospace ``.asc`` grids -> raster index -> lazy COGs.

Two phases with very different cost profiles, split because the raw archive
is huge (~13k files, ~28 GB) and any single analysis only ever touches a tiny
slice of it:

* :func:`build_raster_index` (fast, eager) — discovers every raster's identity
  (scenario/model/variable/entity/year) and where its raw ``.asc`` source
  lives, writing ``raster_index.csv`` (loaded into DuckDB as
  ``catalog_rasters`` by :mod:`ecosim.catalog.build`). Grid geometry is
  constant per model, not per file, so this only reads one ``Ecospace
  RunInfo.txt`` per scenario folder plus filenames — no per-file I/O, no
  rasterio. Safe to re-run after new raw data lands; call it from ``ecosim
  ingest-spatial`` or the "Reload Data" admin endpoint.
* :func:`materialize_raster` (lazy, cached) — converts one indexed raster to
  a Cloud-Optimized GeoTIFF under ``data/spatial/`` only when something asks
  for it (an API request, or later an R job-sandbox prep step), then reuses
  that file forever after. This is the only place raw pixels get read/written.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ecosim.core.config import Settings, get_settings
from ecosim.core.schema import RASTER_INDEX_COLUMNS, slugify
from ecosim.ingestion.parsers.asc_grid import parse_input_filename, parse_output_filename, write_cog
from ecosim.ingestion.parsers.ecosim_csv import read_header
from ecosim.ingestion.parsers.group_map import Dictionaries, parse_group_map


@dataclass
class SpatialIndexReport:
    rasters_indexed: int = 0
    files_seen: int = 0
    errors: list[str] = field(default_factory=list)
    # False when no Mapa_grupy_fleets.xlsx was found -- indexing still ran
    # (see Dictionaries.empty()); group/fleet entity names still resolve from
    # the .asc filename itself (see asc_grid.py) even without a dictionary,
    # only the canonical numeric group_id/fleet_id columns stay null.
    group_dictionary_found: bool = True


@dataclass
class _Source:
    src_path: Path
    variable: str
    domain: str
    entity_type: str | None
    entity_name: str | None
    year: int
    model_id: str | None
    model_name: str | None
    scenario_id: str
    crs_wkt: str | None = None


def _find_group_map(root: Path) -> Path | None:
    candidates = list(root.glob("Mapa_grupy_fleets.xlsx")) or list(root.rglob("Mapa_grupy_fleets.xlsx"))
    return candidates[0] if candidates else None


def _discover_output_rasters(output_raw_dir: Path) -> list[_Source]:
    """Find every Ecospace ``.asc`` output map anywhere under
    ``output_raw_dir`` and its accompanying ``Ecospace RunInfo.txt``.

    Scans recursively without assuming any folder name ("output/", "asc/")
    or nesting depth -- see ``pipeline.py``'s module docstring for why (no
    such convention is documented anywhere in the official EwE manual).
    Rasters are grouped by whichever folder they're actually found in; that
    folder's own ``Ecospace RunInfo.txt``, if present alongside them, gives
    the authoritative ``ModelName``/``EcosimScenario``/``StartYear``/
    ``CoordinateSystemWKT`` -- the same content-based rule ``_discover_output``
    uses for CSV scenarios, so ids line up with the time-series store. If no
    ``RunInfo.txt`` sits with them, still-recognisable Ecospace map filenames
    are indexed anyway (scenario id falls back to the containing folder's
    name) rather than being silently dropped.
    """
    out: list[_Source] = []
    if not output_raw_dir.exists():
        return out
    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for grid in output_raw_dir.rglob("*.asc"):
        # Cheap shape check only (real start_year applied below, per folder)
        # -- just to skip non-Ecospace .asc files before grouping.
        if parse_output_filename(grid.name, start_year=1998) is not None:
            by_dir[grid.parent].append(grid)

    for asc_dir, grids in sorted(by_dir.items()):
        runinfo = asc_dir / "Ecospace RunInfo.txt"
        header = read_header(runinfo) if runinfo.exists() else {}
        model_label = header.get("ModelName")
        # Fallback only matters when RunInfo.txt is missing (rare -- it's
        # empirically always present alongside real Ecospace output, just
        # not officially documented, see docs/ewe-data-formats.md). Prefer
        # the parent folder's name over the immediate one, since the
        # immediate folder is sometimes a generic name like "asc".
        scenario_label = header.get("EcosimScenario") or asc_dir.parent.name or asc_dir.name
        start_year = int(header.get("StartYear", 1998))
        model_id = slugify(model_label) if model_label else None
        scenario_id = slugify(scenario_label)
        # CoordinateSystemWKT confirms which projection Ecospace actually used
        # for this scenario's grid (traditional WGS84/decimal-degrees vs. the
        # "Assume Square Cells" local-UTM/metres mode -- see
        # docs/ewe-data-formats.md) -- carried into the index so write_cog can
        # verify it at materialize time instead of silently assuming WGS84.
        crs_wkt = header.get("CoordinateSystemWKT")
        for grid in sorted(grids):
            meta = parse_output_filename(grid.name, start_year=start_year)
            if meta is None:
                continue
            out.append(_Source(
                src_path=grid, variable=meta.variable, domain="output",
                entity_type=meta.entity_type, entity_name=meta.entity_name, year=meta.year,
                model_id=model_id, model_name=model_label, scenario_id=scenario_id,
                crs_wkt=crs_wkt,
            ))
    return out


def _discover_input_rasters(input_raw_dir: Path) -> list[_Source]:
    """Find real driver grids anywhere under ``input_raw_dir``, not assuming
    an "input/" folder name or fixed nesting depth (see ``pipeline.py``'s
    module docstring for why). Unlike output maps, these carry no embedded
    scenario/driver identity of their own (see
    ``parsers/asc_grid.parse_input_filename``) -- the file's own parent
    folder names the driver, its grandparent the scenario, the same
    EwE-external convention ``_discover_input`` relies on for the CSV
    equivalent of this data.

    Real exports can contain duplicate mirrored copies of the same grids
    (observed empirically -- a "Conected_xml_<scenario>/<model>/..." copy
    kept in sync with the real one, for EwE's own scenario-XML wiring, not a
    second independent driver). Previously filtered by requiring an exact
    path depth from an "input/" root; deduplicated by (scenario, driver,
    year) identity instead now, so it works regardless of how deep any
    particular copy happens to be nested -- first one found for a given key
    wins, since both are supposed to be identical anyway.

    No ``Ecospace RunInfo.txt`` exists for driver grids, so ``crs_wkt`` stays
    unset (the ``_Source`` default) -- these grids are not projection-checked
    at materialize time, same as today.
    """
    out: list[_Source] = []
    if not input_raw_dir.exists():
        return out
    seen: set[tuple[str, str, int]] = set()
    for grid in sorted(input_raw_dir.rglob("*.asc")):
        driver = grid.parent.name
        scenario_dir = grid.parent.parent.name
        meta = parse_input_filename(grid.name, driver=driver)
        if meta is None:
            continue
        key = (slugify(scenario_dir), slugify(driver), meta.year)
        if key in seen:
            continue
        seen.add(key)
        out.append(_Source(
            src_path=grid, variable=meta.variable, domain="input",
            entity_type=None, entity_name=None, year=meta.year,
            model_id=None, model_name=None, scenario_id=slugify(scenario_dir),
        ))
    return out


def _entity(source: _Source, dicts: Dictionaries) -> tuple[int | None, str | None, int | None, str | None, str]:
    """Resolve (group_id, group_name, fleet_id, fleet_name, entity_slug) for a source."""
    if source.entity_type == "group":
        gid = dicts.group_id_by_name(source.entity_name)
        gname = dicts.group_name(gid) if gid is not None else source.entity_name
        return gid, gname, None, None, slugify(gname or source.entity_name)
    if source.entity_type == "fleet":
        fid = dicts.fleet_id_by_name(source.entity_name)
        fname = dicts.fleet_name(fid) if fid is not None else source.entity_name
        return None, None, fid, fname, slugify(fname or source.entity_name)
    return None, None, None, None, "none"


def _cog_path(spatial_dir: Path, scenario: str, domain: str, variable: str,
              entity_slug: str, year: int) -> Path:
    return (
        spatial_dir
        / f"scenario={scenario}" / f"domain={domain}" / f"variable={variable}"
        / f"{entity_slug}__{year}.tif"
    )


def build_raster_index(settings: Settings | None = None) -> SpatialIndexReport:
    """Fast, eager pass: discover every raster and record where its raw source
    lives. Converts nothing -- see :func:`materialize_raster` for that."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    report = SpatialIndexReport()
    # Optional, same as run_ingest() -- see Dictionaries.empty() and
    # validate_output_root()'s docstring for why this must never block
    # indexing real .asc output.
    dict_path = _find_group_map(settings.output_raw_dir)
    dicts = parse_group_map(dict_path) if dict_path else Dictionaries.empty()
    report.group_dictionary_found = dict_path is not None

    sources = _discover_output_rasters(settings.output_raw_dir)
    if settings.input_raw_dir is not None:
        sources += _discover_input_rasters(settings.input_raw_dir)
    index_rows: list[dict] = []
    # raster id -> source .asc path already claiming it, to catch the case
    # Ecospace was configured to write spatial output at monthly (not just
    # annual) cadence -- confirmed possible by the official docs ("especially
    # when writing spatial output for every monthly time step", UG p.182) --
    # which our id scheme (no month dimension) can't distinguish. Without this
    # check, two .asc files for the same year would silently collide on one
    # id, discarding all but whichever happened to load last.
    seen_ids: dict[str, Path] = {}
    for source in sources:
        report.files_seen += 1
        try:
            gid, gname, fid, fname, entity_slug = _entity(source, dicts)
            raster_id = f"{source.scenario_id}|{source.domain}|{source.variable}|{entity_slug}|{source.year}"
            if raster_id in seen_ids:
                raise ValueError(
                    f"duplicate raster id {raster_id!r} -- {source.src_path.name} and "
                    f"{seen_ids[raster_id].name} both map to the same (scenario, variable, "
                    "entity, year); likely Ecospace was configured to write spatial output "
                    "more than once per year (e.g. monthly), which this pipeline's "
                    "year-only raster id does not support"
                )
            seen_ids[raster_id] = source.src_path
            out_path = _cog_path(
                settings.spatial_dir, source.scenario_id, source.domain,
                source.variable, entity_slug, source.year,
            )
            index_rows.append({
                "id": raster_id,
                "model": source.model_id, "model_name": source.model_name,
                "scenario": source.scenario_id, "domain": source.domain, "variable": source.variable,
                "group_id": gid, "group_name": gname, "fleet_id": fid, "fleet_name": fname,
                "year": source.year,
                "path": out_path.relative_to(settings.spatial_dir).as_posix(),
                # Absolute, not relative-to-raw_dir: output and input rasters
                # now come from two independently-chosen roots, so there is
                # no single shared root left to store paths relative to.
                "source_path": str(source.src_path),
                "source_crs_wkt": source.crs_wkt,
            })
            report.rasters_indexed += 1
        except Exception as exc:  # noqa: BLE001 - collect and continue
            report.errors.append(f"{source.src_path.name}: {exc}")

    _export_index(index_rows, settings.spatial_dir)
    return report


def materialize_raster(row: dict, settings: Settings | None = None) -> Path:
    """Ensure the COG for one raster-index row exists on disk; return its path.

    Converts from the raw ``.asc`` (``row['source_path']``, an absolute path)
    only on first call for a given raster -- every call after that just
    returns the already-cached file. This is the single lazy-cache
    chokepoint, used by the ``/spatial/raster/{id}`` endpoint and, later, by
    the R job-sandbox prep step.
    """
    settings = settings or get_settings()
    out_path = settings.spatial_dir / row["path"]
    if not out_path.exists():
        write_cog(Path(row["source_path"]), out_path, source_crs_wkt=row.get("source_crs_wkt"))
    return out_path


def _export_index(rows: list[dict], spatial_dir: Path) -> None:
    spatial_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=RASTER_INDEX_COLUMNS) if rows else pd.DataFrame(columns=RASTER_INDEX_COLUMNS)
    df.to_csv(spatial_dir / "raster_index.csv", index=False)
