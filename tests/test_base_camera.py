"""Tests for src/cameras/base_camera.py — BaseCamera abstract class via a ConcreteCamera stub."""

import time
import logging
from unittest.mock import patch

import numpy as np
import pytest

from cameras.base_camera import BaseCamera


class ConcreteCamera(BaseCamera):
    """Minimal concrete subclass for testing BaseCamera methods."""

    def setup(self):
        return True

    def capture_frame(self):
        return None

    def reconnect(self):
        return True

    def cleanup(self):
        pass

    def get_camera_info(self):
        return {"type": self.config.get("type", "test")}


def _make_camera(camera_config=None, global_config=None, logger=None):
    camera_config = camera_config or {
        "id": "test-cam",
        "type": "rtsp",
        "capture_interval": 120,
        "resolution": [1920, 1080],
        "fps": 15,
    }
    global_config = global_config or {"advanced": {"reconnect_attempts": 3}}
    logger = logger or logging.getLogger("test")
    return ConcreteCamera(camera_config["id"], camera_config, global_config, logger)


# ──────────────────────────────────────────────────────────────────────────────
# validate_frame
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateFrame:

    def test_none_returns_false(self):
        cam = _make_camera()
        assert cam.validate_frame(None) is False

    def test_empty_array_returns_false(self):
        cam = _make_camera()
        assert cam.validate_frame(np.array([])) is False

    def test_normal_frame_returns_true(self):
        cam = _make_camera()
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        assert cam.validate_frame(frame) is True

    def test_dark_frame_warns_but_valid(self, mock_logger):
        cam = _make_camera(logger=mock_logger)
        frame = np.full((480, 640, 3), 2, dtype=np.uint8)
        assert cam.validate_frame(frame) is True
        warnings = [r for r in mock_logger._test_handler.records if r.levelno == logging.WARNING]
        assert any("Low brightness" in r.getMessage() for r in warnings)

    def test_bright_frame_warns_but_valid(self, mock_logger):
        cam = _make_camera(logger=mock_logger)
        frame = np.full((480, 640, 3), 252, dtype=np.uint8)
        assert cam.validate_frame(frame) is True
        warnings = [r for r in mock_logger._test_handler.records if r.levelno == logging.WARNING]
        assert any("High brightness" in r.getMessage() for r in warnings)

    def test_midrange_frame_no_warning(self, mock_logger):
        cam = _make_camera(logger=mock_logger)
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        cam.validate_frame(frame)
        warnings = [r for r in mock_logger._test_handler.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0


# ──────────────────────────────────────────────────────────────────────────────
# Timing methods
# ──────────────────────────────────────────────────────────────────────────────

class TestTimingMethods:

    def test_get_capture_interval_configured(self):
        cam = _make_camera()
        assert cam.get_capture_interval() == 120

    def test_get_capture_interval_default(self):
        cam = _make_camera(camera_config={"id": "c", "type": "rtsp"})
        assert cam.get_capture_interval() == 300

    def test_should_capture_now_elapsed(self):
        cam = _make_camera()
        cam.last_frame_time = time.time() - 200  # well past 120s interval
        assert cam.should_capture_now() is True

    def test_should_capture_now_not_elapsed(self):
        cam = _make_camera()
        cam.last_frame_time = time.time()  # just captured
        assert cam.should_capture_now() is False


# ──────────────────────────────────────────────────────────────────────────────
# Resolution / FPS
# ──────────────────────────────────────────────────────────────────────────────

class TestResolutionFps:

    def test_configured_resolution(self):
        cam = _make_camera()
        assert cam.get_resolution() == (1920, 1080)

    def test_default_resolution(self):
        cam = _make_camera(camera_config={"id": "c", "type": "rtsp"})
        assert cam.get_resolution() == (1280, 720)

    def test_configured_fps(self):
        cam = _make_camera()
        assert cam.get_fps() == 15

    def test_default_fps(self):
        cam = _make_camera(camera_config={"id": "c", "type": "rtsp"})
        assert cam.get_fps() == 30


# ──────────────────────────────────────────────────────────────────────────────
# Reconnect attempts
# ──────────────────────────────────────────────────────────────────────────────

class TestReconnectAttempts:

    def test_increment_returns_true_below_max(self):
        cam = _make_camera()  # max=3
        assert cam.increment_reconnect_attempts() is True  # 1 < 3
        assert cam.increment_reconnect_attempts() is True  # 2 < 3

    def test_increment_returns_false_at_max(self):
        cam = _make_camera()
        cam.increment_reconnect_attempts()  # 1
        cam.increment_reconnect_attempts()  # 2
        assert cam.increment_reconnect_attempts() is False  # 3 >= 3

    def test_reset_to_zero(self):
        cam = _make_camera()
        cam.increment_reconnect_attempts()
        cam.reset_reconnect_attempts()
        assert cam.reconnect_attempts == 0

    def test_max_from_global_config(self):
        cam = _make_camera(global_config={"advanced": {"reconnect_attempts": 5}})
        assert cam.max_reconnect_attempts == 5

    def test_max_default_when_not_configured(self):
        cam = _make_camera(global_config={})
        assert cam.max_reconnect_attempts == 3


# ──────────────────────────────────────────────────────────────────────────────
# Constructor / __str__
# ──────────────────────────────────────────────────────────────────────────────

class TestConstructorStr:

    def test_init_stores_values(self):
        cam = _make_camera()
        assert cam.camera_id == "test-cam"
        assert cam.config["type"] == "rtsp"

    def test_is_connected_defaults_false(self):
        cam = _make_camera()
        assert cam.is_connected is False

    def test_str_format(self):
        cam = _make_camera()
        s = str(cam)
        assert "ConcreteCamera" in s
        assert "test-cam" in s
        assert "rtsp" in s
