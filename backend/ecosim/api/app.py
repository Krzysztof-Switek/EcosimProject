"""FastAPI application factory.

Mounts the catalog, dictionary and time-series routers. CORS is open in local
mode so the Vite dev server (http://localhost:5173) can call the API; tighten
this when moving to a shared server.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ecosim import __version__
from ecosim.api.routers import admin, catalog, spatial, timeseries


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

    app.include_router(catalog.router)
    app.include_router(catalog.dict_router)
    app.include_router(timeseries.router)
    app.include_router(spatial.router)
    app.include_router(admin.router)
    return app


app = create_app()
