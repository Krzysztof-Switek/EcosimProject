"""Command-line entry point: ``ecosim ingest`` / ``ecosim serve``."""

from __future__ import annotations

import typer

from ecosim.core.config import get_settings

app = typer.Typer(help="EwE / Ecosim analysis platform CLI.")


@app.command()
def ingest() -> None:
    """Parse DataEcosim/ into the canonical Parquet store and rebuild the catalog."""
    from ecosim.ingestion.pipeline import run_ingest

    settings = get_settings()
    typer.echo(f"Raw source : {settings.raw_dir}")
    typer.echo(f"Store      : {settings.store_dir}")
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
def catalog() -> None:
    """Rebuild only the DuckDB catalog from the existing Parquet store."""
    from ecosim.catalog.build import build_catalog

    build_catalog(get_settings())
    typer.echo("Catalog rebuilt.")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the FastAPI server."""
    import uvicorn

    uvicorn.run("ecosim.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
