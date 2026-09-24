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

Two layers (added 2026-08-28, real trigger: a genuine ~400GB/~1hr source had to
be fully re-ingested just to switch back to it):

* **Per-source cache** -- each registered source gets its own private,
  independently-cached ingest output at ``source_cache_dir(source.id)``
  (``profile_dir()/store/sources/<source_id>/``), built by pointing
  ``settings_for_single_source()`` (only ONE of output/input set) at the
  same ``run_ingest``/``build_raster_index`` used everywhere else. Re-
  activating a source whose cache is still present on disk skips raw-file
  ingestion entirely (see ``ingestion.activation``'s cache-validity check)
  -- this is what makes switching between two already-scanned sources
  instant instead of a full rescan. Never invalidated automatically: only
  an explicit user-triggered Rescan (one source at a time, never "all")
  overwrites a source's own cache slot.
* **Live combined store** -- ``store_dir`` itself (unchanged location/shape
  from before this existed: ``timeseries/``, ``spatial/`` incl. the COG
  cache, ``dictionaries/``, ``catalog/catalog.duckdb``, ``jobs/``) is cheaply
  rebuilt (no raw-file I/O, just small-CSV concatenation + pointing DuckDB
  at a list of per-source Parquet directories) from whichever source(s) are
  currently active, every time activation/rescan/removal changes that set.

That store directory (both the live combined one and each source's cache
slot under it) lives under the active profile's own directory
(``core.workspace.profile_dir()``, default ``~/.ecosim/profiles/default/store``)
-- never inside the project's own code tree. It's generated/derived state
(same status as the workspace registry, not source-controlled), so it
belongs with the user's own data, not bundled with the app.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ecosim.core.workspace import DataSource, NoActiveDataSourceError, get_workspace_registry, profile_dir

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

    # Canonical, regenerable store produced by the ingestion pipeline --
    # lives under the profile directory, not the project root (see module
    # docstring). default_factory (not a plain default) since it must be
    # evaluated per-instantiation, not once at class-definition time.
    store_dir: Path = Field(default_factory=lambda: profile_dir() / "store")

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


def source_cache_dir(source_id: str) -> Path:
    """Where one source's own, independently-cached ingest output lives --
    see this module's docstring's "Per-source cache" note. Pure path
    builder (no registry lookup, no I/O) so it's cheap to call from
    anywhere that just needs to check/build/delete a source's cache slot."""
    return profile_dir() / "store" / "sources" / source_id


def dir_size_bytes(path: Path) -> int:
    """Total size on disk of every file under ``path``, recursively -- used
    to show disk-space usage per source in the "Indexed data" panel (see
    ``api/routers/sources.py::SourceOut.cache_size_bytes``). ``0`` for a
    directory that doesn't exist (a source never scanned yet). Cheap in
    practice: a source's cache holds the already-normalised, aggregated
    output of ingestion (one Parquet file per scenario/domain/variable/freq,
    plus a handful of index/dictionary CSVs) -- dozens of files, not the
    hundreds of thousands a raw source folder can have -- confirmed on a
    real ~400GB source's cache: 46 files, walked in ~64ms. Safe to call
    synchronously per source on every ``GET /admin/sources`` (called
    infrequently -- page load, after an operation finishes -- never in a
    tight poll loop)."""
    if not path.exists():
        return 0
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass  # vanished mid-walk (e.g. a concurrent Remove) -- skip it
    return total


def settings_for_single_source(source: DataSource) -> Settings:
    """Settings for ingesting exactly ONE source in isolation into its own
    cache slot -- only the raw dir matching ``source.kind`` is set, the
    other stays ``None`` (safe: ``run_ingest``/``build_raster_index`` both
    skip a domain whose raw dir is ``None``). Used by
    ``ingestion.activation`` to populate/refresh one source's cache without
    ever touching another source's."""
    store_dir = source_cache_dir(source.id)
    if source.kind == "output":
        return Settings(output_raw_dir=source.path, input_raw_dir=None, store_dir=store_dir)
    return Settings(output_raw_dir=None, input_raw_dir=source.path, store_dir=store_dir)


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
