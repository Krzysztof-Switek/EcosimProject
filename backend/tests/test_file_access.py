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
import threading

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
    download_files,
    scan_local_availability,
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
    report = check_files_are_local(tmp_path, "output")
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
        check_files_are_local(tmp_path, "output")
    msg = str(info.value)
    assert "1 of 2 CSV files" in msg
    assert "1 of 1 ASC map files" in msg
    assert "Download and scan" in msg


@windows_only
def test_only_files_the_scan_needs_are_counted(tmp_path, readonly_means_cloud):
    # The real folder: 33 GB of maps in a format not supported yet -- those
    # must not count towards "has to be downloaded first".
    run = tmp_path / "run"
    _write_csv(run / "biomass_annual.csv")
    for name in ("biodiv_ind_Fish B-0012.asc", "biodiv_ind_Fish B-0012.prj", "notes.docx"):
        (run / name).write_text("x")
        _make_cloud_only(run / name)
    _make_cloud_only(run / "biomass_annual.csv")

    report = scan_local_availability(tmp_path, "output")
    assert report.files_checked == 1
    assert [p.name for p, _ in report.missing] == ["biomass_annual.csv"]

    # An input source only ever reads trend_*.csv -- other CSVs don't count.
    assert scan_local_availability(tmp_path, "input").files_checked == 0


@windows_only
def test_describe_read_error_explains_cloud_only_file(tmp_path, readonly_means_cloud):
    path = tmp_path / "biomass_annual.csv"
    _write_csv(path)
    _make_cloud_only(path)
    msg = describe_read_error(OSError(22, "Invalid argument"), path, tmp_path)
    assert "stored only online" in msg
    assert "OneDrive icon" in msg and "Rescan" in msg


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
    assert "Download and scan" in failed.error
    assert "Errno" not in failed.error


# --- "Download and scan" (keep_local) ---------------------------------------


def _report(missing: list) -> LocalFilesReport:
    return LocalFilesReport(
        files_checked=10, cloud_only=len(missing),
        cloud_only_bytes=sum(size for _, size in missing), missing=missing,
    )


def test_keep_local_survives_registry_round_trip(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    source = registry.add_source("Calib", tmp_path, "output", keep_local=True)
    assert registry.get(source.id).keep_local is True
    assert registry.add_source("Plain", tmp_path, "output").keep_local is False


def test_download_files_reads_every_file_and_reports_byte_progress(tmp_path):
    files = []
    for i, size in enumerate((100, 250, 50)):
        p = tmp_path / f"f{i}.csv"
        p.write_bytes(b"x" * size)
        files.append((p, size))
    seen: list[tuple[int, int]] = []
    assert download_files(files, tmp_path, on_progress=lambda d, t: seen.append((d, t)), workers=1)
    assert seen[0] == (0, 400) and seen[-1] == (400, 400)
    assert len(seen) == 4  # start + one per file


def test_download_files_names_the_file_that_failed(tmp_path, monkeypatch):
    bad = tmp_path / "Sample_00004" / "predation_detritus_monthly.csv"

    def fail(path):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(file_access, "_download_one", fail)
    with pytest.raises(SourceNotLocalError) as info:
        download_files([(bad, 10)], tmp_path)
    assert "1 of 1 files could not be downloaded" in str(info.value)
    assert "predation_detritus_monthly.csv" in str(info.value)


def test_download_files_stops_when_cancelled(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(b"x")
    cancel = threading.Event()
    cancel.set()
    assert download_files([(p, 1)], tmp_path, cancel_event=cancel) is False


def _keep_local_source(tmp_path):
    raw = tmp_path / "raw"
    _write_csv(raw / "run" / "biomass_annual.csv")
    registry = WorkspaceRegistry(tmp_path / "config" / "workspaces.json")
    return registry, registry.add_source("Calib", raw, "output", keep_local=True)


def test_keep_local_source_is_downloaded_first_then_scanned(tmp_path, monkeypatch):
    registry, source = _keep_local_source(tmp_path)
    missing = [(source.path / "run" / "biomass_annual.csv", 500)]
    downloaded: list = []

    def fake_download(files, root, on_progress=None, cancel_event=None, on_pause=None):
        downloaded.extend(files)
        on_progress(200, 500)
        on_pause(True)
        on_pause(False)
        on_progress(500, 500)
        return True

    monkeypatch.setattr(activation, "can_make_local", lambda: True)
    monkeypatch.setattr(activation, "sync_client_not_running", lambda root: None)
    monkeypatch.setattr(activation, "scan_local_availability", lambda *a, **k: _report(missing))
    monkeypatch.setattr(activation, "download_files", fake_download)
    seen: list[tuple] = []
    result = activate_source(registry, source, on_progress=lambda phase, d, t: seen.append((phase, d, t)))
    assert downloaded == missing
    assert seen[:4] == [
        ("downloading", 200, 500),
        ("download_paused", 200, 500),  # a pause is reported with the bytes so far
        ("downloading", 200, 500),
        ("downloading", 500, 500),
    ]
    assert result.scenarios  # the scan really ran after the download
    assert registry.get(source.id).status == "ok"


def test_download_refused_up_front_when_onedrive_is_not_running(tmp_path, monkeypatch):
    registry, source = _keep_local_source(tmp_path)
    monkeypatch.setattr(activation, "can_make_local", lambda: True)
    monkeypatch.setattr(activation, "sync_client_not_running", lambda root: "OneDrive")
    monkeypatch.setattr(activation, "scan_local_availability", lambda *a, **k: _report([(source.path, 500)]))
    monkeypatch.setattr(activation, "download_files", lambda *a, **k: pytest.fail("must not start downloading"))
    with pytest.raises(ActivationError) as info:
        activate_source(registry, source)
    assert "OneDrive isn't running" in str(info.value)


def test_sync_client_check_only_applies_inside_onedrive_folders(tmp_path, monkeypatch):
    onedrive = tmp_path / "OneDrive - Org"
    (onedrive / "data").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    for name in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OneDriveCommercial", str(onedrive))
    monkeypatch.setattr(file_access, "can_make_local", lambda: True)
    monkeypatch.setattr(file_access, "_process_running", lambda image: False)
    assert file_access.sync_client_not_running(onedrive / "data") == "OneDrive"
    assert file_access.sync_client_not_running(tmp_path / "elsewhere") is None
    monkeypatch.setattr(file_access, "_process_running", lambda image: True)
    assert file_access.sync_client_not_running(onedrive / "data") is None


@pytest.fixture
def fast_outage(monkeypatch):
    monkeypatch.setattr(file_access, "_OUTAGE_AFTER_FAILURES", 3)
    monkeypatch.setattr(file_access, "_OUTAGE_RETRY_SECONDS", 0.01)


def test_download_waits_out_a_sync_app_outage(tmp_path, monkeypatch, fast_outage):
    # The real case: OneDrive updated itself mid-download and every read
    # failed for ~10 minutes. Nothing may be given up on during that time.
    files = [(tmp_path / f"f{i}.csv", 10) for i in range(10)]
    calls = {"n": 0}
    lock = threading.Lock()

    def flaky(path):
        with lock:
            calls["n"] += 1
            n = calls["n"]
        if 2 <= n <= 30:  # the outage: a long run of failures
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(file_access, "_download_one", flaky)
    pauses: list[bool] = []
    assert download_files(files, tmp_path, workers=1, on_pause=pauses.append) is True
    assert pauses == [True, False]


def test_download_gives_up_when_the_outage_lasts_too_long(tmp_path, monkeypatch, fast_outage):
    monkeypatch.setattr(file_access, "_OUTAGE_MAX_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(file_access, "sync_client_not_running", lambda root: None)

    def down(path):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(file_access, "_download_one", down)
    files = [(tmp_path / f"f{i}.csv", 10) for i in range(50)]
    with pytest.raises(SourceNotLocalError) as info:
        download_files(files, tmp_path, workers=4)
    assert "did not recover" in str(info.value)


def test_files_that_failed_before_an_outage_was_noticed_are_retried(tmp_path, monkeypatch, fast_outage):
    failing = {tmp_path / "early.csv"}
    calls: dict = {}

    def first_two_reads_fail(path):
        calls[path] = calls.get(path, 0) + 1
        if path in failing and calls[path] <= 2:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr(file_access, "_download_one", first_two_reads_fail)
    files = [(tmp_path / "early.csv", 1), (tmp_path / "later.csv", 1)]
    assert download_files(files, tmp_path, workers=1) is True
    assert calls[tmp_path / "early.csv"] == 3  # two quick attempts + the final retry pass


def test_cancelling_download_cancels_the_scan(tmp_path, monkeypatch):
    registry, source = _keep_local_source(tmp_path)
    monkeypatch.setattr(activation, "can_make_local", lambda: True)
    monkeypatch.setattr(activation, "sync_client_not_running", lambda root: None)
    monkeypatch.setattr(activation, "scan_local_availability", lambda *a, **k: _report([(source.path, 500)]))
    monkeypatch.setattr(activation, "download_files", lambda *a, **k: False)
    with pytest.raises(IngestCancelled):
        activate_source(registry, source)
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
