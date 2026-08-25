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


def _find_group_map(raw_dir: Path) -> Path:
    candidates = list(raw_dir.glob("Mapa_grupy_fleets.xlsx")) or list(raw_dir.rglob("Mapa_grupy_fleets.xlsx"))
    if not candidates:
        raise FileNotFoundError(f"Mapa_grupy_fleets.xlsx not found under {raw_dir}")
    return candidates[0]


def _discover_output_rasters(raw_dir: Path) -> list[_Source]:
    """Find every ``asc/`` run folder under ``output/`` and its map files.

    Each run's own ``Ecospace RunInfo.txt`` (not the parent folder name) gives
    the authoritative ``ModelName``/``EcosimScenario`` — the same rule used for
    CSV scenarios, so ids line up with the time-series store.
    """
    out: list[_Source] = []
    output_root = raw_dir / "output"
    if not output_root.exists():
        return out
    for asc_dir in sorted(p for p in output_root.rglob("asc") if p.is_dir()):
        runinfo = asc_dir / "Ecospace RunInfo.txt"
        header = read_header(runinfo) if runinfo.exists() else {}
        model_label = header.get("ModelName")
        scenario_label = header.get("EcosimScenario") or asc_dir.parent.name
        start_year = int(header.get("StartYear", 1998))
        model_id = slugify(model_label) if model_label else None
        scenario_id = slugify(scenario_label)
        for grid in sorted(asc_dir.glob("*.asc")):
            meta = parse_output_filename(grid.name, start_year=start_year)
            if meta is None:
                continue
            out.append(_Source(
                src_path=grid, variable=meta.variable, domain="output",
                entity_type=meta.entity_type, entity_name=meta.entity_name, year=meta.year,
                model_id=model_id, model_name=model_label, scenario_id=scenario_id,
            ))
    return out


def _discover_input_rasters(raw_dir: Path) -> list[_Source]:
    """Find real driver grids: ``input/<export>/<scenario>/<driver>/<...>.asc``.

    Depth is checked (exactly 4 path parts below ``input/``) to skip the
    duplicate copies nested under ``.../Conected_xml_<scenario>/<model>/...``,
    which mirror the same grids for the Ecosim scenario-XML wiring.
    """
    out: list[_Source] = []
    input_root = raw_dir / "input"
    if not input_root.exists():
        return out
    for grid in sorted(input_root.rglob("*.asc")):
        rel = grid.relative_to(input_root)
        if len(rel.parts) != 4:
            continue
        _export, scenario_dir, driver, _name = rel.parts
        meta = parse_input_filename(grid.name, driver=driver)
        if meta is None:
            continue
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
    dicts = parse_group_map(_find_group_map(settings.raw_dir))

    sources = _discover_output_rasters(settings.raw_dir) + _discover_input_rasters(settings.raw_dir)
    index_rows: list[dict] = []
    for source in sources:
        report.files_seen += 1
        try:
            gid, gname, fid, fname, entity_slug = _entity(source, dicts)
            out_path = _cog_path(
                settings.spatial_dir, source.scenario_id, source.domain,
                source.variable, entity_slug, source.year,
            )
            index_rows.append({
                "id": f"{source.scenario_id}|{source.domain}|{source.variable}|{entity_slug}|{source.year}",
                "model": source.model_id, "model_name": source.model_name,
                "scenario": source.scenario_id, "domain": source.domain, "variable": source.variable,
                "group_id": gid, "group_name": gname, "fleet_id": fid, "fleet_name": fname,
                "year": source.year,
                "path": out_path.relative_to(settings.spatial_dir).as_posix(),
                "source_path": source.src_path.relative_to(settings.raw_dir).as_posix(),
            })
            report.rasters_indexed += 1
        except Exception as exc:  # noqa: BLE001 - collect and continue
            report.errors.append(f"{source.src_path.name}: {exc}")

    _export_index(index_rows, settings.spatial_dir)
    return report


def materialize_raster(row: dict, settings: Settings | None = None) -> Path:
    """Ensure the COG for one raster-index row exists on disk; return its path.

    Converts from the raw ``.asc`` (``row['source_path']``, relative to
    ``raw_dir``) only on first call for a given raster -- every call after
    that just returns the already-cached file. This is the single lazy-cache
    chokepoint, used by the ``/spatial/raster/{id}`` endpoint and, later, by
    the R job-sandbox prep step.
    """
    settings = settings or get_settings()
    out_path = settings.spatial_dir / row["path"]
    if not out_path.exists():
        write_cog(settings.raw_dir / row["source_path"], out_path)
    return out_path


def _export_index(rows: list[dict], spatial_dir: Path) -> None:
    spatial_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=RASTER_INDEX_COLUMNS) if rows else pd.DataFrame(columns=RASTER_INDEX_COLUMNS)
    df.to_csv(spatial_dir / "raster_index.csv", index=False)
