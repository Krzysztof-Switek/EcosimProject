"""FastAPI application factory.

Mounts the catalog, dictionary and time-series routers. CORS is open in local
mode so the Vite dev server (http://localhost:5173) can call the API; tighten
this when moving to a shared server.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ecosim import __version__
from ecosim.api.routers import admin, analyses, catalog, sources, spatial, timeseries
from ecosim.core.workspace import NoActiveDataSourceError


def create_app() -> FastAPI:
    app = FastAPI(title="Ecosim Analysis Platform API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    app.include_router(catalog.dict_router)
    app.include_router(timeseries.router)
    app.include_router(spatial.router)
    app.include_router(analyses.router)
    app.include_router(admin.router)
    app.include_router(sources.router)
    return app


app = create_app()
