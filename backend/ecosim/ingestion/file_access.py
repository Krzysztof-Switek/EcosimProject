"""Raw-file readability: cloud-only (not-downloaded) file detection, the
pre-scan check built on it, and human-readable read-error messages.

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
exist -- the checks below simply report "not cloud-only" there.

Getting the files local (``request_keep_local``/``wait_until_local``) is
the same thing as Explorer's "Always keep on this device": set the Pinned
attribute and let the sync app download in its own time, while this module
only watches attributes for progress. That's a desktop-Windows feature by
nature -- on a server (Linux/Docker) there are no placeholders to pin
(``can_make_local()`` is False) and data is expected to arrive as ordinary
files on a mounted share, so none of it ever runs there.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Win32 file attribute bits (winnt.h). Not all exposed by ``stat`` on every
# Python version, so spelled out here.
_FILE_ATTRIBUTE_OFFLINE = 0x0000_1000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x0004_0000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x0040_0000
_CLOUD_ONLY_MASK = (
    _FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_OPEN | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)

# The only raw files either pipeline ever reads: Ecosim/driver CSVs, Ecospace
# .asc grids (read at materialize time) and ``Ecospace RunInfo.txt``.
_SCANNED_SUFFIXES = (".csv", ".asc", ".txt")

_KEEP_LOCAL_HINT = (
    "In File Explorer, right-click the folder \"{folder}\" and choose \"Always keep on this "
    "device\", wait until the sync app has finished downloading (the folder shows a solid "
    "green check mark), then click Rescan."
)


class UnreadableFileError(RuntimeError):
    """A raw file the scan needs could not be read. The message is already
    human-readable (names the file and the cause) -- callers surface
    ``str(exc)`` straight to the UI."""


class SourceNotLocalError(RuntimeError):
    """The pre-scan check found files that exist only in the cloud. Raised
    *before* any ingestion starts -- see ``check_files_are_local``."""


def _is_cloud_only_attrs(attrs: int) -> bool:
    return bool(attrs & _CLOUD_ONLY_MASK)


def is_cloud_only(path: Path) -> bool:
    try:
        attrs = getattr(os.stat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return _is_cloud_only_attrs(attrs)


def describe_read_error(exc: Exception, path: Path, root: Path | None = None) -> str:
    """Turn a raw error from reading ``path`` into a message a user can act
    on: which file, and what actually went wrong. Usually an ``OSError``,
    but any exception is accepted -- rasterio, for one, wraps read failures
    in its own types. ``root`` (the source folder), when given, shortens the
    path shown and names the folder in the fix-it hint."""
    shown = path
    if root is not None:
        try:
            shown = path.relative_to(root)
        except ValueError:
            pass
    if is_cloud_only(path):
        folder = root.name if root is not None else path.parent.name
        return (
            f"Could not read \"{shown}\": the file is stored only online (e.g. OneDrive "
            "\"Files On-Demand\") and Windows could not download it. "
            + _KEEP_LOCAL_HINT.format(folder=folder)
        )
    reason = getattr(exc, "strerror", None) or str(exc)
    code = f" (Windows error {exc.winerror})" if getattr(exc, "winerror", None) else ""
    return f"Could not read \"{shown}\": {reason}{code}."


@dataclass
class LocalFilesReport:
    files_checked: int = 0
    cloud_only: int = 0
    cloud_only_bytes: int = 0
    # suffix -> (cloud_only, total), for the per-type breakdown in the message
    by_suffix: dict[str, list[int]] = field(default_factory=dict)


def scan_local_availability(
    root: Path,
    on_progress: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
    progress_every: int = 2000,
) -> LocalFilesReport:
    """Walk ``root`` and count which of the files a scan would read are
    cloud-only. Attributes only -- never opens a file, so it never triggers
    a download itself. ``os.scandir`` on Windows returns attributes straight
    from the directory listing (no extra per-file syscall), which is what
    keeps this fast on very large trees. When ``cancel_event`` is set this
    just returns early -- raising ``IngestCancelled`` is left to the caller,
    which checks the event again (keeps this module free of pipeline
    imports)."""
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
                suffix = os.path.splitext(entry.name)[1].lower()
                if suffix not in _SCANNED_SUFFIXES:
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            report.files_checked += 1
            counts = report.by_suffix.setdefault(suffix, [0, 0])
            counts[1] += 1
            if _is_cloud_only_attrs(getattr(st, "st_file_attributes", 0)):
                report.cloud_only += 1
                report.cloud_only_bytes += st.st_size
                counts[0] += 1
            if on_progress is not None and report.files_checked % progress_every == 0:
                on_progress(report.files_checked)
    if on_progress is not None:
        on_progress(report.files_checked)
    return report


_SUFFIX_LABEL = {".csv": "CSV files", ".asc": "ASC map files", ".txt": "text files"}


def _format_gb(n_bytes: int) -> str:
    # 1024-based, like File Explorer and the frontend's formatBytes -- so the
    # size quoted here matches what the user sees in the folder's Properties.
    gb = n_bytes / 1024**3
    return f"{gb:.1f} GB" if gb >= 0.1 else f"{n_bytes / 1024**2:.0f} MB"


def cloud_only_message(report: LocalFilesReport, root: Path) -> str:
    parts = [
        f"{cloud:,} of {total:,} {_SUFFIX_LABEL.get(suffix, suffix + ' files')}"
        for suffix, (cloud, total) in sorted(report.by_suffix.items())
        if cloud
    ]
    listed = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
    return (
        f"{listed} in this folder ({_format_gb(report.cloud_only_bytes)}) are stored "
        "only online (e.g. OneDrive \"Files On-Demand\") and are not on this computer yet. "
        "The scan has to read every one of them, so nothing was loaded. "
        + _KEEP_LOCAL_HINT.format(folder=root.name)
    )


def can_make_local() -> bool:
    """Whether this machine can ask a sync app to download cloud-only
    files (Windows Cloud Files placeholders). False on a Linux server."""
    return sys.platform == "win32"


def _attrib(root: Path, *flags: str) -> None:
    """Apply ``attrib`` flags to ``root`` itself and everything under it.
    ``+P -U`` = pinned ("Always keep on this device"); ``-P`` = back to the
    default state (the sync app stops fetching anything not yet local)."""
    for target, extra in ((str(root), ()), (str(root / "*"), ("/S", "/D"))):
        proc = subprocess.run(
            ["attrib", *flags, target, *extra], capture_output=True, timeout=1800,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            output = (proc.stdout + proc.stderr).decode(errors="replace").strip()
            raise SourceNotLocalError(
                f"Windows refused to mark \"{root.name}\" to be kept on this computer "
                f"(attrib exit code {proc.returncode}{': ' + output if output else ''})."
            )


def request_keep_local(root: Path) -> None:
    """Ask the sync app to download everything under ``root`` and keep it
    local -- exactly Explorer's "Always keep on this device". Returns as soon
    as the request is made; the download itself runs in the sync app."""
    _attrib(root, "+P", "-U")


def release_keep_local(root: Path) -> None:
    """Undo ``request_keep_local`` (used when the user cancels mid-download)
    so the sync app stops fetching the rest. Files already downloaded stay
    as they are. Best-effort: a failure here must not mask the cancel."""
    try:
        _attrib(root, "-P")
    except (SourceNotLocalError, OSError, subprocess.SubprocessError):
        pass


# No byte arriving for this long means the sync app isn't downloading at all
# (paused, signed out, offline, erroring) -- say so instead of waiting forever.
DOWNLOAD_STALL_SECONDS = 600
_DOWNLOAD_POLL_SECONDS = 5


def wait_until_local(
    root: Path,
    on_progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    stall_seconds: float = DOWNLOAD_STALL_SECONDS,
    poll_seconds: float = _DOWNLOAD_POLL_SECONDS,
) -> bool:
    """Block until nothing under ``root`` is cloud-only, reporting
    ``on_progress(bytes_downloaded, bytes_total)``. Returns False if
    ``cancel_event`` was set (caller decides what cancelling means), True
    once everything is local. Raises ``SourceNotLocalError`` if nothing has
    been downloaded for ``stall_seconds``."""
    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    # A cancelled scan returns a partial report -- never read it as "done".
    report = scan_local_availability(root, cancel_event=cancel_event)
    if cancelled():
        return False
    total = report.cloud_only_bytes
    remaining = total
    last_change = time.monotonic()
    while report.cloud_only:
        if on_progress is not None:
            on_progress(total - remaining, total)
        if cancel_event is not None and cancel_event.wait(poll_seconds):
            return False
        if cancel_event is None:
            time.sleep(poll_seconds)
        report = scan_local_availability(root, cancel_event=cancel_event)
        if cancelled():
            return False
        if report.cloud_only_bytes < remaining:
            remaining = report.cloud_only_bytes
            last_change = time.monotonic()
        elif time.monotonic() - last_change > stall_seconds:
            raise SourceNotLocalError(
                f"OneDrive has not downloaded anything for {round(stall_seconds / 60)} minutes "
                f"({_format_gb(remaining)} of {_format_gb(total)} still missing). Check the "
                "OneDrive icon in the taskbar -- syncing may be paused, signed out or reporting "
                "an error -- then click Rescan to continue where it stopped."
            )
    if on_progress is not None:
        on_progress(total, total)
    return True


def check_files_are_local(
    root: Path,
    on_progress: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> LocalFilesReport:
    """Pre-scan gate: raise ``SourceNotLocalError`` if any file the scan
    would read exists only in the cloud. Deliberately blocks rather than
    letting the scan trigger downloads file by file: a full scan would
    silently pull tens of GB, and one failed download mid-way leaves a
    half-read Monte Carlo ensemble -- neither is something to find out an
    hour in."""
    report = scan_local_availability(root, on_progress, cancel_event)
    if report.cloud_only:
        raise SourceNotLocalError(cloud_only_message(report, root))
    return report
