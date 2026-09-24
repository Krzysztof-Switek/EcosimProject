"""Shared pytest fixtures for the backend test suite.

Autouse, per-test isolation of the profile directory: any code path that
goes through ``core.workspace.profile_dir()`` (``get_workspace_registry()``,
``core.config.source_cache_dir``/``Settings()``'s default ``store_dir``, and
therefore all of ``ingestion.activation``'s ``activate_source``/
``rescan_source``/``combine_and_rebuild``/``remove_source_and_rebuild``/
``migrate_legacy_store_if_needed``) honors the ``ECOSIM_CONFIG_DIR`` env var.

Without this fixture, a test that doesn't explicitly override every
``Settings``/``WorkspaceRegistry`` it constructs silently writes into the
REAL ``~/.ecosim`` profile directory. This is not hypothetical: it happened
(2026-08-28) -- synthetic test data from ``test_run_id_detection.py`` and
``test_activation_lock.py`` overwrote the live ``catalog.duckdb``/
``dictionaries/*.csv``/``spatial/raster_index.csv`` for a real, already-
scanned user data source (RU_SSP1), requiring manual recovery (re-deriving
the raster index from raw files; the scenario "label" dimension text was
lost outright, though the actual tidy-row data in Parquet -- the part that
matters for real analysis -- was never touched, since ingestion always
writes to new per-source paths, never overwrites existing ones).

Redirecting ``ECOSIM_CONFIG_DIR`` to a per-test ``tmp_path`` makes this
class of mistake structurally impossible going forward, regardless of which
``Settings``/registry a future test happens to construct -- a test that
DOES explicitly pass its own ``tmp_path``-scoped paths is unaffected (this
fixture only changes what the *default*/unspecified location resolves to).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_ecosim_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOSIM_CONFIG_DIR", str(tmp_path / "ecosim_home"))
