"""FastAPI application factory.

Mounts the catalog, dictionary and time-series routers. CORS is open in local
mode so the Vite dev server (http://localhost:5173) can call the API; tighten
this when moving to a shared server.
"""

from __future__ import annotations

import logging
import threading

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ecosim import __version__
from ecosim.api.routers import admin, analyses, areas, auth, catalog, regions, sources, spatial, timeseries
from ecosim.core.workspace import NoActiveDataSourceError, get_workspace_registry
from ecosim.ingestion.activation import combine_and_rebuild, migrate_legacy_store_if_needed


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

    # Signing in (core/auth.py): when set up, every call but these needs a
    # session -- including /docs and /openapi.json.
    @app.middleware("http")
    async def _require_session(request: Request, call_next):
        from ecosim.core import auth as auth_core

        if request.method == "OPTIONS" or request.url.path in _OPEN_PATHS or not auth_core.enabled():
            return await call_next(request)
        account = auth.current_account(request)
        if account is None:
            return JSONResponse(status_code=401, content={"detail": "Sign in first."})
        if account.role != "admin" and auth_core.admin_only(request.method, request.url.path):
            return JSONResponse(status_code=403, content={"detail": "Only the administrator can do this."})
        return await call_next(request)

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
        # Rebuild the catalog from the active sources' cached Parquet (no raw
        # files read), so a change in the catalog's own rules -- labels,
        # counts, Results-Extractor categories -- applies without re-activating.
        try:
            combine_and_rebuild(get_workspace_registry())
        except Exception:  # noqa: BLE001 -- best-effort, the previous catalog stays usable
            logging.getLogger("ecosim.activation").exception("Catalog rebuild failed; keeping the previous one.")

    @app.on_event("startup")
    def _identify_models() -> None:
        # Sources identified before identify() learned something new (e.g.
        # Ecopath group names) are identified again -- in the background,
        # since a large Monte Carlo folder takes ~25 s (file headers only,
        # cloud-only files skipped, nothing downloaded).
        from ecosim.ingestion.model_origin import refresh_identification

        threading.Thread(
            target=refresh_identification, args=(get_workspace_registry(),), daemon=True,
            name="identify-models",
        ).start()

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
    app.include_router(regions.router)
    app.include_router(areas.router)
    app.include_router(auth.router)
    return app


_OPEN_PATHS = {"/health", "/auth/status", "/auth/login", "/auth/logout"}


app = create_app()
