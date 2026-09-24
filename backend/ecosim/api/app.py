"""FastAPI application factory.

Mounts the catalog, dictionary and time-series routers. CORS is open in local
mode so the Vite dev server (http://localhost:5173) can call the API; tighten
this when moving to a shared server.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ecosim import __version__
from ecosim.api.routers import admin, analyses, catalog, sources, spatial, timeseries
from ecosim.core.workspace import NoActiveDataSourceError, get_workspace_registry
from ecosim.ingestion.activation import migrate_legacy_store_if_needed


def create_app() -> FastAPI:
    # basicConfig is a no-op if the root logger already has a handler (e.g.
    # uvicorn's own setup) -- safe to call unconditionally, just makes sure
    # ecosim.activation's INFO-level migration log (see below) is actually
    # visible somewhere rather than silently dropped by Python logging's
    # WARNING-only "handler of last resort".
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    app = FastAPI(title="Ecosim Analysis Platform API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _migrate_store() -> None:
        # One-time, idempotent move from the old single-global-store layout
        # to per-source caching (added 2026-08-28) -- a no-op on every
        # startup after the first. Never fails app startup: a migration
        # problem should surface as "the usual full rescan still works",
        # not "the app won't boot".
        try:
            migrate_legacy_store_if_needed(get_workspace_registry())
        except Exception:  # noqa: BLE001 -- best-effort, must never block startup
            logging.getLogger("ecosim.activation").exception("Legacy store migration failed; continuing without it.")

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    # Any endpoint that touches the canonical store (catalog/timeseries/
    # spatial/analyses) can hit this before a data source is ever activated
    # -- 409 lets the frontend distinguish "point me at a folder first" from
    # a real server error and show the source picker instead of a crash.
    @app.exception_handler(NoActiveDataSourceError)
    def _no_active_source(request: Request, exc: NoActiveDataSourceError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(catalog.router)
    app.include_router(timeseries.router)
    app.include_router(spatial.router)
    app.include_router(analyses.router)
    app.include_router(admin.router)
    app.include_router(sources.router)
    return app


app = create_app()
