"""Central configuration: filesystem layout of raw source and canonical store.

All paths are derived from the project root so the platform works the same
on a developer laptop (local mode) and later on a shared server. Override any
path with an ``ECOSIM_*`` environment variable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ecosim/core/config.py -> project root is three parents up.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings. Field names map to ``ECOSIM_<FIELD>`` env vars."""

    model_config = SettingsConfigDict(env_prefix="ECOSIM_", env_file=".env", extra="ignore")

    project_root: Path = _PROJECT_ROOT

    # Immutable raw source delivered by the modellers.
    raw_dir: Path = Field(default=_PROJECT_ROOT / "DataEcosim")

    # Canonical, regenerable store produced by the ingestion pipeline.
    store_dir: Path = Field(default=_PROJECT_ROOT / "data")

    @property
    def timeseries_dir(self) -> Path:
        return self.store_dir / "timeseries"

    @property
    def spatial_dir(self) -> Path:
        return self.store_dir / "spatial"

    @property
    def dictionaries_dir(self) -> Path:
        return self.store_dir / "dictionaries"

    @property
    def catalog_db(self) -> Path:
        return self.store_dir / "catalog" / "catalog.duckdb"

    @property
    def jobs_dir(self) -> Path:
        return self.store_dir / "jobs"

    def ensure_dirs(self) -> None:
        for path in (
            self.timeseries_dir,
            self.spatial_dir,
            self.dictionaries_dir,
            self.catalog_db.parent,
            self.jobs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
