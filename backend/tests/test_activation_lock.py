"""Tests for the activation concurrency lock + cooperative cancel (added
2026-08-28) -- ``get_running_activation``/``request_cancel`` in
``ingestion.activation``. Fully synthetic (monkeypatches ``run_ingest``/
``build_raster_index`` with controllable stand-ins) so it doesn't depend on
any real dataset and runs deterministically instead of racing real I/O.
"""

from __future__ import annotations

import threading
import time

from ecosim.core.workspace import WorkspaceRegistry
from ecosim.ingestion import activation as activation_module
from ecosim.ingestion.pipeline import IngestCancelled, IngestReport
from ecosim.ingestion.spatial_pipeline import SpatialIndexReport

_TIMEOUT = 5.0


def _slow_activation(tmp_path, monkeypatch):
    """Registers one output source and patches activation's ingestion calls
    with stand-ins that block on ``release`` (and observe ``cancel_event``
    the same way the real pipeline does at its checkpoints), so a test can
    deterministically catch it "mid-activation" instead of racing real I/O.
    Returns (registry, source, started, release)."""
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    out_dir = tmp_path / "raw"
    out_dir.mkdir()
    source = registry.add_source("Slow", out_dir, "output")

    started = threading.Event()
    release = threading.Event()

    def fake_run_ingest(settings, on_progress=None, cancel_event=None):
        started.set()
        while not release.is_set():
            if cancel_event is not None and cancel_event.is_set():
                raise IngestCancelled()
            time.sleep(0.01)
        # A non-empty scenario list so activate_source()'s "found literally
        # nothing" guard doesn't fire -- irrelevant to what this test module
        # actually exercises (the lock/cancel primitives, not ingestion
        # correctness -- see test_run_id_detection.py for that).
        return IngestReport(scenarios=[{"id": "fake", "label": "Fake", "domain": "output"}])

    def fake_build_raster_index(settings, on_progress=None, cancel_event=None):
        return SpatialIndexReport()

    monkeypatch.setattr(activation_module, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(activation_module, "build_raster_index", fake_build_raster_index)
    # combine_and_rebuild() (unmocked -- it's cheap, real pandas/CSV work
    # against tmp_path-adjacent per-source dirs) calls build_catalog with a
    # `timeseries_dirs` kwarg now, hence **kwargs here.
    monkeypatch.setattr(activation_module, "build_catalog", lambda *args, **kwargs: None)
    return registry, source, started, release


def test_get_running_activation_reports_the_in_flight_source(tmp_path, monkeypatch):
    registry, source, started, release = _slow_activation(tmp_path, monkeypatch)

    assert activation_module.get_running_activation() is None
    activation_module.start_activation(registry, source)
    assert started.wait(timeout=_TIMEOUT)

    running = activation_module.get_running_activation()
    assert running is not None
    assert running.source_id == source.id
    assert running.status == "running"

    release.set()  # let the background thread finish so it doesn't outlive the test
    deadline = time.time() + _TIMEOUT
    while activation_module.get_activation_progress(source.id).status == "running" and time.time() < deadline:
        time.sleep(0.01)
    assert activation_module.get_activation_progress(source.id).status == "ok"
    assert activation_module.get_running_activation() is None


def test_request_cancel_stops_the_activation_and_leaves_registry_untouched(tmp_path, monkeypatch):
    registry, source, started, release = _slow_activation(tmp_path, monkeypatch)

    activation_module.start_activation(registry, source)
    assert started.wait(timeout=_TIMEOUT)

    assert activation_module.request_cancel(source.id) is True

    deadline = time.time() + _TIMEOUT
    while activation_module.get_activation_progress(source.id).status == "running" and time.time() < deadline:
        time.sleep(0.01)

    progress = activation_module.get_activation_progress(source.id)
    assert progress.status == "cancelled"
    assert activation_module.get_running_activation() is None
    # A cancelled attempt is not a failure: the source's own registry record
    # (status/error) is left exactly as it was before activation started --
    # never flipped to "error", per activate_source()'s IngestCancelled
    # re-raise (see activation.py).
    assert registry.get(source.id).status == "unscanned"
    assert registry.get(source.id).error is None


def test_request_cancel_on_a_finished_or_unknown_source_returns_false(tmp_path, monkeypatch):
    registry, source, started, release = _slow_activation(tmp_path, monkeypatch)
    assert activation_module.request_cancel(source.id) is False  # never started

    activation_module.start_activation(registry, source)
    assert started.wait(timeout=_TIMEOUT)
    release.set()
    deadline = time.time() + _TIMEOUT
    while activation_module.get_activation_progress(source.id).status == "running" and time.time() < deadline:
        time.sleep(0.01)

    assert activation_module.request_cancel(source.id) is False  # already finished
