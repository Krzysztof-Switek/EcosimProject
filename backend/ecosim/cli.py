"""Command-line entry point: ``ecosim ingest`` / ``ecosim serve`` / ``ecosim sources``."""

from __future__ import annotations

import typer

from ecosim.core.config import get_settings
from ecosim.core.workspace import NoActiveDataSourceError

app = typer.Typer(help="EwE / Ecosim analysis platform CLI.")
sources_app = typer.Typer(
    help="Manage registered model output/input data sources (network shares, "
    "local folders) -- see docs/Plans and TO_DO lists/27.08_data_upload_PLAN.md."
)
app.add_typer(sources_app, name="sources")


def _get_settings_or_exit():
    try:
        return get_settings()
    except NoActiveDataSourceError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1) from exc


@app.command()
def ingest() -> None:
    """Parse the active data source(s) into the canonical Parquet store and rebuild the catalog."""
    from ecosim.ingestion.pipeline import run_ingest

    settings = _get_settings_or_exit()
    typer.echo(f"Output source : {settings.output_raw_dir}")
    typer.echo(f"Input source  : {settings.input_raw_dir or '(none)'}")
    typer.echo(f"Store         : {settings.store_dir}")
    report = run_ingest(settings)
    typer.echo(
        f"Done. scenarios={len(report.scenarios)} "
        f"files_read={report.files_read} datasets={report.datasets_written} "
        f"rows={report.rows_written}"
    )
    for scn in report.scenarios:
        typer.echo(f"  - {scn['id']} ({scn['domain']})")
    if report.errors:
        typer.echo(f"\n{len(report.errors)} file(s) skipped:")
        for err in report.errors[:20]:
            typer.echo(f"  ! {err}")


@app.command()
def ingest_spatial() -> None:
    """Index the active source(s)' .asc maps (fast) and rebuild the catalog.

    Only discovers rasters and records where their raw source lives -- it
    does not convert anything, so it runs in well under a minute even for
    ~13k files. Individual rasters are converted to COGs lazily, on first
    request, via GET /spatial/raster/{id}. Safe to re-run after new raw
    scenarios arrive.
    """
    from ecosim.ingestion.spatial_pipeline import build_raster_index

    settings = _get_settings_or_exit()
    typer.echo(f"Output source : {settings.output_raw_dir}")
    typer.echo(f"Input source  : {settings.input_raw_dir or '(none)'}")
    typer.echo(f"Spatial store : {settings.spatial_dir}")
    report = build_raster_index(settings)
    typer.echo(f"Done. files_seen={report.files_seen} indexed={report.rasters_indexed}")
    if report.errors:
        typer.echo(f"\n{len(report.errors)} file(s) skipped with errors:")
        for err in report.errors[:20]:
            typer.echo(f"  ! {err}")

    from ecosim.catalog.build import build_catalog

    build_catalog(settings)
    typer.echo("Catalog rebuilt.")


@app.command()
def catalog() -> None:
    """Rebuild only the DuckDB catalog from the existing Parquet store."""
    from ecosim.catalog.build import build_catalog

    build_catalog(_get_settings_or_exit())
    typer.echo("Catalog rebuilt.")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the FastAPI server."""
    import uvicorn

    uvicorn.run("ecosim.api.app:app", host=host, port=port, reload=reload)


@sources_app.command("list")
def sources_list() -> None:
    """List registered data sources, grouped by kind; * marks each kind's active one."""
    from ecosim.core.workspace import get_workspace_registry

    registry = get_workspace_registry()
    known = registry.list_sources()
    if not known:
        typer.echo("No data sources registered yet. Add one with `ecosim sources add`.")
        return
    for kind in ("output", "input"):
        active = registry.active(kind)
        typer.echo(f"\n{kind}:")
        for s in [s for s in known if s.kind == kind]:
            mark = "*" if active and s.id == active.id else " "
            typer.echo(f"{mark} {s.id}  [{s.status:9}]  {s.name!r:30}  {s.path}")


@sources_app.command("add")
def sources_add(name: str, path: str, kind: str = typer.Argument(..., help="'output' or 'input'")) -> None:
    """Register a new data source (does not activate/ingest it -- run `ecosim sources activate` next).

    See docs/data-contract.md's "Oczekiwany układ katalogów źródłowych" for
    the required folder layout (an 'output' or 'input' subfolder directly
    inside the selected path, plus -- for output -- Mapa_grupy_fleets.xlsx).
    """
    from pathlib import Path

    from ecosim.core.workspace import get_workspace_registry
    from ecosim.ingestion.pipeline import validate_input_root, validate_output_root

    if kind not in ("output", "input"):
        typer.echo("Error: kind must be 'output' or 'input'")
        raise typer.Exit(1)

    resolved = Path(path)
    if not resolved.is_dir():
        typer.echo(f"Error: not a reachable directory: {path}")
        raise typer.Exit(1)
    problems = (validate_output_root if kind == "output" else validate_input_root)(resolved)
    if problems:
        for p in problems:
            typer.echo(f"Error: {p}")
        raise typer.Exit(1)

    registry = get_workspace_registry()
    source = registry.add_source(name, resolved, kind)  # type: ignore[arg-type]
    typer.echo(f"Added {kind} source {source.id} ({source.name}) -> {source.path}")
    typer.echo(f"Run `ecosim sources activate {source.id}` to scan it in.")


@sources_app.command("activate")
def sources_activate(source_id: str) -> None:
    """Make a source active and (re)build the canonical store."""
    from ecosim.core.workspace import get_workspace_registry
    from ecosim.ingestion.activation import ActivationError, activate_source

    registry = get_workspace_registry()
    source = registry.get(source_id)
    if source is None:
        typer.echo(f"Unknown source: {source_id}")
        raise typer.Exit(1)
    try:
        result = activate_source(registry, source)
    except ActivationError as exc:
        typer.echo(f"Activation failed: {exc}")
        raise typer.Exit(1) from exc
    typer.echo(
        f"Activated {source.id} ({source.name}, {source.kind}). "
        f"datasets={result.datasets} rows={result.rows} rasters_indexed={result.rasters_indexed}"
    )
    if result.errors or result.spatial_errors:
        typer.echo(f"  ({result.errors} timeseries file(s), {result.spatial_errors} spatial file(s) skipped)")


@sources_app.command("remove")
def sources_remove(source_id: str) -> None:
    """Forget a source (never touches the raw directory itself)."""
    from ecosim.core.workspace import get_workspace_registry

    registry = get_workspace_registry()
    if registry.get(source_id) is None:
        typer.echo(f"Unknown source: {source_id}")
        raise typer.Exit(1)
    registry.remove_source(source_id)
    typer.echo(f"Removed {source_id} from the registry (raw data untouched).")


if __name__ == "__main__":
    app()
