"""Orchestrates "make this data source the active one and (re)build the
canonical store" -- the one thing both the API (``api/routers/sources.py``)
and the CLI (``ecosim sources activate``) need.

Two layers as of 2026-08-28 (see ``core/config.py``'s module docstring for
the full rationale -- a real ~400GB/~1hr source had to be fully re-ingested
just to switch back to it): each source gets its own independently-cached
ingest output (``core.config.source_cache_dir``), and a cheap "combine" step
merges whichever source(s) are currently active into the live, shared
store every time that set changes (activate/rescan-of-active/remove).
Re-activating a source whose cache is already valid skips raw-file
ingestion entirely -- ``activate_source``'s cache-validity check.

Kept out of ``core.workspace`` deliberately: ``core.config`` imports
``core.workspace``, so if ``core.workspace`` imported ingestion code (which
itself imports ``core.config``) that would be a circular import. This module
sits one layer above both, so it can safely depend on everything.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from ecosim.catalog.build import build_catalog
from ecosim.core.config import Settings, settings_for_single_source, source_cache_dir
from ecosim.core.schema import RASTER_INDEX_COLUMNS
from ecosim.core.workspace import DataSource, WorkspaceRegistry
from ecosim.ingestion.file_access import (
    can_make_local,
    check_files_are_local,
    release_keep_local,
    request_keep_local,
    scan_local_availability,
    wait_until_local,
)
from ecosim.ingestion.pipeline import IngestCancelled, IngestReport, ProgressFn, run_ingest
from ecosim.ingestion.spatial_pipeline import SpatialIndexReport, build_raster_index

log = logging.getLogger("ecosim.activation")

# The scenario dict shape run_ingest's seen_scenarios accumulates (see
# pipeline.py) -- not part of core/schema.py's tidy-row columns, so kept
# local to where it's actually consumed (combining/migrating scenarios.csv).
_SCENARIOS_COLUMNS = ["id", "label", "domain", "model", "model_name"]
_MODELS_COLUMNS = ["id", "name"]


class ActivationError(RuntimeError):
    """Ingestion failed while activating a data source. The source is left
    registered with ``status="error"`` (see ``mark_scanned``) so it still
    shows up -- with the reason -- in the source picker instead of silently
    vanishing or leaving the previous source half-replaced."""


@dataclass
class ActivationResult:
    source_id: str
    models: list[str]
    scenarios: list[str]
    datasets: int
    rows: int
    files_read: int
    errors: int
    rasters_indexed: int
    spatial_errors: int
    # "montecarlo" when either pipeline found 2+ distinct run directories for
    # the same (model,scenario)/(scenario) -- real Ecosampler/Monte Carlo
    # data, not one ordinary run (see core/schema.py's run_id docstring).
    # "mixed" when there's both timeseries and spatial data (the common
    # single-run case), "spatial"/"timeseries" when only one domain was
    # found, or None when nothing was found at all (empty-source path below).
    data_kind: str | None = None
    # Distinct source directories seen for the (largest) multi-run scenario --
    # 1 for ordinary data; shown on the Monte Carlo tile as "N samples".
    run_count: int = 1
    # Files recognised as a known-but-unsupported shape (Ecospace map-as-CSV
    # duplicate / region-age-structure) -- see pipeline.IngestReport's field
    # of the same name. Not counted in `errors`.
    skipped_unsupported: int = 0
    # Human-readable notes about anything the scan found but did NOT load
    # (unrecognised map files, unsupported CSV shapes, per-file errors) --
    # persisted in meta.json and shown on the source's row in the UI, so a
    # "successful" scan can never quietly leave data behind. See
    # ``_scan_warnings``.
    warnings: list[str] = field(default_factory=list)


def _data_kind(has_timeseries: bool, has_rasters: bool, is_montecarlo: bool) -> str | None:
    if is_montecarlo:
        return "montecarlo"
    if has_timeseries and has_rasters:
        return "mixed"
    if has_rasters:
        return "spatial"
    if has_timeseries:
        return "timeseries"
    return None


def _live_settings() -> Settings:
    """The combined, always-cheap-to-rebuild store every currently active
    source's cache gets merged into -- unchanged location/shape from before
    per-source caching existed. Deliberately NOT ``get_settings()`` (which
    requires an active *output* source and resolves raw dirs too): this only
    ever needs the store_dir location itself, which must stay valid even
    with nothing active at all (e.g. right after removing the only output
    source -- the live store still needs to exist as a well-formed, empty
    catalog, not error out)."""
    return Settings()


def _meta_path(source_id: str) -> Path:
    return source_cache_dir(source_id) / "meta.json"


def _write_meta(
    result: ActivationResult, *, started_at: datetime, finished_at: datetime,
    duration_seconds: float | None, migrated: bool = False,
) -> None:
    path = _meta_path(result.source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **asdict(result),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": duration_seconds,
        "migrated": migrated,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_meta(source_id: str) -> dict | None:
    path = _meta_path(source_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def scan_warnings(source_id: str) -> list[str]:
    """Warnings recorded by this source's last successful scan (see
    ``ActivationResult.warnings``) -- ``[]`` if none, or if no scan has
    been recorded."""
    meta = _read_meta(source_id)
    return list(meta.get("warnings") or []) if meta else []


def _result_from_meta(meta: dict) -> ActivationResult:
    fields = ActivationResult.__dataclass_fields__.keys()
    return ActivationResult(**{k: v for k, v in meta.items() if k in fields})


def _cache_is_valid(source: DataSource) -> bool:
    """Whether this source's own ingest cache is trustworthy enough to skip
    re-ingesting from raw files: the registry says the last scan succeeded
    AND its ``meta.json`` is genuinely still readable on disk. The second
    check matters because the registry can lie -- someone deleting
    ``sources/<id>/`` by hand (disk cleanup outside the app) would leave
    ``workspaces.json`` still saying ``status="ok"``. This is a filesystem-
    integrity check on the app's OWN cache, not the app deciding raw SOURCE
    data changed -- see ``core/config.py``'s module docstring for that
    boundary; it never inspects the raw directory at all."""
    return source.status == "ok" and _read_meta(source.id) is not None


def _read_csv_or_empty(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists():
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            pass
    return pd.DataFrame(columns=columns)


def _combine_csvs(paths: list[Path], columns: list[str]) -> pd.DataFrame:
    if not paths:
        return pd.DataFrame(columns=columns)
    return pd.concat([_read_csv_or_empty(p, columns) for p in paths], ignore_index=True)


def combine_and_rebuild(registry: WorkspaceRegistry) -> None:
    """Cheap: no raw-file I/O at all, just concatenating each active
    source's own already-computed per-source dictionaries/raster_index.csv
    into the live, shared store, then pointing the DuckDB catalog at the
    union of active sources' own Parquet directories. Called after every
    activation (cache-hit or fresh ingest), every rescan of a currently-
    active source, and every removal -- so the live store always reflects
    exactly whatever's active right now, even when nothing is (an empty,
    well-formed catalog rather than a dangling one)."""
    live = _live_settings()
    live.ensure_dirs()

    active = [s for s in (registry.active("output"), registry.active("input")) if s is not None]
    per_source = [settings_for_single_source(s) for s in active]

    scenarios = _combine_csvs([s.dictionaries_dir / "scenarios.csv" for s in per_source], _SCENARIOS_COLUMNS)
    if not scenarios.empty:
        # output+input sharing a scenario id (plausible -- a driver grid is
        # often named after the scenario it drives) used to dedupe for free
        # inside run_ingest()'s one shared dict when both domains were
        # ingested together in a single call. Now each source's own
        # scenarios.csv is independent, so a shared id would otherwise
        # produce two dim_scenarios rows once concatenated -> fan-out in
        # catalog/service.py's joins. Prefer the output row (carries the
        # real model/label; input's is just scenario_id.upper()).
        scenarios["_output_first"] = scenarios["domain"] != "output"
        scenarios = (
            scenarios.sort_values("_output_first")
            .drop_duplicates(subset="id", keep="first")
            .drop(columns="_output_first")
        )
    scenarios.to_csv(live.dictionaries_dir / "scenarios.csv", index=False)

    models = _combine_csvs([s.dictionaries_dir / "models.csv" for s in per_source], _MODELS_COLUMNS)
    models.to_csv(live.dictionaries_dir / "models.csv", index=False)

    rasters = _combine_csvs([s.spatial_dir / "raster_index.csv" for s in per_source], RASTER_INDEX_COLUMNS)
    rasters.to_csv(live.spatial_dir / "raster_index.csv", index=False)

    build_catalog(live, timeseries_dirs=[s.timeseries_dir for s in per_source])


def _scan_warnings(report: IngestReport, spatial_report: SpatialIndexReport) -> list[str]:
    """One plain-English line per kind of thing the scan found but did not
    load. Empty for a scan that loaded everything it saw."""
    out: list[str] = []
    if spatial_report.unrecognized_files:
        examples = ", ".join(f"\"{n}\"" for n in spatial_report.unrecognized_examples)
        out.append(
            f"{spatial_report.unrecognized_files:,} .asc map file(s) were not loaded: their names "
            f"match no map format this app recognises yet (e.g. {examples})."
        )
    if report.skipped_unsupported:
        out.append(
            f"{report.skipped_unsupported:,} CSV file(s) were skipped: a known EwE export shape "
            "this app does not load yet (Ecospace maps saved as CSV, or region/age-structure tables)."
        )
    if report.errors:
        out.append(f"{len(report.errors):,} CSV file(s) could not be loaded. First: {report.errors[0]}")
    if spatial_report.errors:
        out.append(
            f"{len(spatial_report.errors):,} .asc map file(s) could not be indexed. "
            f"First: {spatial_report.errors[0]}"
        )
    return out


def _download_to_this_computer(
    source: DataSource, on_progress: ProgressFn | None, cancel_event: threading.Event | None,
) -> None:
    """First phase of scanning a ``keep_local`` source: make sure every file
    is actually on this computer. Pins the folder (the sync app downloads in
    its own time -- see file_access.request_keep_local) and waits, reporting
    phase "downloading" as (bytes downloaded, bytes total). A no-op when
    nothing is missing. On cancel, un-pins so the sync app stops fetching
    the rest, then raises IngestCancelled like any other cancelled scan."""
    missing = scan_local_availability(source.path, cancel_event=cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        raise IngestCancelled()
    if not missing.cloud_only:
        return
    if on_progress is not None:
        on_progress("downloading", 0, missing.cloud_only_bytes)
    request_keep_local(source.path)
    finished = wait_until_local(
        source.path,
        on_progress=(lambda done, total: on_progress("downloading", done, total)) if on_progress else None,
        cancel_event=cancel_event,
    )
    if not finished:
        release_keep_local(source.path)
        raise IngestCancelled()


def _ingest_one_source(
    registry: WorkspaceRegistry, source: DataSource,
    on_progress: ProgressFn | None, cancel_event: threading.Event | None,
) -> ActivationResult:
    """Ingest exactly ONE source into its own cache slot -- the slow path
    (full raw-file scan), used by both a fresh activation and an explicit
    Rescan. Writes ``sources/<id>/meta.json`` on success. On failure or
    cancellation, any PRIOR successful scan's cache is left completely
    untouched (``run_ingest``/``build_raster_index`` only ever write into
    this fresh per-source location, nothing existing is cleared upfront) --
    a failed rescan never destroys a working cache."""
    settings = settings_for_single_source(source)
    settings.ensure_dirs()
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    try:
        if source.keep_local and can_make_local():
            _download_to_this_computer(source, on_progress, cancel_event)
        # Pre-scan gate (attributes only, never downloads anything): refuse
        # up front if files the scan needs are cloud-only, instead of dying
        # partway through on the first one that fails to download -- see
        # ingestion/file_access.py for the real case behind this. For a
        # keep_local source this just confirms the download above finished.
        check_files_are_local(
            source.path,
            on_progress=(lambda n: on_progress("checking_files", n, None)) if on_progress else None,
            cancel_event=cancel_event,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise IngestCancelled()
        report = run_ingest(settings, on_progress, cancel_event)
        spatial_report = build_raster_index(settings, on_progress, cancel_event)
        # Finding literally nothing at all (zero scenarios, zero rasters)
        # means this source's *shape* didn't match anything this pipeline
        # knows how to discover. Catching it here, not just in
        # validate_output_root() (registration-time only, not re-checked on
        # activate/rescan), so a scan never silently "succeeds" over an
        # empty/wrong folder.
        if not report.scenarios and spatial_report.rasters_indexed == 0:
            raise RuntimeError(
                " ".join([
                    "No scenario results or spatial maps were found for this source "
                    "-- check this is really pointed at your model's output.",
                    *_scan_warnings(report, spatial_report),
                ])
            )
    except IngestCancelled:
        # User-requested stop, not a failure: leave the registry (and
        # whatever cache this source had before, if any) completely
        # untouched -- the background runner records "cancelled" separately.
        raise
    except Exception as exc:  # noqa: BLE001 -- surfaced via source.status, not swallowed
        registry.mark_scanned(source.id, ok=False, error=str(exc))
        raise ActivationError(str(exc)) from exc

    duration = time.monotonic() - t0
    data_kind = _data_kind(
        has_timeseries=bool(report.scenarios),
        has_rasters=spatial_report.rasters_indexed > 0,
        is_montecarlo=report.has_multiple_runs or spatial_report.has_multiple_runs,
    )
    run_count = max(report.run_count, spatial_report.run_count)
    result = ActivationResult(
        source_id=source.id,
        models=[m["id"] for m in report.models],
        scenarios=[s["id"] for s in report.scenarios],
        datasets=report.datasets_written,
        rows=report.rows_written,
        files_read=report.files_read,
        errors=len(report.errors),
        rasters_indexed=spatial_report.rasters_indexed,
        data_kind=data_kind,
        run_count=run_count,
        spatial_errors=len(spatial_report.errors),
        skipped_unsupported=report.skipped_unsupported,
        warnings=_scan_warnings(report, spatial_report),
    )
    _write_meta(result, started_at=started_at, finished_at=datetime.now(timezone.utc), duration_seconds=duration)
    registry.mark_scanned(source.id, ok=True, data_kind=data_kind, run_count=run_count, scan_duration_seconds=duration)
    return result


def activate_source(
    registry: WorkspaceRegistry,
    source: DataSource,
    on_progress: ProgressFn | None = None,
    cancel_event: threading.Event | None = None,
    *,
    force_rescan: bool = False,
) -> ActivationResult:
    """Make ``source`` active for its kind. If its own cache is already
    valid (see ``_cache_is_valid``) and ``force_rescan`` wasn't requested,
    skips raw-file ingestion ENTIRELY and just recombines the live store
    from whichever sources are active -- this is what makes switching back
    to an already-scanned source instant instead of a full rescan.
    Otherwise runs the full (slow) ingest into this source's own cache slot
    first, exactly as before this existed.

    Deliberately does *not* flip the active id before a FRESH ingest
    succeeds: whatever was working before must stay active if this attempt
    fails, rather than leaving the app pointed at a broken/empty source just
    because the user tried (and failed) to add something new. A cache-hit
    re-activation can't fail this way (nothing is re-ingested), so there's
    nothing to guard there.

    ``on_progress``/``cancel_event`` are passed straight through to
    ``run_ingest``/``build_raster_index`` on the slow path -- see
    ``pipeline.ProgressFn``. Optional; callers that don't need live progress
    (tests, the CLI) can omit them.
    """
    if force_rescan or not _cache_is_valid(source):
        result = _ingest_one_source(registry, source, on_progress, cancel_event)
    else:
        result = _result_from_meta(_read_meta(source.id))  # type: ignore[arg-type]
    registry.set_active(source.id)
    combine_and_rebuild(registry)
    return result


def rescan_source(
    registry: WorkspaceRegistry,
    source: DataSource,
    on_progress: ProgressFn | None = None,
    cancel_event: threading.Event | None = None,
) -> ActivationResult:
    """Force a full re-ingest of exactly ONE source's own cache slot,
    regardless of its current status or whether it's active -- NEVER
    touches any other source's cache, and NEVER changes which source is
    active (least-surprise: a user rescanning a source they're not
    currently even looking at shouldn't silently switch what's live; it
    also means rescanning an inactive source never touches the shared live
    store at all, so there's zero concurrency risk with anyone currently
    reading the catalog). Only recombines the live store afterward if this
    source turned out to already be the active one, so its fresh data is
    reflected immediately rather than needing a separate re-activate."""
    result = _ingest_one_source(registry, source, on_progress, cancel_event)
    still_active = registry.active(source.kind)
    if still_active is not None and still_active.id == source.id:
        combine_and_rebuild(registry)
    return result


def remove_source_and_rebuild(registry: WorkspaceRegistry, source_id: str) -> None:
    """Forgets the source AND deletes its on-disk ingest cache, then
    immediately rebuilds the live combined store from whatever's left
    active. Doing these together (not leaving the rebuild to the next
    activation) is what keeps ``catalog.duckdb``'s ``timeseries`` VIEW from
    ever pointing at a just-deleted directory -- it re-executes
    ``read_parquet`` on every query, so a stale reference throws a raw
    DuckDB error instead of the clean 409 a missing active source is
    supposed to produce."""
    shutil.rmtree(source_cache_dir(source_id), ignore_errors=True)
    registry.remove_source(source_id)
    combine_and_rebuild(registry)


def migrate_legacy_store_if_needed(registry: WorkspaceRegistry) -> None:
    """One-time, idempotent migration from the pre-2026-08-28 single-global-
    store layout to per-source caching (see ``core/config.py``'s module
    docstring). Runs automatically at backend startup (``api/app.py``), not
    a separate command to remember: this only ever MOVES already-computed
    cache files into a new directory layout -- it never re-reads or
    re-interprets raw source data, so it doesn't conflict with the "never
    automatic" requirement, which is specifically about deciding raw data
    changed.

    Detects "old layout present, new layout not yet built" by checking for
    ``store/timeseries/`` existing while ``store/sources/`` doesn't -- a
    no-op on every later startup (already migrated) and on a fresh install
    (neither exists yet)."""
    live = _live_settings()
    legacy_timeseries = live.store_dir / "timeseries"
    sources_root = live.store_dir / "sources"
    if not legacy_timeseries.exists() or sources_root.exists():
        return

    migrated_any = False
    for domain in ("output", "input"):
        source = registry.active(domain)  # type: ignore[arg-type]
        if source is None:
            continue
        log.info("Migrating legacy store data for %s source %r (%s) to its own cache slot...", domain, source.name, source.id)
        _migrate_one_source(live, source, domain)
        migrated_any = True

    if migrated_any:
        combine_and_rebuild(registry)
        shutil.rmtree(legacy_timeseries, ignore_errors=True)
        log.info("Legacy store migration done -- future re-activation of these sources will skip re-scanning raw files.")


def _migrate_one_source(live: Settings, source: DataSource, domain: str) -> None:
    dest = settings_for_single_source(source)
    dest.ensure_dirs()

    # Parquet: rename (same-volume move, not a byte copy -- near-instant
    # regardless of data size) the scenario partitions belonging to this
    # domain out of the old flat layout into this source's own cache slot.
    for scenario_dir in sorted(live.timeseries_dir.glob("scenario=*")):
        src = scenario_dir / f"domain={domain}"
        if src.exists():
            dst = dest.timeseries_dir / scenario_dir.name / f"domain={domain}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    # Dictionaries/raster index: split the old combined CSVs by domain --
    # cheap (small metadata files), no raw-file involvement.
    scenarios = _read_csv_or_empty(live.dictionaries_dir / "scenarios.csv", _SCENARIOS_COLUMNS)
    matched = scenarios[scenarios["domain"] == domain] if not scenarios.empty else scenarios
    matched.to_csv(dest.dictionaries_dir / "scenarios.csv", index=False)

    if domain == "output":
        models = _read_csv_or_empty(live.dictionaries_dir / "models.csv", _MODELS_COLUMNS)
        models.to_csv(dest.dictionaries_dir / "models.csv", index=False)
    else:
        pd.DataFrame(columns=_MODELS_COLUMNS).to_csv(dest.dictionaries_dir / "models.csv", index=False)

    rasters = _read_csv_or_empty(live.spatial_dir / "raster_index.csv", RASTER_INDEX_COLUMNS)
    matched_rasters = rasters[rasters["domain"] == domain] if not rasters.empty else rasters
    matched_rasters.to_csv(dest.spatial_dir / "raster_index.csv", index=False)

    # duration_seconds/migrated=True is the honest answer -- the original
    # scan's real wall-clock time was never recorded pre-migration; the UI
    # shows "duration unknown" rather than a fabricated estimate.
    result = ActivationResult(
        source_id=source.id, models=[], scenarios=[], datasets=0, rows=0,
        files_read=0, errors=0, rasters_indexed=0, spatial_errors=0,
        data_kind=source.data_kind, run_count=source.run_count,
    )
    now = datetime.now(timezone.utc)
    _write_meta(result, started_at=now, finished_at=now, duration_seconds=None, migrated=True)


@dataclass
class ActivationProgress:
    """Live status of a background activation/rescan started by
    ``start_activation``/``start_rescan`` -- polled by ``GET
    /admin/sources/{id}/activation-status`` so the UI can show real,
    moving progress instead of a request that just looks hung on a very
    large dataset (real case, 2026-08-28: ~400GB / 800k+ files on a synced
    network path). Lives only in this process's memory (``_progress``
    below) -- lost on restart, which is fine, a restart means "start over"
    for whatever was mid-operation anyway, same as before this existed."""
    status: str = "running"  # "running" | "ok" | "error" | "cancelled"
    phase: str = "starting"
    files_done: int = 0
    files_total: int | None = None
    result: ActivationResult | None = None
    error: str | None = None
    # Which source this progress record belongs to -- needed by
    # ``get_running_activation`` since it has to scan all records without
    # already knowing the id (that's the whole point: the caller trying to
    # start a *different* activation doesn't know one is already running).
    source_id: str = ""


_progress: dict[str, ActivationProgress] = {}
_progress_lock = threading.Lock()
# One cooperative-cancellation flag per in-flight activation/rescan, keyed
# the same way as ``_progress``. Separate dict (not a field on
# ActivationProgress) because it's written by the API thread (request_cancel)
# and read by the background ingestion thread -- keeping it out of the
# dataclass makes that cross-thread contract obvious at a glance.
_cancel_events: dict[str, threading.Event] = {}


def get_activation_progress(source_id: str) -> ActivationProgress | None:
    with _progress_lock:
        return _progress.get(source_id)


def get_running_activation() -> ActivationProgress | None:
    """Any activation/rescan still in flight, regardless of which source or
    which operation -- used by the API route to reject starting a second one
    with 409 instead of letting two operations race to write the same live
    store. Deliberately one GLOBAL lock, not per-source: the only thing that
    genuinely needs mutual exclusion is the shared live-store combine step
    (``combine_and_rebuild``), and at this app's current scale (one admin
    at a time) a single lock is simplest. Note this makes rescanning an
    *inactive* source strictly safer than it looks: since it never touches
    the live store at all (see ``rescan_source``), it wouldn't actually
    need this lock for correctness -- the lock exists for the cases that do."""
    with _progress_lock:
        for p in _progress.values():
            if p.status == "running":
                return p
    return None


def request_cancel(source_id: str) -> bool:
    """Signal the in-flight activation/rescan for ``source_id`` to stop at
    its next checkpoint. Returns True if a running operation was actually
    found and signalled, False if there's nothing to cancel (already
    finished, or never started) -- the API route uses this to decide
    404 vs 202."""
    with _progress_lock:
        p = _progress.get(source_id)
        event = _cancel_events.get(source_id)
    if p is None or event is None or p.status != "running":
        return False
    event.set()
    return True


def _start_background(source: DataSource, run_work: Callable[[ProgressFn, threading.Event], ActivationResult]) -> None:
    """Shared background-thread + progress-tracking + cancel machinery for
    both ``start_activation`` and ``start_rescan`` -- ``run_work`` does the
    actual (activate-vs-rescan) work and returns an ``ActivationResult``."""
    cancel_event = threading.Event()
    with _progress_lock:
        _progress[source.id] = ActivationProgress(source_id=source.id)
        _cancel_events[source.id] = cancel_event

    def on_progress(phase: str, done: int, total: int | None) -> None:
        with _progress_lock:
            p = _progress.get(source.id)
            if p is not None:
                p.phase = phase
                p.files_done = done
                p.files_total = total

    def run() -> None:
        try:
            result = run_work(on_progress, cancel_event)
            with _progress_lock:
                p = _progress[source.id]
                p.status = "ok"
                p.phase = "done"
                p.result = result
        except IngestCancelled:
            with _progress_lock:
                p = _progress.setdefault(source.id, ActivationProgress(source_id=source.id))
                p.status = "cancelled"
                p.phase = "cancelled"
        except Exception as exc:  # noqa: BLE001 -- surfaced via progress status, not swallowed
            # The UI only ever gets str(exc); the traceback goes to the
            # backend log so a failure is diagnosable after the fact (there
            # was none at all before -- 2026-09-24).
            log.exception("Scan of data source %r (%s) failed", source.name, source.id)
            with _progress_lock:
                p = _progress.setdefault(source.id, ActivationProgress(source_id=source.id))
                p.status = "error"
                p.phase = "error"
                p.error = str(exc)
        finally:
            with _progress_lock:
                _cancel_events.pop(source.id, None)

    threading.Thread(target=run, daemon=True).start()


def start_activation(registry: WorkspaceRegistry, source: DataSource) -> None:
    """Kick off ``activate_source`` on a background thread and return
    immediately -- the API route responds right away instead of blocking for
    however long a very large, uncached dataset takes to fully ingest (a
    cached source instead finishes almost instantly, but still goes through
    this same tracked path for a consistent UI contract).
    ``get_activation_progress(source.id)`` reports live status until it
    reaches ``"ok"``/``"error"``/``"cancelled"``. A plain in-memory dict
    guarded by a lock is proportionate at this app's current scale (one
    admin, a handful of sources, per ``core.workspace``'s own docs) -- no
    task queue needed; see ``docs/architecture.md``'s deployment-modes note
    on a real async job queue being explicitly out of scope until Etap 4
    (server mode).
    """
    _start_background(source, lambda on_progress, cancel_event: activate_source(registry, source, on_progress, cancel_event))


def start_rescan(registry: WorkspaceRegistry, source: DataSource) -> None:
    """Kick off ``rescan_source`` on a background thread -- same
    progress/lock/cancel contract as ``start_activation``, but forces a real
    re-ingest of exactly this one source and never changes what's active
    (see ``rescan_source``'s docstring)."""
    _start_background(source, lambda on_progress, cancel_event: rescan_source(registry, source, on_progress, cancel_event))
