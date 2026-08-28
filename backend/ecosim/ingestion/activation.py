"""Orchestrates "make this data source the active one and (re)build the
canonical store" -- the one thing both the API (``api/routers/sources.py``)
and the CLI (``ecosim sources activate``) need.

Output and input are independent sources, but they feed ONE combined
canonical store, so activating either one re-ingests using whichever
output+input pair is active afterwards (the one just activated, plus
whatever was already active for the other kind -- or ``None`` if that kind
has nothing active yet).

Kept out of ``core.workspace`` deliberately: ``core.config`` imports
``core.workspace``, so if ``core.workspace`` imported ingestion code (which
itself imports ``core.config``) that would be a circular import. This module
sits one layer above both, so it can safely depend on everything.
"""

from __future__ import annotations

from dataclasses import dataclass

from ecosim.catalog.build import build_catalog
from ecosim.core.config import settings_for_sources
from ecosim.core.workspace import DataSource, WorkspaceRegistry
from ecosim.ingestion.pipeline import run_ingest
from ecosim.ingestion.spatial_pipeline import build_raster_index


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
    # False when no Mapa_grupy_fleets.xlsx was found for this output source --
    # ingestion still succeeded (group_id/fleet_id are preserved; only
    # *_name columns are unresolved, and raster entity names still come from
    # filenames regardless -- see Dictionaries.empty()). Non-blocking; the
    # frontend surfaces this as an informational note, not an error.
    group_dictionary_found: bool = True


def _empty_result(source_id: str) -> ActivationResult:
    return ActivationResult(
        source_id=source_id, models=[], scenarios=[], datasets=0, rows=0,
        files_read=0, errors=0, rasters_indexed=0, spatial_errors=0,
        group_dictionary_found=True,
    )


def activate_source(registry: WorkspaceRegistry, source: DataSource) -> ActivationResult:
    """(Re)build the combined canonical store for {this source} + {whatever
    is active for the other kind}, and only once that succeeds, make this
    source active for its kind.

    Deliberately does *not* flip the active id before ingestion: whatever
    was working before must stay active if this attempt fails, rather than
    leaving the app pointed at a broken/empty store just because the user
    tried (and failed) to add something new. Safe to call again on an
    already-active source (that's what "Rescan" does) -- ingestion is
    idempotent, it just re-scans from scratch.
    """
    other_kind = "input" if source.kind == "output" else "output"
    other = registry.active(other_kind)
    output = source if source.kind == "output" else other
    input_source = source if source.kind == "input" else other

    if output is None:
        # Activating an input source before any output source exists: valid
        # (register + remember it), but there's nothing to ingest into a
        # combined store yet -- output is what models/scenarios/groups all
        # derive from. Ingestion runs once an output source is activated.
        registry.mark_scanned(source.id, ok=True)
        registry.set_active(source.id)
        registry.keep_only(source.kind, source.id)
        return _empty_result(source.id)

    settings = settings_for_sources(output, input_source)
    settings.ensure_dirs()
    try:
        report = run_ingest(settings)
        spatial_report = build_raster_index(settings)
        # A missing group/fleet dictionary must never block ingestion (see
        # Dictionaries.empty()) -- but finding literally nothing at all
        # (zero scenarios, zero rasters) is a different problem: it means
        # this source's *shape* didn't match anything this pipeline knows
        # how to discover, independent of the dictionary question. Catching
        # it here, not just in validate_output_root() (registration-time
        # only, not re-checked on activate/rescan), so activation never
        # silently "succeeds" over an empty/wrong folder.
        if not report.scenarios and spatial_report.rasters_indexed == 0:
            raise RuntimeError(
                "No scenario results or spatial maps were found for this source "
                "-- check this is really pointed at your model's output."
            )
        build_catalog(settings)
    except Exception as exc:  # noqa: BLE001 -- surfaced via source.status, not swallowed
        registry.mark_scanned(source.id, ok=False, error=str(exc))
        raise ActivationError(str(exc)) from exc

    registry.mark_scanned(source.id, ok=True)
    registry.set_active(source.id)
    # Only prune the previous source for this kind now that the new one has
    # actually proven itself -- see keep_only()'s docstring for why this
    # can't happen at add_source() time.
    registry.keep_only(source.kind, source.id)
    return ActivationResult(
        source_id=source.id,
        models=[m["id"] for m in report.models],
        scenarios=[s["id"] for s in report.scenarios],
        datasets=report.datasets_written,
        rows=report.rows_written,
        files_read=report.files_read,
        errors=len(report.errors),
        rasters_indexed=spatial_report.rasters_indexed,
        spatial_errors=len(spatial_report.errors),
        group_dictionary_found=report.group_dictionary_found and spatial_report.group_dictionary_found,
    )
