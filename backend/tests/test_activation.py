"""Tests for ingestion.activation.activate_source -- in particular the
ordering bug caught while building this feature live: a failed activation
must never leave the broken source "active", or the app would end up
pointed at an empty/broken store instead of falling back to whatever was
working before."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecosim.core.workspace import WorkspaceRegistry
from ecosim.ingestion.activation import ActivationError, activate_source

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "DataEcosim"

pytestmark = pytest.mark.skipif(not RAW.exists(), reason="DataEcosim/ not present")


def test_failed_activation_does_not_replace_the_active_source(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")

    # RAW (DataEcosim/) directly contains both an 'output' subfolder and
    # Mapa_grupy_fleets.xlsx, so it's a valid *output* root as-is.
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
    # And its *registration* must survive too -- keep_only() (which prunes
    # the old same-kind source once a replacement activates successfully,
    # see workspace.py) must never run on a failed attempt, or the good
    # source's name/path would be gone even though it's still "active".
    assert registry.get(good.id) is not None


def test_successful_activation_prunes_the_previous_source_of_the_same_kind(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")

    first = registry.add_source("First", RAW, "output")
    activate_source(registry, first)
    assert registry.active("output").id == first.id

    second = registry.add_source("Second", RAW, "output")
    activate_source(registry, second)

    assert registry.active("output").id == second.id
    assert registry.get(first.id) is None  # pruned now that the new one proved itself
    assert [s.id for s in registry.list_sources(kind="output")] == [second.id]
