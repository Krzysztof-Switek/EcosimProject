"""Tests for ingestion.activation.activate_source -- in particular the
ordering bug caught while building this feature live: a failed activation
must never leave the broken source "active", or the app would end up
pointed at an empty/broken store instead of falling back to whatever was
working before."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from ecosim.core.workspace import WorkspaceRegistry
from ecosim.ingestion.activation import ActivationError, activate_source

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "DataEcosim"

pytestmark = pytest.mark.skipif(not RAW.exists(), reason="DataEcosim/ not present")


def test_failed_activation_does_not_replace_the_active_source(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")

    # RAW (DataEcosim/) directly contains an 'output' subfolder with real
    # scenario results, so it's a valid *output* root as-is.
    good = registry.add_source("Good", RAW, "output")
    activate_source(registry, good)
    assert registry.active("output").id == good.id
    assert registry.get(good.id).status == "ok"

    bad_dir = tmp_path / "not_an_ewe_export"
    bad_dir.mkdir()
    bad = registry.add_source("Bad", bad_dir, "output")

    with pytest.raises(ActivationError):
        activate_source(registry, bad)

    # The good source is still the active one -- activation failure must not
    # silently swap the app onto a broken, empty store.
    assert registry.active("output").id == good.id
    assert registry.get(bad.id).status == "error"
    assert registry.get(bad.id).error
    # And its *registration* must survive too -- a failed attempt must never
    # remove the good source's registration, or it would vanish even though
    # it's still "active".
    assert registry.get(good.id) is not None


def test_activate_source_does_not_prune_other_sources(tmp_path):
    # As of 2026-08-28: each source gets its own independently-cached ingest
    # output (see core/config.py's per-source-cache docstring), so the
    # registry keeps every source ever added instead of pruning to one per
    # kind -- switching back to "first" later can reuse its cache instead of
    # a full rescan. See test_activation_cache.py for the cache-hit itself.
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")

    first = registry.add_source("First", RAW, "output")
    activate_source(registry, first)
    assert registry.active("output").id == first.id

    second = registry.add_source("Second", RAW, "output")
    activate_source(registry, second)

    assert registry.active("output").id == second.id
    assert registry.get(first.id) is not None  # NOT pruned
    assert {s.id for s in registry.list_sources(kind="output")} == {first.id, second.id}
