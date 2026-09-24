"""Tests for core/config.py's small filesystem helpers."""

from __future__ import annotations

from ecosim.core.config import dir_size_bytes


def test_dir_size_bytes_nonexistent_dir_is_zero(tmp_path):
    assert dir_size_bytes(tmp_path / "does_not_exist") == 0


def test_dir_size_bytes_sums_files_recursively(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x" * 100)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.txt").write_bytes(b"y" * 250)

    assert dir_size_bytes(tmp_path) == 350


def test_dir_size_bytes_ignores_subdirectories_themselves(tmp_path):
    # An empty subdirectory contributes nothing -- only real files count.
    (tmp_path / "empty_subdir").mkdir()
    assert dir_size_bytes(tmp_path) == 0
