"""Tests for StorageManager from src/camera_service.py — uses tmp_path for real filesystem."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from camera_service import StorageManager


def _make_manager(tmp_path, mock_logger, **overrides):
    """Helper to create a StorageManager rooted in tmp_path."""
    defaults = dict(
        base_path=tmp_path / "storage",
        max_size_gb=1.0,
        cleanup_threshold_gb=0.8,
        retention_days=7,
        logger=mock_logger,
    )
    defaults.update(overrides)
    return StorageManager(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# Constructor
# ──────────────────────────────────────────────────────────────────────────────

class TestStorageManagerInit:

    def test_creates_uploaded_dir(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        assert (sm.base_path / "uploaded").is_dir()

    def test_creates_metadata_dir(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        assert (sm.base_path / "metadata").is_dir()


# ──────────────────────────────────────────────────────────────────────────────
# store_image
# ──────────────────────────────────────────────────────────────────────────────

class TestStoreImage:

    def test_creates_image_file(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        data = b"\xff\xd8\xff" + b"\x00" * 100
        assert sm.store_image(data, "cam1_2026-01-01_00-00-00.jpg") is True
        assert (sm.base_path / "cam1_2026-01-01_00-00-00.jpg").exists()

    def test_creates_metadata_json(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        meta = {"camera_id": "cam1", "timestamp": "2026-01-01"}
        sm.store_image(b"\xff" * 50, "cam1.jpg", metadata=meta)
        meta_file = sm.metadata_path / "cam1.jpg.json"
        assert meta_file.exists()
        stored = json.loads(meta_file.read_text())
        assert stored["camera_id"] == "cam1"

    def test_no_metadata_when_none(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        sm.store_image(b"\xff" * 50, "cam1.jpg", metadata=None)
        assert not (sm.metadata_path / "cam1.jpg.json").exists()

    def test_triggers_cleanup_at_limit(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger, max_size_gb=0)
        with patch.object(sm, "cleanup_old_files") as mock_cleanup:
            sm.store_image(b"\xff" * 50, "cam1.jpg")
            mock_cleanup.assert_called_once_with(force=True)

    def test_returns_true_on_success(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        assert sm.store_image(b"\xff", "test.jpg") is True


# ──────────────────────────────────────────────────────────────────────────────
# mark_as_uploaded
# ──────────────────────────────────────────────────────────────────────────────

class TestMarkAsUploaded:

    def test_moves_image_to_uploaded(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        sm.store_image(b"\xff" * 50, "img.jpg")
        assert sm.mark_as_uploaded("img.jpg") is True
        assert not (sm.base_path / "img.jpg").exists()
        assert (sm.uploaded_path / "img.jpg").exists()

    def test_moves_metadata(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        sm.store_image(b"\xff" * 50, "img.jpg", metadata={"k": "v"})
        sm.mark_as_uploaded("img.jpg")
        assert (sm.uploaded_path / "metadata" / "img.jpg.json").exists()
        assert not (sm.metadata_path / "img.jpg.json").exists()

    def test_returns_true_on_success(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        sm.store_image(b"\xff" * 50, "img.jpg")
        assert sm.mark_as_uploaded("img.jpg") is True


# ──────────────────────────────────────────────────────────────────────────────
# get_current_size_gb
# ──────────────────────────────────────────────────────────────────────────────

class TestGetCurrentSizeGb:

    def test_empty_dir_is_zero(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        assert sm.get_current_size_gb() == pytest.approx(0, abs=0.001)

    def test_correct_calculation_with_known_files(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger)
        # Write exactly 1 MiB = 1/1024 GiB
        (sm.base_path / "test.bin").write_bytes(b"\x00" * (1024 * 1024))
        expected_gb = 1.0 / 1024
        assert sm.get_current_size_gb() == pytest.approx(expected_gb, rel=0.01)


# ──────────────────────────────────────────────────────────────────────────────
# cleanup_old_files
# ──────────────────────────────────────────────────────────────────────────────

class TestCleanupOldFiles:

    def test_below_threshold_no_op(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger, cleanup_threshold_gb=100)
        sm.store_image(b"\xff" * 100, "img.jpg")
        sm.mark_as_uploaded("img.jpg")
        # File should still exist after cleanup (below threshold)
        sm.cleanup_old_files()
        assert (sm.uploaded_path / "img.jpg").exists()

    def test_deletes_oldest_uploaded_first(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger, cleanup_threshold_gb=0)
        # Create two uploaded files with different ages
        sm.store_image(b"\xff" * 100, "old.jpg")
        sm.mark_as_uploaded("old.jpg")
        sm.store_image(b"\xff" * 100, "new.jpg")
        sm.mark_as_uploaded("new.jpg")
        # Force cleanup — should delete oldest first
        sm.cleanup_old_files(force=True)
        # After cleanup with threshold=0, all should be deleted
        assert not (sm.uploaded_path / "old.jpg").exists()

    def test_force_ignores_retention(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger, cleanup_threshold_gb=0, retention_days=9999)
        sm.store_image(b"\xff" * 100, "img.jpg")
        sm.mark_as_uploaded("img.jpg")
        sm.cleanup_old_files(force=True)
        assert not (sm.uploaded_path / "img.jpg").exists()

    def test_respects_retention_days(self, tmp_path, mock_logger):
        sm = _make_manager(tmp_path, mock_logger, cleanup_threshold_gb=0, retention_days=9999)
        sm.store_image(b"\xff" * 100, "img.jpg")
        sm.mark_as_uploaded("img.jpg")
        # Non-force should respect retention — file is brand new
        sm.cleanup_old_files(force=False)
        # File should still exist because retention=9999 days
        assert (sm.uploaded_path / "img.jpg").exists()

    def test_stops_at_target(self, tmp_path, mock_logger):
        """Once below threshold, stop deleting."""
        # threshold=0 means always cleanup; files are small so all get cleaned
        sm = _make_manager(tmp_path, mock_logger, cleanup_threshold_gb=0)
        for i in range(5):
            sm.store_image(b"\xff" * 100, f"img{i}.jpg")
            sm.mark_as_uploaded(f"img{i}.jpg")
        sm.cleanup_old_files(force=True)
        remaining = list(sm.uploaded_path.glob("*.jpg"))
        # All should be deleted when threshold=0
        assert len(remaining) == 0

    def test_concurrent_lock(self, tmp_path, mock_logger):
        """Second cleanup call while first is in progress should be skipped."""
        sm = _make_manager(tmp_path, mock_logger)
        sm._cleanup_lock.acquire()
        try:
            # This should be a no-op since lock is held
            sm.cleanup_old_files()
        finally:
            sm._cleanup_lock.release()
