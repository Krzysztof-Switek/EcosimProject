"""Raw-file readability: cloud-only (not-downloaded) file detection, getting
the files a scan needs onto this computer, and human-readable read errors.

Why this exists (real case, 2026-09-24): a user pointed a source at a
~48 GB OneDrive folder in which 99% of the files were "Files On-Demand"
placeholders -- listed by the filesystem, but with no content on disk.
Reading one makes Windows download it on the spot; when that download
failed, Windows reported ERROR_CLOUD_FILE_UNSUCCESSFUL (0x80070185, "The
cloud operation was unsuccessful"), which reaches Python via the C
runtime's ``read()`` as a bare ``OSError(22, 'Invalid argument')`` -- no
``winerror``, no filename. The scan died after 581 files with exactly
that text shown in the UI, telling the user nothing.

The reliable signal is the file's own attributes, not the error code:
Windows marks every cloud placeholder with FILE_ATTRIBUTE_RECALL_ON_DATA_
ACCESS / RECALL_ON_OPEN (OFFLINE on older providers). That is the Windows
Cloud Files API every sync client implements (OneDrive, Dropbox, Google
Drive, ...), so this isn't OneDrive-specific. Reading it needs no file
content at all, so the whole check stays cheap even for hundreds of
thousands of files. On non-Windows platforms ``st_file_attributes`` doesn't
exist -- everything below simply reports "all local" there.

Only the files a scan actually needs are considered (``_is_needed``): every
CSV the discovery reads, ``Ecospace RunInfo.txt``, and ``.asc`` maps whose
names this app recognises. The same real folder held 33 GB of map files in
a format not supported yet -- counting those would have demanded a 44 GB
download for an 11 GB scan.

Downloading (``download_files``) is done by the app itself: reading a
placeholder makes Windows fetch it on the spot, and a pool of readers keeps
many requests in flight. The first version instead pinned the whole folder
(Explorer's "Always keep on this device") and waited for OneDrive -- on the
real folder OneDrive then spent 20+ minutes producing gigabytes of logs
without downloading a single file, while on-demand reads of the same files
succeeded at once. Each downloaded file is pinned individually afterwards so
OneDrive doesn't free it again.

The sync app can disappear mid-download (real case, 2026-09-25: OneDrive
auto-updated itself at 01:44-01:54 UTC, five hours into an 11 GB download).
While it is gone every read fails instantly, so without care the remaining
queue -- 15,455 files that time -- fails within minutes. ``download_files``
therefore treats a run of failures with no success in between as an outage
and waits for the sync app to come back (``_OutageGate``), and the download
refuses to start at all when the folder's sync app isn't running
(``sync_client_not_running``). This is desktop-Windows only by nature
(``can_make_local()``): a server (Linux/Docker) reads ordinary files from a
mounted share and never gets here.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from ecosim.ingestion.parsers.asc_grid import parse_input_filename, parse_output_filename

# Win32 file attribute bits (winnt.h). Not all exposed by ``stat`` on every
# Python version, so spelled out here.
_FILE_ATTRIBUTE_OFFLINE = 0x0000_1000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x0004_0000
_FILE_ATTRIBUTE_PINNED = 0x0008_0000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x0040_0000
_CLOUD_ONLY_MASK = (
    _FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_OPEN | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)
# Attributes SetFileAttributesW accepts back (read-only, hidden, system,
# archive, temporary, offline, not-content-indexed) -- the rest (reparse
# point, recall flags) are read-only state owned by the filesystem.
_SETTABLE_MASK = 0x0000_3127

# Measured on the real OneDrive folder (2026-09-24): on-demand downloads are
# limited per file by the sync app, not by bandwidth -- ~10 files/s with 64
# concurrent readers, ~6 files/s with 16. Used for the up-front estimate
# only, never to decide anything.
_DOWNLOAD_WORKERS = 64
_EST_FILES_PER_SECOND = 10

# Outage handling (see the module docstring): this many failed reads in a
# row, with no success in between, means the sync app itself is down rather
# than a few files being broken. Then every reader retries every
# _OUTAGE_RETRY_SECONDS, and the download gives up only after
# _OUTAGE_MAX_WAIT_SECONDS without recovering. The real outage (an
# OneDrive self-update) lasted ~10 minutes.
_OUTAGE_AFTER_FAILURES = 20
_OUTAGE_RETRY_SECONDS = 15
_OUTAGE_MAX_WAIT_SECONDS = 20 * 60

_ONEDRIVE_HINT = (
    "Check the OneDrive icon in the taskbar (syncing may be paused, signed out or "
    "reporting an error), then click Rescan to try again -- files already downloaded are kept."
)

SourceKind = Literal["output", "input"]


class UnreadableFileError(RuntimeError):
    """A raw file the scan needs could not be read. The message is already
    human-readable (names the file and the cause) -- callers surface
    ``str(exc)`` straight to the UI."""


class SourceNotLocalError(RuntimeError):
    """Files the scan needs exist only in the cloud (or could not be
    downloaded). Raised *before* any ingestion starts."""


def _is_cloud_only_attrs(attrs: int) -> bool:
    return bool(attrs & _CLOUD_ONLY_MASK)


def is_cloud_only(path: Path) -> bool:
    try:
        attrs = getattr(os.stat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return _is_cloud_only_attrs(attrs)


def can_make_local() -> bool:
    """Whether this machine can fetch cloud-only placeholders (Windows Cloud
    Files). False on a Linux server."""
    return sys.platform == "win32"


def _onedrive_roots() -> list[Path]:
    # Set by the OneDrive client for each signed-in account (work/school and
    # personal); the same variables Explorer uses to place the OneDrive folders.
    names = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
    return [Path(os.environ[n]) for n in names if os.environ.get(n)]


def _process_running(image_name: str) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace", timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # can't tell -- don't block on it
    # A match prints a CSV row with the image name; no match prints a
    # localised "INFO: ..." line, so look for the name only.
    return f'"{image_name.lower()}"' in out.lower()


def sync_client_not_running(root: Path) -> str | None:
    """The name of the sync app that serves ``root`` ("OneDrive") if that app
    isn't running on this computer, else None. Without it no cloud-only file
    can be downloaded, so a download would fail on every single file. Only
    OneDrive is recognised (the folder lies under one of its roots); for any
    other location this returns None and downloading just proceeds."""
    if not can_make_local():
        return None
    try:
        resolved = root.resolve()
    except OSError:
        return None
    for od_root in _onedrive_roots():
        try:
            resolved.relative_to(od_root.resolve())
        except (OSError, ValueError):
            continue
        return None if _process_running("OneDrive.exe") else "OneDrive"
    return None


def sync_client_not_running_message(client: str) -> str:
    return (
        f"{client} isn't running on this computer, so the files that are stored only online "
        f"can't be downloaded. Start {client} (Start menu > {client}), wait until its taskbar "
        "icon shows it is signed in and syncing, then click Rescan -- files already downloaded are kept."
    )


def describe_read_error(exc: Exception, path: Path, root: Path | None = None) -> str:
    """Turn a raw error from reading ``path`` into a message a user can act
    on: which file, and what actually went wrong. Usually an ``OSError``,
    but any exception is accepted -- rasterio, for one, wraps read failures
    in its own types. ``root`` (the source folder), when given, shortens the
    path shown."""
    shown = path
    if root is not None:
        try:
            shown = path.relative_to(root)
        except ValueError:
            pass
    if is_cloud_only(path):
        return (
            f"Could not read \"{shown}\": the file is stored only online (e.g. OneDrive "
            f"\"Files On-Demand\") and Windows could not download it. {_ONEDRIVE_HINT}"
        )
    reason = getattr(exc, "strerror", None) or str(exc)
    code = f" (Windows error {exc.winerror})" if getattr(exc, "winerror", None) else ""
    return f"Could not read \"{shown}\": {reason}{code}."


def _is_needed(name: str, parent_name: str, kind: SourceKind) -> bool:
    """Whether a scan of a ``kind`` source reads this file (now, or at map
    display time for rasters). Mirrors discovery in pipeline.py /
    spatial_pipeline.py: output reads every ``.csv`` (the header decides),
    input only ``trend_*.csv``; ``.asc`` only when the filename is a
    recognised map."""
    lower = name.lower()
    if kind == "output":
        if lower.endswith(".csv") or name == "Ecospace RunInfo.txt":
            return True
        return lower.endswith(".asc") and parse_output_filename(name, start_year=1998) is not None
    if lower.startswith("trend_") and lower.endswith(".csv"):
        return True
    return lower.endswith(".asc") and parse_input_filename(name, driver=parent_name) is not None


@dataclass
class LocalFilesReport:
    files_checked: int = 0
    cloud_only: int = 0
    cloud_only_bytes: int = 0
    # suffix -> [cloud_only, total], for the per-type breakdown in messages
    by_suffix: dict[str, list[int]] = field(default_factory=dict)
    # (path, size) of every needed file not on this computer yet
    missing: list[tuple[Path, int]] = field(default_factory=list)

    @property
    def estimated_download_seconds(self) -> int:
        return round(self.cloud_only / _EST_FILES_PER_SECOND)


def scan_local_availability(
    root: Path,
    kind: SourceKind,
    on_progress: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
    progress_every: int = 2000,
) -> LocalFilesReport:
    """Walk ``root`` and find which of the files a ``kind`` scan needs are
    cloud-only. Attributes only -- never opens a file, so it never triggers
    a download itself. ``os.scandir`` on Windows returns attributes straight
    from the directory listing (no extra per-file syscall), which is what
    keeps this fast on very large trees (~5 s for ~160k files). When
    ``cancel_event`` is set this just returns early -- raising
    ``IngestCancelled`` is left to the caller, which checks the event again
    (keeps this module free of pipeline imports)."""
    report = LocalFilesReport()
    stack = [root]
    while stack:
        if cancel_event is not None and cancel_event.is_set():
            return report
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue  # unlistable subfolder: discovery will skip it the same way
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                    continue
                if not _is_needed(entry.name, current.name, kind):
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            report.files_checked += 1
            counts = report.by_suffix.setdefault(os.path.splitext(entry.name)[1].lower(), [0, 0])
            counts[1] += 1
            if _is_cloud_only_attrs(getattr(st, "st_file_attributes", 0)):
                report.cloud_only += 1
                report.cloud_only_bytes += st.st_size
                report.missing.append((Path(entry.path), st.st_size))
                counts[0] += 1
            if on_progress is not None and report.files_checked % progress_every == 0:
                on_progress(report.files_checked)
    if on_progress is not None:
        on_progress(report.files_checked)
    return report


_SUFFIX_LABEL = {".csv": "CSV files", ".asc": "ASC map files", ".txt": "text files"}


def format_gb(n_bytes: int) -> str:
    # 1024-based, like File Explorer and the frontend's formatBytes -- so the
    # size quoted here matches what the user sees in the folder's Properties.
    gb = n_bytes / 1024**3
    return f"{gb:.1f} GB" if gb >= 0.1 else f"{n_bytes / 1024**2:.0f} MB"


def cloud_only_message(report: LocalFilesReport) -> str:
    parts = [
        f"{cloud:,} of {total:,} {_SUFFIX_LABEL.get(suffix, suffix + ' files')}"
        for suffix, (cloud, total) in sorted(report.by_suffix.items())
        if cloud
    ]
    listed = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
    return (
        f"{listed} this scan needs ({format_gb(report.cloud_only_bytes)}) are stored only online "
        "(e.g. OneDrive \"Files On-Demand\") and are not on this computer, so nothing was loaded. "
        "Add the folder again under \"Browse for a folder\" and choose \"Download and scan\"."
    )


def check_files_are_local(
    root: Path,
    kind: SourceKind,
    on_progress: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> LocalFilesReport:
    """Pre-scan gate: raise ``SourceNotLocalError`` if any file the scan
    needs exists only in the cloud. Deliberately blocks rather than letting
    the scan trigger downloads file by file: a full scan would silently
    pull gigabytes, and one failed download mid-way leaves a half-read Monte
    Carlo ensemble -- neither is something to find out an hour in. (A
    source the user agreed to download goes through ``download_files``
    first, see activation._download_to_this_computer.)"""
    report = scan_local_availability(root, kind, on_progress, cancel_event)
    if report.cloud_only:
        raise SourceNotLocalError(cloud_only_message(report))
    return report


if sys.platform == "win32":
    _SetFileAttributesW = ctypes.windll.kernel32.SetFileAttributesW
    _SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    _SetFileAttributesW.restype = ctypes.c_int


def _pin(path: Path) -> None:
    """Mark one already-downloaded file "always keep on this device" so the
    sync app doesn't free it again (the UNPINNED bit, 0x100000, is dropped
    by construction -- it isn't in the settable mask). Best-effort: if it fails, the worst case
    is a later scan finding it cloud-only again and saying so."""
    if not can_make_local():
        return
    try:
        attrs = os.stat(path).st_file_attributes
    except OSError:
        return
    _SetFileAttributesW(str(path), (attrs & _SETTABLE_MASK) | _FILE_ATTRIBUTE_PINNED)


def _download_one(path: Path) -> None:
    """Read the whole file once -- for a cloud placeholder that is what makes
    Windows download it -- then pin it."""
    with open(path, "rb") as fh:
        while fh.read(1 << 20):
            pass
    _pin(path)


class _OutageGate:
    """Shared by all download workers: tells a failure that is the file's own
    problem apart from the sync app being gone. ``_OUTAGE_AFTER_FAILURES``
    failures in a row with no success in between open an outage; while it
    is open, failing workers wait and retry instead of giving up; the first
    success closes it. ``timed_out`` once it has stayed open for
    ``_OUTAGE_MAX_WAIT_SECONDS``. ``on_pause(True/False)`` fires on each
    open/close."""

    def __init__(self, on_pause: Callable[[bool], None] | None) -> None:
        self._lock = threading.Lock()
        self._in_a_row = 0
        self._since: float | None = None
        self._on_pause = on_pause

    def success(self) -> None:
        with self._lock:
            self._in_a_row = 0
            if self._since is not None:
                self._since = None
                if self._on_pause is not None:
                    self._on_pause(False)

    def failure(self) -> None:
        with self._lock:
            self._in_a_row += 1
            if self._since is None and self._in_a_row >= _OUTAGE_AFTER_FAILURES:
                self._since = time.monotonic()
                if self._on_pause is not None:
                    self._on_pause(True)

    @property
    def open(self) -> bool:
        return self._since is not None

    @property
    def timed_out(self) -> bool:
        since = self._since
        return since is not None and time.monotonic() - since >= _OUTAGE_MAX_WAIT_SECONDS


def download_files(
    files: list[tuple[Path, int]],
    root: Path,
    on_progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    workers: int = _DOWNLOAD_WORKERS,
    on_pause: Callable[[bool], None] | None = None,
) -> bool:
    """Download ``files`` ((path, size) pairs, e.g. ``LocalFilesReport.
    missing``) onto this computer, reporting ``on_progress(bytes_done,
    bytes_total)`` after every file. Returns False if ``cancel_event`` was
    set (files already downloaded stay, so a later attempt only fetches the
    rest).

    A file that fails is retried at once, and once more at the very end. If
    the sync app stops serving files altogether (see ``_OutageGate``), the
    download pauses -- ``on_pause(True)``, then ``on_pause(False)`` when
    files arrive again -- and gives up after ``_OUTAGE_MAX_WAIT_SECONDS``.
    Raises ``SourceNotLocalError`` naming the first failure if any file
    could not be downloaded, or saying the sync app never came back."""
    total = sum(size for _, size in files)
    done = 0
    failed: list[tuple[Path, int, str]] = []
    lock = threading.Lock()
    gate = _OutageGate(on_pause)
    abandoned = threading.Event()  # the outage outlasted _OUTAGE_MAX_WAIT_SECONDS

    def stopped() -> bool:
        return abandoned.is_set() or (cancel_event is not None and cancel_event.is_set())

    def wait_for_recovery() -> None:
        if cancel_event is not None:
            cancel_event.wait(_OUTAGE_RETRY_SECONDS)
        else:
            time.sleep(_OUTAGE_RETRY_SECONDS)

    def one(path: Path, size: int) -> None:
        nonlocal done
        attempts = 0
        while not stopped():
            try:
                _download_one(path)
            except OSError as exc:
                gate.failure()
                if gate.timed_out:
                    abandoned.set()
                    return
                if gate.open:
                    wait_for_recovery()  # attempts during an outage don't count
                    continue
                attempts += 1
                if attempts < 2:
                    continue
                with lock:
                    failed.append((path, size, describe_read_error(exc, path, root)))
                return
            gate.success()
            with lock:
                done += size
                if on_progress is not None:
                    on_progress(done, total)
            return

    def run(batch: list[tuple[Path, int]]) -> None:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in [pool.submit(one, path, size) for path, size in batch]:
                future.result()

    if on_progress is not None:
        on_progress(0, total)
    run(files)
    # Files that failed just before an outage was recognised (or while one
    # was ending) get one more chance now that downloads work again.
    if failed and not stopped():
        retry = [(path, size) for path, size, _ in failed]
        failed.clear()
        run(retry)
    if cancel_event is not None and cancel_event.is_set():
        return False
    if abandoned.is_set():
        minutes = round(_OUTAGE_MAX_WAIT_SECONDS / 60)
        client = sync_client_not_running(root)
        cause = (
            sync_client_not_running_message(client) if client
            else f"Downloads from OneDrive stopped working and did not recover within {minutes} minutes. "
            f"{_ONEDRIVE_HINT}"
        )
        raise SourceNotLocalError(f"{cause} ({format_gb(done)} of {format_gb(total)} downloaded so far.)")
    if failed:
        raise SourceNotLocalError(
            f"{len(failed):,} of {len(files):,} files could not be downloaded from OneDrive. "
            f"First: {failed[0][2]}"
        )
    return True
