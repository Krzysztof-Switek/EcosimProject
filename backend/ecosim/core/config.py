"""Central configuration: filesystem layout of raw source and canonical store.

``output_raw_dir``/``input_raw_dir`` come from whichever data sources are
currently *active* in the workspace registry (``core/workspace.py``) --
model output (Ecosim/Ecospace results) and model input (driver grids) are
two independently-selected sources, not subfolders of one shared root, since
they may come from different places at different times. Output is
mandatory (models/scenarios/groups all derive from it); input is optional.
Pointing the app at a new export is a runtime action through the API/UI, not
an environment variable + restart. See
``docs/Plans and TO_DO lists/27.08_data_upload_PLAN.md``.

``Settings`` itself stays a plain, explicitly-constructible value object --
tests and scripts still build it directly
(``Settings(output_raw_dir=..., input_raw_dir=..., store_dir=...)``); only
``get_settings()``, the thing routers/CLI actually call, resolves the active
workspace sources.

The canonical store is a single, always-freshly-rebuilt location (not
namespaced per source) -- switching which source is active always re-runs
ingestion (same cost as today's "Reload Data"), in exchange for there being
exactly one store directory ever, never a growing pile of per-combination
caches to clean up.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ecosim.core.workspace import DataSource, NoActiveDataSourceError, get_workspace_registry

# backend/ecosim/core/config.py -> project root is three parents up.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings for the currently active output/input data sources.
    Field names map to ``ECOSIM_<FIELD>`` env vars when constructed bare
    (ad-hoc scripts, tests) -- ``get_settings()`` below overrides them
    explicitly per the active workspace sources instead of relying on env
    vars."""

    model_config = SettingsConfigDict(env_prefix="ECOSIM_", env_file=".env", extra="ignore")

    project_root: Path = _PROJECT_ROOT

    # Immutable raw sources delivered by the modellers. Output is where
    # models/scenarios/groups/scenario CSVs and Ecospace .asc maps live;
    # input is the (optional) driver/forcing-grid export. These field
    # defaults (None) only apply when Settings() is constructed directly;
    # get_settings() always overrides them with the active workspace sources.
    output_raw_dir: Path | None = None
    input_raw_dir: Path | None = None

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

    @property
    def analyses_dir(self) -> Path:
        """Where R analysis plugins live: one folder per analysis, each with
        ``analysis.yaml`` + an entry script. Source-controlled, not regenerated."""
        return self.project_root / "rkit" / "analyses"

    @property
    def ecosimkit_path(self) -> Path:
        return self.project_root / "rkit" / "R" / "ecosimkit.R"

    def ensure_dirs(self) -> None:
        for path in (
            self.timeseries_dir,
            self.spatial_dir,
            self.dictionaries_dir,
            self.catalog_db.parent,
            self.jobs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def settings_for_sources(output: DataSource, input_source: DataSource | None) -> Settings:
    return Settings(output_raw_dir=output.path, input_raw_dir=input_source.path if input_source else None)


def get_settings() -> Settings:
    """Settings for the currently active output (+ optional input) data
    source.

    Deliberately not cached: switching the active source (via the API/CLI)
    must be visible on the very next call, and construction is cheap (a JSON
    read + path joins, no I/O beyond that). Raises ``NoActiveDataSourceError``
    if no *output* source is active yet -- the API turns this into HTTP 409
    (see ``api/app.py``) so the frontend shows the source picker instead of a
    broken, empty catalog. Input alone, without output, is not enough to
    resolve settings: there is nothing to build a catalog from.
    """
    registry = get_workspace_registry()
    output = registry.active("output")
    if output is None:
        raise NoActiveDataSourceError(
            "No active model output data source. Register one via "
            "POST /admin/sources (kind=output) and activate it, or run "
            "`ecosim sources add`/`ecosim sources activate`."
        )
    return settings_for_sources(output, registry.active("input"))
