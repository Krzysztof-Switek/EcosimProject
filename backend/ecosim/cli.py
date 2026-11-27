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


def _active_sources_or_exit():
    from ecosim.core.workspace import get_workspace_registry

    registry = get_workspace_registry()
    output = registry.active("output")
    if output is None:
        typer.echo("Error: No active model output data source. Run `ecosim sources activate <id>` first.")
        raise typer.Exit(1)
    input_source = registry.active("input")
    return registry, output, input_source


@app.command()
def ingest() -> None:
    """Force-rescan the active data source(s) into their own cache slots and
    rebuild the combined catalog -- same as ``ecosim sources activate``'s
    Rescan, looped over whichever of output/input are currently active (see
    ``ingestion.activation.rescan_source``)."""
    from ecosim.ingestion.activation import rescan_source

    registry, output, input_source = _active_sources_or_exit()
    typer.echo(f"Output source : {output.path}")
    typer.echo(f"Input source  : {input_source.path if input_source else '(none)'}")
    for source in [output] + ([input_source] if input_source else []):
        report = rescan_source(registry, source)
        typer.echo(
            f"[{source.kind}] {source.name}: scenarios={len(report.scenarios)} "
            f"files_read={report.files_read} datasets={report.datasets} rows={report.rows}"
        )
        if report.errors:
            typer.echo(f"  {report.errors} file(s) skipped with errors.")
        if report.skipped_unsupported:
            typer.echo(
                f"  {report.skipped_unsupported} file(s) recognised as a known-but-"
                "unsupported shape (Ecospace map-as-CSV / region-age-structure), "
                "skipped -- not errors."
            )


@app.command()
def ingest_spatial() -> None:
    """Force-rescan the active source(s)' .asc maps (fast) and rebuild the
    catalog -- see ``ingest``'s docstring; this is the same rescan, just
    described in spatial-only terms for anyone reaching for the old command
    name. Individual rasters are still converted to COGs lazily, on first
    request, via GET /spatial/raster/{id}.
    """
    from ecosim.ingestion.activation import rescan_source

    registry, output, input_source = _active_sources_or_exit()
    typer.echo(f"Output source : {output.path}")
    typer.echo(f"Input source  : {input_source.path if input_source else '(none)'}")
    for source in [output] + ([input_source] if input_source else []):
        report = rescan_source(registry, source)
        typer.echo(f"[{source.kind}] {source.name}: indexed={report.rasters_indexed}")
        if report.spatial_errors:
            typer.echo(f"  {report.spatial_errors} raster file(s) skipped with errors.")
    typer.echo("Catalog rebuilt.")


@app.command()
def catalog() -> None:
    """Rebuild only the DuckDB catalog from the existing per-source caches,
    without re-scanning any raw files."""
    from ecosim.ingestion.activation import combine_and_rebuild

    registry, _output, _input_source = _active_sources_or_exit()
    combine_and_rebuild(registry)
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

    Any folder works -- discovery scans recursively and matches on file
    content, not folder name or nesting depth. See docs/data-contract.md's
    "Oczekiwany układ katalogów źródłowych" for details.
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
    for warning in result.warnings:
        typer.echo(f"  Warning: {warning}")


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


auth_app = typer.Typer(help="Signing in (for a shared server).")
app.add_typer(auth_app, name="auth")


@auth_app.command("set-user")
def auth_set_user(username: str, role: str = typer.Option("tester", help="admin or tester")) -> None:
    """Add an account or set its password/role (the password is asked here,
    never on the command line). The first account must be an admin; that
    turns signing in on."""
    from ecosim.core import auth

    password = typer.prompt("Password (10+ characters)", hide_input=True, confirmation_prompt=True)
    try:
        auth.set_user(username, password, role)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(f"Account {username} ({role}) saved in {auth.auth_path()}.")


@auth_app.command("remove-user")
def auth_remove_user(username: str) -> None:
    from ecosim.core import auth

    try:
        removed = auth.remove_user(username)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(f"Removed {username}." if removed else f"No account {username}.")


@auth_app.command("status")
def auth_status() -> None:
    """Whether signing in is on, and the accounts."""
    from ecosim.core import auth

    cfg = auth.load_config()
    typer.echo(f"Signing in: {'on' if cfg else 'off'}{' (required by ECOSIM_REQUIRE_AUTH)' if auth.required() else ''}")
    for a in cfg.accounts if cfg else ():
        typer.echo(f"  {a.username}  ({a.role})")


@auth_app.command("disable")
def auth_disable() -> None:
    """Turn signing in off (removes auth.json) -- for a personal computer only."""
    from ecosim.core import auth

    typer.echo("Signing in turned off." if auth.disable() else "Signing in was not set up.")


regions_app = typer.Typer(help="Reference areas: region map packs (ICES, management layers).")
app.add_typer(regions_app, name="regions")


@regions_app.command("list")
def regions_list() -> None:
    """Imported region packs and their layers."""
    from ecosim.regions import store

    packs = store.list_packs()
    if not packs:
        typer.echo("No region packs imported.")
    for pack in packs:
        typer.echo(f"{pack['id']}  {pack['name']}  ({pack['source_path']})")
        for layer in pack["layers"]:
            g = layer["grid"]
            typer.echo(f"    {layer['key']:<45} {layer['kind']:<7} {len(layer['classes']):>4} classes  "
                       f"{g['ncols']}x{g['nrows']} {layer['crs']}")


@regions_app.command("import")
def regions_import(path: str, name: str = typer.Option(None, help="Name shown in the app")) -> None:
    """Copy a folder or .zip of region maps into the profile."""
    from pathlib import Path

    from ecosim.regions import store

    try:
        pack = store.import_pack(Path(path), name)
    except store.RegionPackError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    typer.echo(f"Imported {pack['id']} ({pack['name']}): {len(pack['layers'])} layers.")
    for warning in pack["warnings"]:
        typer.echo(f"  ! {warning}")


@regions_app.command("remove")
def regions_remove(pack_id: str) -> None:
    from ecosim.regions import store

    if not store.remove_pack(pack_id):
        typer.echo(f"Unknown region pack: {pack_id}")
        raise typer.Exit(1)
    typer.echo(f"Removed region pack {pack_id}.")


if __name__ == "__main__":
    app()
