"""Readable read errors, the cloud-only pre-scan gate, and unrecognised
raster reporting -- see ecosim/ingestion/file_access.py for the real
2026-09-24 case behind all three (a OneDrive folder whose files were
mostly not downloaded; the scan died with a bare "[Errno 22] Invalid
argument" and would have indexed 0 of its 119,067 unrecognised maps
without a word).

Real cloud placeholders can't be created in a test, so the Windows tests
stand in the READONLY attribute bit (settable with plain ``os.chmod``) for
the cloud-only bits by patching ``_is_cloud_only_attrs`` -- everything
else (``os.scandir``/``os.stat``, attribute reading, counting, messages)
runs for real.
"""

from __future__ import annotations

import os
import stat
import sys

import pytest
from fastapi import HTTPException

from ecosim.api.routers import sources as sources_router
from ecosim.core.config import Settings
from ecosim.core.workspace import WorkspaceRegistry
from ecosim.ingestion import activation, file_access, pipeline
from ecosim.ingestion.activation import ActivationError, activate_source
from ecosim.ingestion.file_access import (
    LocalFilesReport,
    SourceNotLocalError,
    UnreadableFileError,
    check_files_are_local,
    describe_read_error,
    wait_until_local,
)
from ecosim.ingestion.pipeline import IngestCancelled
from ecosim.ingestion.spatial_pipeline import build_raster_index

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="file attributes are Windows-only")

_FILE_ATTRIBUTE_READONLY = 0x1

_HEADER_BLOCK = (
    '"<HEADER ecopath/>"\nModelName,"Test Model"\n'
    '"<HEADER ecosim/>"\nEcosimScenario,test_scenario\nStartYear,1998\n'
    '"<HEADER end/>"\n\n'
)
_CSV_BODY = "Data,Biomass\n\nyear\\group,1,2\n1998,0.01,0.02\n"


@pytest.fixture
def readonly_means_cloud(monkeypatch):
    monkeypatch.setattr(file_access, "_is_cloud_only_attrs", lambda attrs: bool(attrs & _FILE_ATTRIBUTE_READONLY))


def _make_cloud_only(path) -> None:
    os.chmod(path, stat.S_IREAD)


def _write_csv(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEADER_BLOCK + _CSV_BODY, encoding="utf-8")


def test_describe_read_error_names_file_and_reason(tmp_path):
    path = tmp_path / "Sample_00004" / "biomass_annual.csv"
    msg = describe_read_error(OSError(22, "Invalid argument"), path, tmp_path)
    assert "Sample_00004" in msg and "biomass_annual.csv" in msg
    assert "Invalid argument" in msg
    assert "Errno" not in msg


def test_check_files_are_local_passes_for_ordinary_files(tmp_path):
    _write_csv(tmp_path / "run" / "biomass_annual.csv")
    (tmp_path / "run" / "notes.docx").write_text("x")  # not a file the scan reads
    report = check_files_are_local(tmp_path)
    assert report.cloud_only == 0
    assert report.files_checked == 1


@windows_only
def test_check_files_are_local_blocks_on_cloud_only_files(tmp_path, readonly_means_cloud):
    _write_csv(tmp_path / "a" / "biomass_annual.csv")
    _write_csv(tmp_path / "b" / "biomass_annual.csv")
    asc = tmp_path / "b" / "EcospaceMapBiomass-Cod-00001.asc"
    asc.write_text("ncols 1\n")
    _make_cloud_only(tmp_path / "b" / "biomass_annual.csv")
    _make_cloud_only(asc)

    with pytest.raises(SourceNotLocalError) as info:
        check_files_are_local(tmp_path)
    msg = str(info.value)
    assert "1 of 2 CSV files" in msg
    assert "1 of 1 ASC map files" in msg
    assert "Always keep on this device" in msg
    assert tmp_path.name in msg


@windows_only
def test_describe_read_error_explains_cloud_only_file(tmp_path, readonly_means_cloud):
    path = tmp_path / "biomass_annual.csv"
    _write_csv(path)
    _make_cloud_only(path)
    msg = describe_read_error(OSError(22, "Invalid argument"), path, tmp_path)
    assert "stored only online" in msg
    assert "Always keep on this device" in msg


def _broken_read_header(_path):
    raise OSError(22, "Invalid argument")


def test_discovery_stops_with_readable_error_on_unreadable_file(tmp_path, monkeypatch):
    _write_csv(tmp_path / "run" / "biomass_annual.csv")
    monkeypatch.setattr(pipeline, "read_header", _broken_read_header)
    settings = Settings(output_raw_dir=tmp_path, input_raw_dir=None, store_dir=tmp_path / "store")
    with pytest.raises(UnreadableFileError) as info:
        pipeline.run_ingest(settings)
    assert "biomass_annual.csv" in str(info.value)


def test_registration_check_explains_when_nothing_was_readable(tmp_path, monkeypatch):
    _write_csv(tmp_path / "run" / "biomass_annual.csv")
    monkeypatch.setattr(pipeline, "read_header", _broken_read_header)
    problems = pipeline.validate_output_root(tmp_path)
    assert len(problems) == 1
    assert "could not be read" in problems[0]
    assert "biomass_annual.csv" in problems[0]


def test_unrecognised_asc_files_are_counted_not_silently_dropped(tmp_path):
    raw = tmp_path / "raw" / "SSP1_A002"
    raw.mkdir(parents=True)
    for ts in ("0012", "0024"):
        (raw / f"biodiv_ind_Commercial B-{ts}.asc").write_text("ncols 1\n")
    settings = Settings(output_raw_dir=tmp_path / "raw", input_raw_dir=None, store_dir=tmp_path / "store")
    report = build_raster_index(settings)
    assert report.rasters_indexed == 0
    assert report.unrecognized_files == 2
    assert report.unrecognized_examples == ["biodiv_ind_Commercial B-0012.asc", "biodiv_ind_Commercial B-0024.asc"]


def test_scan_warnings_are_recorded_for_unrecognised_maps(tmp_path):
    raw = tmp_path / "raw"
    _write_csv(raw / "run" / "biomass_annual.csv")
    (raw / "run" / "biodiv_ind_Fish B-0012.asc").write_text("ncols 1\n")
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("Calib", raw, "output")
    result = activate_source(registry, source)
    assert len(result.warnings) == 1
    assert "1 .asc map file(s) were not loaded" in result.warnings[0]
    assert "biodiv_ind_Fish B-0012.asc" in result.warnings[0]


@windows_only
def test_activation_fails_upfront_with_clear_message_on_cloud_only_source(tmp_path, readonly_means_cloud):
    raw = tmp_path / "raw"
    _write_csv(raw / "run" / "biomass_annual.csv")
    _make_cloud_only(raw / "run" / "biomass_annual.csv")
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("Calib", raw, "output")

    with pytest.raises(ActivationError, match="stored only online"):
        activate_source(registry, source)
    failed = registry.get(source.id)
    assert failed.status == "error"
    assert "Always keep on this device" in failed.error
    assert "Errno" not in failed.error


# --- "Download and scan" (keep_local) ---------------------------------------


def _report(cloud_bytes: int) -> LocalFilesReport:
    return LocalFilesReport(files_checked=10, cloud_only=1 if cloud_bytes else 0, cloud_only_bytes=cloud_bytes)


def test_keep_local_survives_registry_round_trip(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("Calib", tmp_path, "output", keep_local=True)
    assert registry.get(source.id).keep_local is True
    assert registry.add_source("Plain", tmp_path, "output").keep_local is False


def test_wait_until_local_reports_byte_progress_until_done(tmp_path, monkeypatch):
    remaining = iter([_report(300), _report(100), _report(0)])
    monkeypatch.setattr(file_access, "scan_local_availability", lambda *a, **k: next(remaining))
    seen: list[tuple[int, int]] = []
    assert wait_until_local(tmp_path, on_progress=lambda d, t: seen.append((d, t)), poll_seconds=0)
    assert seen == [(0, 300), (200, 300), (300, 300)]


def test_wait_until_local_gives_up_with_clear_message_when_nothing_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(file_access, "scan_local_availability", lambda *a, **k: _report(300))
    with pytest.raises(SourceNotLocalError, match="has not downloaded anything"):
        wait_until_local(tmp_path, poll_seconds=0, stall_seconds=0)


def _keep_local_source(tmp_path):
    raw = tmp_path / "raw"
    _write_csv(raw / "run" / "biomass_annual.csv")
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    return registry, registry.add_source("Calib", raw, "output", keep_local=True)


def test_keep_local_source_is_downloaded_first_then_scanned(tmp_path, monkeypatch):
    registry, source = _keep_local_source(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(activation, "can_make_local", lambda: True)
    monkeypatch.setattr(activation, "scan_local_availability", lambda *a, **k: _report(500))
    monkeypatch.setattr(activation, "request_keep_local", lambda root: calls.append("pin"))
    monkeypatch.setattr(activation, "wait_until_local", lambda root, **k: calls.append("wait") or True)
    phases: list[str] = []
    result = activate_source(registry, source, on_progress=lambda phase, d, t: phases.append(phase))
    assert calls == ["pin", "wait"]
    assert phases[0] == "downloading"
    assert result.scenarios  # the scan really ran after the download
    assert registry.get(source.id).status == "ok"


def test_cancelling_download_unpins_and_cancels(tmp_path, monkeypatch):
    registry, source = _keep_local_source(tmp_path)
    released: list[bool] = []
    monkeypatch.setattr(activation, "can_make_local", lambda: True)
    monkeypatch.setattr(activation, "scan_local_availability", lambda *a, **k: _report(500))
    monkeypatch.setattr(activation, "request_keep_local", lambda root: None)
    monkeypatch.setattr(activation, "wait_until_local", lambda root, **k: False)
    monkeypatch.setattr(activation, "release_keep_local", lambda root: released.append(True))
    with pytest.raises(IngestCancelled):
        activate_source(registry, source)
    assert released == [True]
    assert registry.get(source.id).status == "unscanned"


@windows_only
def test_adding_a_cloud_only_folder_registers_nothing_and_explains(tmp_path, readonly_means_cloud):
    _write_csv(tmp_path / "raw" / "run" / "biomass_annual.csv")
    _make_cloud_only(tmp_path / "raw" / "run" / "biomass_annual.csv")
    body = sources_router.AddSourceIn(name="Calib", path=str(tmp_path / "raw"), kind="output")
    with pytest.raises(HTTPException) as info:
        sources_router.add_source(body)
    assert info.value.status_code == 409
    assert info.value.detail["code"] == "not_local"
    assert info.value.detail["cloud_only_files"] == 1
    assert sources_router.list_sources() == []


@windows_only
def test_download_and_scan_registration_never_reads_cloud_only_files(tmp_path, readonly_means_cloud, monkeypatch):
    _write_csv(tmp_path / "raw" / "run" / "biomass_annual.csv")
    _make_cloud_only(tmp_path / "raw" / "run" / "biomass_annual.csv")
    monkeypatch.setattr(pipeline, "read_header", _broken_read_header)  # reading would fail the test
    body = sources_router.AddSourceIn(name="Calib", path=str(tmp_path / "raw"), kind="output", keep_local=True)
    out = sources_router.add_source(body)
    assert out.name == "Calib"
