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

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ecosim.core.config import Settings, get_settings
from ecosim.core.schema import RASTER_INDEX_COLUMNS, slugify
from ecosim.ingestion.file_access import UnreadableFileError, describe_read_error, is_cloud_only
from ecosim.ingestion.parsers.asc_grid import parse_input_filename, parse_output_filename, write_cog
from ecosim.ingestion.parsers.ecosim_csv import read_header
from ecosim.ingestion.pipeline import _PROGRESS_EVERY, IngestCancelled, ProgressFn


@dataclass
class SpatialIndexReport:
    rasters_indexed: int = 0
    files_seen: int = 0
    errors: list[str] = field(default_factory=list)
    # True when any scenario's rasters were found under 2+ distinct source
    # directories -- Monte Carlo/Ecosampler, not one ordinary run. See
    # pipeline.IngestReport.has_multiple_runs (same concept, raster side).
    has_multiple_runs: bool = False
    # Distinct source directories seen for whichever scenario spans the
    # most -- 1 for ordinary single-run data. See pipeline.IngestReport's
    # matching field.
    run_count: int = 1
    # .asc files found but whose filename matches no map format this
    # pipeline recognises -- NOT indexed. Counted (with a few example names)
    # instead of dropped silently: a real 2026-09-24 source had 119,067
    # ECOIND-style "biodiv_ind_<indicator>-<timestep>.asc" maps and the scan
    # reported "0 rasters" with no hint why.
    unrecognized_files: int = 0
    unrecognized_examples: list[str] = field(default_factory=list)


_UNRECOGNIZED_EXAMPLES = 3


def _note_unrecognized(report: SpatialIndexReport, paths: list[Path]) -> None:
    report.unrecognized_files += len(paths)
    for p in paths[: _UNRECOGNIZED_EXAMPLES - len(report.unrecognized_examples)]:
        report.unrecognized_examples.append(p.name)


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
    # nullable str -- see core/schema.py's run_id docstring note. Only set
    # when this scenario's rasters were found under 2+ distinct directories.
    run_id: str | None = None


def _any_output_raster(root: Path) -> bool:
    """True as soon as one recognisable Ecospace ``.asc`` filename is found
    anywhere under ``root`` -- an existence check for ``validate_output_root``,
    not full discovery. No ``RunInfo.txt`` read needed at all (that's only
    for resolving scenario identity, irrelevant to a yes/no check) and no
    grouping/sorting -- just the raw ``rglob`` generator, first match wins.
    See ``pipeline.py::validate_output_root`` for why this matters at scale."""
    if not root.exists():
        return False
    for grid in root.rglob("*.asc"):
        if parse_output_filename(grid.name, start_year=1998) is not None:
            return True
    return False


def _discover_output_rasters(output_raw_dir: Path, unrecognized: list[Path] | None = None) -> list[_Source]:
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

    ``unrecognized``, when given, collects every ``.asc`` whose filename
    matches no known map format -- see ``SpatialIndexReport.unrecognized_files``.
    """
    if not output_raw_dir.exists():
        return []
    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for grid in output_raw_dir.rglob("*.asc"):
        # Cheap shape check only (real start_year applied below, per folder)
        # -- just to skip non-Ecospace .asc files before grouping.
        if parse_output_filename(grid.name, start_year=1998) is not None:
            by_dir[grid.parent].append(grid)
        elif unrecognized is not None:
            unrecognized.append(grid)

    # Pass 1: resolve each directory's own scenario identity (as before),
    # but don't emit _Source objects yet -- run_id (pass 2) depends on
    # knowing, for every scenario, how many distinct directories it spans.
    dirs_by_scenario: dict[str, list[Path]] = defaultdict(list)
    dir_info: dict[Path, dict] = {}
    for asc_dir, grids in sorted(by_dir.items()):
        runinfo = asc_dir / "Ecospace RunInfo.txt"
        try:
            header = read_header(runinfo) if runinfo.exists() else {}
        except OSError as exc:
            raise UnreadableFileError(describe_read_error(exc, runinfo, output_raw_dir)) from exc
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
        dir_info[asc_dir] = {
            "grids": grids, "model_id": model_id, "model_label": model_label,
            "scenario_id": scenario_id, "start_year": start_year, "crs_wkt": crs_wkt,
        }
        dirs_by_scenario[scenario_id].append(asc_dir)

    # Pass 2: a scenario spanning 2+ directories is Monte Carlo/Ecosampler,
    # not one ordinary run split across folders (see core/schema.py's run_id
    # docstring note) -- only then does run_id get populated, so an ordinary
    # single-directory scenario's raster ids stay exactly as before this
    # existed.
    out: list[_Source] = []
    for asc_dir, info in dir_info.items():
        is_multi_run = len(dirs_by_scenario[info["scenario_id"]]) > 1
        run_id = str(asc_dir.relative_to(output_raw_dir)) if is_multi_run else None
        for grid in sorted(info["grids"]):
            meta = parse_output_filename(grid.name, start_year=info["start_year"])
            if meta is None:
                continue
            out.append(_Source(
                src_path=grid, variable=meta.variable, domain="output",
                entity_type=meta.entity_type, entity_name=meta.entity_name, year=meta.year,
                model_id=info["model_id"], model_name=info["model_label"],
                scenario_id=info["scenario_id"], crs_wkt=info["crs_wkt"], run_id=run_id,
            ))
    return out


def _any_input_raster(root: Path) -> bool:
    """True as soon as one recognisable driver ``.asc`` grid is found
    anywhere under ``root`` -- existence check for ``validate_input_root``,
    not full discovery (no dedup/grouping needed for a yes/no answer)."""
    if not root.exists():
        return False
    for grid in root.rglob("*.asc"):
        if parse_input_filename(grid.name, driver=grid.parent.name) is not None:
            return True
    return False


def _discover_input_rasters(input_raw_dir: Path, unrecognized: list[Path] | None = None) -> list[_Source]:
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
            if unrecognized is not None:
                unrecognized.append(grid)
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


def _entity(source: _Source) -> tuple[int | None, str | None, int | None, str | None, str]:
    """Resolve (group_id, group_name, fleet_id, fleet_name, entity_slug) for a
    source. Ecospace ``.asc`` filenames are natively self-describing (see
    asc_grid.py) -- the entity *name* comes straight from the filename with
    no external lookup involved. The numeric id has no source at all here
    (EwE's filenames never carry one) and always stays null."""
    if source.entity_type == "group":
        return None, source.entity_name, None, None, slugify(source.entity_name)
    if source.entity_type == "fleet":
        return None, None, None, source.entity_name, slugify(source.entity_name)
    return None, None, None, None, "none"


def _cog_path(spatial_dir: Path, scenario: str, domain: str, variable: str,
              entity_slug: str, year: int, run_id: str | None = None) -> Path:
    # run_id folded into the filename (slugified -- it's a raw relative
    # directory path like "Sample_00001/ecosim_SSP1_A002", not safe as-is)
    # when present, so two Monte Carlo runs of the same scenario/variable/
    # entity/year materialize to genuinely different cached files instead
    # of silently colliding on the same COG path on disk.
    stem = f"{entity_slug}__{year}" + (f"__{slugify(run_id)}" if run_id else "")
    return (
        spatial_dir
        / f"scenario={scenario}" / f"domain={domain}" / f"variable={variable}"
        / f"{stem}.tif"
    )


def build_raster_index(
    settings: Settings | None = None,
    on_progress: ProgressFn | None = None,
    cancel_event: threading.Event | None = None,
) -> SpatialIndexReport:
    """Fast, eager pass: discover every raster and record where its raw source
    lives. Converts nothing -- see :func:`materialize_raster` for that.

    ``on_progress(phase, done, total)`` -- optional, same contract as
    ``pipeline.run_ingest``'s, for a caller to surface live progress on a
    very large raster archive instead of the request looking hung.
    ``cancel_event`` -- same cooperative-cancellation contract as
    ``pipeline.run_ingest``'s; raises ``pipeline.IngestCancelled`` when set."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    report = SpatialIndexReport()

    if on_progress is not None:
        on_progress("discovering_rasters", 0, None)
    # settings.output_raw_dir may genuinely be None here (ingesting an
    # *input* source in isolation into its own cache slot -- see
    # config.py's settings_for_single_source, mirrors pipeline.run_ingest's
    # identical guard); _discover_output_rasters has no None-safety of its
    # own, hence the guard rather than passing None straight through.
    unrecognized: list[Path] = []
    sources = (
        _discover_output_rasters(settings.output_raw_dir, unrecognized)
        if settings.output_raw_dir is not None else []
    )
    run_ids_by_scenario: dict[str, set[str]] = defaultdict(set)
    for s in sources:
        if s.run_id:
            run_ids_by_scenario[s.scenario_id].add(s.run_id)
    if run_ids_by_scenario:
        report.run_count = max(len(v) for v in run_ids_by_scenario.values())
    if settings.input_raw_dir is not None:
        sources += _discover_input_rasters(settings.input_raw_dir, unrecognized)
    _note_unrecognized(report, unrecognized)
    total = len(sources)
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
        if report.files_seen % _PROGRESS_EVERY == 0:
            if on_progress is not None:
                on_progress("rasters", report.files_seen, total)
            if cancel_event is not None and cancel_event.is_set():
                raise IngestCancelled()
        try:
            gid, gname, fid, fname, entity_slug = _entity(source)
            raster_id = f"{source.scenario_id}|{source.domain}|{source.variable}|{entity_slug}|{source.year}"
            if source.run_id:
                raster_id += f"|{source.run_id}"
            if raster_id in seen_ids:
                raise ValueError(
                    f"duplicate raster id {raster_id!r} -- {source.src_path.name} and "
                    f"{seen_ids[raster_id].name} both map to the same (scenario, variable, "
                    "entity, year" + (", run" if source.run_id else "") + "); likely Ecospace "
                    "was configured to write spatial output more than once per year (e.g. "
                    "monthly), which this pipeline's year-only raster id does not support"
                )
            seen_ids[raster_id] = source.src_path
            out_path = _cog_path(
                settings.spatial_dir, source.scenario_id, source.domain,
                source.variable, entity_slug, source.year, source.run_id,
            )
            index_rows.append({
                "id": raster_id,
                "model": source.model_id, "model_name": source.model_name,
                "scenario": source.scenario_id, "domain": source.domain, "variable": source.variable,
                "group_id": gid, "group_name": gname, "fleet_id": fid, "fleet_name": fname,
                "year": source.year,
                "run_id": source.run_id,
                "path": out_path.relative_to(settings.spatial_dir).as_posix(),
                # Absolute, not relative-to-raw_dir: output and input rasters
                # now come from two independently-chosen roots, so there is
                # no single shared root left to store paths relative to.
                "source_path": str(source.src_path),
                "source_crs_wkt": source.crs_wkt,
            })
            report.rasters_indexed += 1
            if source.run_id:
                report.has_multiple_runs = True
        except Exception as exc:  # noqa: BLE001 - collect and continue
            report.errors.append(f"{source.src_path.name}: {exc}")

    if on_progress is not None and total:
        on_progress("rasters", total, total)
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
        src = Path(row["source_path"])
        try:
            write_cog(src, out_path, source_crs_wkt=row.get("source_crs_wkt"))
        except Exception as exc:
            # A cloud-only .asc (see file_access.py) fails deep inside
            # rasterio with an unhelpful message -- say what's actually wrong.
            # Anything else (e.g. write_cog's own CRS ValueError) is already
            # meaningful and propagates unchanged.
            if is_cloud_only(src):
                raise UnreadableFileError(describe_read_error(exc, src)) from exc
            raise
    return out_path


def _export_index(rows: list[dict], spatial_dir: Path) -> None:
    spatial_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=RASTER_INDEX_COLUMNS) if rows else pd.DataFrame(columns=RASTER_INDEX_COLUMNS)
    df.to_csv(spatial_dir / "raster_index.csv", index=False)
