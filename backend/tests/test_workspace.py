"""Tests for the data-source registry (core/workspace.py) and its wiring
into get_settings() (core/config.py) -- see
docs/Plans and TO_DO lists/27.08_data_upload_PLAN.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecosim.core.workspace import NoActiveDataSourceError, WorkspaceRegistry


def _registry(tmp_path: Path) -> WorkspaceRegistry:
    return WorkspaceRegistry(tmp_path / "config" / "workspaces.json")


def test_fresh_registry_has_no_sources_or_active(tmp_path):
    registry = _registry(tmp_path)
    assert registry.list_sources() == []
    assert registry.active("output") is None
    assert registry.active("input") is None


def test_add_source_rejects_nonexistent_path(tmp_path):
    registry = _registry(tmp_path)
    with pytest.raises(ValueError, match="Not a reachable directory"):
        registry.add_source("missing", tmp_path / "does_not_exist", "output")


def test_output_and_input_are_independent_active_slots(tmp_path):
    registry = _registry(tmp_path)
    out_dir = tmp_path / "share" / "out"
    in_dir = tmp_path / "share" / "in"
    out_dir.mkdir(parents=True)
    in_dir.mkdir(parents=True)

    out_source = registry.add_source("Output pkg", out_dir, "output")
    in_source = registry.add_source("Input pkg", in_dir, "input")
    assert registry.active("output") is None  # adding does not activate
    assert registry.active("input") is None

    registry.set_active(out_source.id)
    assert registry.active("output").id == out_source.id
    assert registry.active("input") is None  # unaffected

    registry.set_active(in_source.id)
    assert registry.active("output").id == out_source.id  # still there
    assert registry.active("input").id == in_source.id


def test_add_activate_remove_cycle(tmp_path):
    registry = _registry(tmp_path)
    data_dir = tmp_path / "share" / "my_export"
    data_dir.mkdir(parents=True)

    source = registry.add_source("My export", data_dir, "output")
    assert source.status == "unscanned"
    assert source.kind == "output"

    registry.set_active(source.id)
    assert registry.active("output").id == source.id

    registry.mark_scanned(source.id, ok=True)
    assert registry.get(source.id).status == "ok"

    registry.mark_scanned(source.id, ok=False, error="boom")
    refreshed = registry.get(source.id)
    assert refreshed.status == "error"
    assert refreshed.error == "boom"

    registry.remove_source(source.id)
    assert registry.get(source.id) is None
    assert registry.active("output") is None  # removing the active source clears it


def test_add_source_does_not_replace_by_itself(tmp_path):
    # add_source() alone must NOT prune the previous same-kind source --
    # only keep_only() does that, and only ingestion.activation calls it,
    # only after the new source has actually proven itself. If add_source()
    # pruned eagerly, a failed activation of the new source would have
    # already destroyed the still-working previous one's registration
    # before we even knew activation would fail -- see
    # test_activation.py::test_failed_activation_does_not_replace_the_active_source.
    registry = _registry(tmp_path)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    first = registry.add_source("First", first_dir, "output")
    second = registry.add_source("Second", second_dir, "output")
    assert {s.id for s in registry.list_sources()} == {first.id, second.id}


def test_keep_only_replaces_existing_source_of_the_same_kind(tmp_path):
    # No remembered history/list in the UI any more (removed 27.08 -- "keep
    # it simple" until there's per-user accounts) -- once a new source has
    # activated successfully, ingestion.activation calls keep_only() so the
    # old one doesn't silently accumulate alongside it.
    registry = _registry(tmp_path)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    first = registry.add_source("First", first_dir, "output")
    registry.set_active(first.id)
    second = registry.add_source("Second", second_dir, "output")

    registry.keep_only("output", second.id)

    assert [s.id for s in registry.list_sources()] == [second.id]
    assert registry.get(first.id) is None


def test_keep_only_does_not_disturb_other_kind(tmp_path):
    registry = _registry(tmp_path)
    out_dir = tmp_path / "out"
    in_dir = tmp_path / "in"
    out_dir.mkdir()
    in_dir.mkdir()

    out_source = registry.add_source("Out", out_dir, "output")
    registry.set_active(out_source.id)
    in_source = registry.add_source("In", in_dir, "input")

    registry.keep_only("input", in_source.id)

    assert registry.active("output").id == out_source.id  # untouched
    assert registry.get(out_source.id) is not None  # untouched (different kind)


def test_list_sources_filters_by_kind(tmp_path):
    registry = _registry(tmp_path)
    out_dir = tmp_path / "out"
    in_dir = tmp_path / "in"
    out_dir.mkdir()
    in_dir.mkdir()
    registry.add_source("Output pkg", out_dir, "output")
    registry.add_source("Input pkg", in_dir, "input")

    assert len(registry.list_sources()) == 2
    assert [s.kind for s in registry.list_sources(kind="output")] == ["output"]
    assert [s.kind for s in registry.list_sources(kind="input")] == ["input"]


def test_set_active_rejects_unknown_id(tmp_path):
    registry = _registry(tmp_path)
    with pytest.raises(ValueError, match="Unknown data source"):
        registry.set_active("nope")


def test_get_settings_raises_without_active_output_source(tmp_path, monkeypatch):
    from ecosim.core import config as config_module

    empty_registry = _registry(tmp_path)
    monkeypatch.setattr(config_module, "get_workspace_registry", lambda: empty_registry)

    with pytest.raises(NoActiveDataSourceError):
        config_module.get_settings()


def test_get_settings_resolves_active_output_only(tmp_path, monkeypatch):
    from ecosim.core import config as config_module

    registry = _registry(tmp_path)
    out_dir = tmp_path / "share" / "baltic_2026"
    out_dir.mkdir(parents=True)
    source = registry.add_source("Baltic 2026", out_dir, "output")
    registry.set_active(source.id)
    monkeypatch.setattr(config_module, "get_workspace_registry", lambda: registry)

    settings = config_module.get_settings()
    assert settings.output_raw_dir == out_dir
    assert settings.input_raw_dir is None


def test_get_settings_resolves_both_sources(tmp_path, monkeypatch):
    from ecosim.core import config as config_module

    registry = _registry(tmp_path)
    out_dir = tmp_path / "out"
    in_dir = tmp_path / "in"
    out_dir.mkdir()
    in_dir.mkdir()
    out_source = registry.add_source("Out", out_dir, "output")
    in_source = registry.add_source("In", in_dir, "input")
    registry.set_active(out_source.id)
    registry.set_active(in_source.id)
    monkeypatch.setattr(config_module, "get_workspace_registry", lambda: registry)

    settings = config_module.get_settings()
    assert settings.output_raw_dir == out_dir
    assert settings.input_raw_dir == in_dir
