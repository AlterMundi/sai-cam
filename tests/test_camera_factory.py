"""Tests for src/cameras/camera_factory.py — Factory, validation, supported types."""

import logging
from unittest.mock import patch, MagicMock

import pytest

from cameras.camera_factory import (
    get_supported_camera_types,
    validate_camera_config,
    create_camera,
    create_camera_from_config,
)


# ──────────────────────────────────────────────────────────────────────────────
# get_supported_camera_types
# ──────────────────────────────────────────────────────────────────────────────

class TestGetSupportedCameraTypes:

    def test_returns_expected_types(self):
        assert get_supported_camera_types() == ['usb', 'rtsp', 'onvif']


# ──────────────────────────────────────────────────────────────────────────────
# validate_camera_config
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateCameraConfig:

    # --- Valid configs ---

    def test_valid_rtsp_config(self, sample_rtsp_camera_config):
        errors = validate_camera_config(sample_rtsp_camera_config)
        assert errors == {}

    def test_valid_usb_config(self, sample_usb_camera_config):
        errors = validate_camera_config(sample_usb_camera_config)
        assert errors == {}

    def test_valid_onvif_config(self, sample_onvif_camera_config):
        errors = validate_camera_config(sample_onvif_camera_config)
        assert errors == {}

    # --- Missing required fields ---

    def test_missing_id(self):
        errors = validate_camera_config({'type': 'rtsp', 'rtsp_url': 'rtsp://host/s'})
        assert 'id' in errors

    def test_unsupported_type(self):
        errors = validate_camera_config({'id': 'cam1', 'type': 'thermal'})
        assert 'type' in errors

    # --- Type-specific missing fields ---

    def test_rtsp_missing_url(self):
        errors = validate_camera_config({'id': 'cam1', 'type': 'rtsp'})
        assert 'rtsp_url' in errors

    def test_usb_missing_device(self):
        errors = validate_camera_config({'id': 'cam1', 'type': 'usb'})
        assert 'device' in errors

    def test_usb_with_device_index_only(self):
        """device_index=0 should pass validation."""
        errors = validate_camera_config({'id': 'cam1', 'type': 'usb', 'device_index': 0})
        assert 'device' not in errors

    def test_onvif_missing_address(self):
        errors = validate_camera_config({'id': 'cam1', 'type': 'onvif'})
        assert 'address' in errors

    # --- Resolution validation ---

    def test_invalid_resolution_wrong_length(self):
        errors = validate_camera_config({'id': 'c', 'type': 'rtsp', 'rtsp_url': 'rtsp://h/s', 'resolution': [1920]})
        assert 'resolution' in errors

    def test_invalid_resolution_negative(self):
        errors = validate_camera_config({'id': 'c', 'type': 'rtsp', 'rtsp_url': 'rtsp://h/s', 'resolution': [-1, 720]})
        assert 'resolution' in errors

    def test_invalid_resolution_non_list(self):
        errors = validate_camera_config({'id': 'c', 'type': 'rtsp', 'rtsp_url': 'rtsp://h/s', 'resolution': "1920x1080"})
        assert 'resolution' in errors

    # --- FPS validation ---

    def test_invalid_fps_zero(self):
        errors = validate_camera_config({'id': 'c', 'type': 'rtsp', 'rtsp_url': 'rtsp://h/s', 'fps': 0})
        assert 'fps' in errors

    def test_invalid_fps_negative(self):
        errors = validate_camera_config({'id': 'c', 'type': 'rtsp', 'rtsp_url': 'rtsp://h/s', 'fps': -5})
        assert 'fps' in errors

    # --- Capture interval validation ---

    def test_invalid_capture_interval(self):
        errors = validate_camera_config({'id': 'c', 'type': 'rtsp', 'rtsp_url': 'rtsp://h/s', 'capture_interval': 0})
        assert 'capture_interval' in errors


# ──────────────────────────────────────────────────────────────────────────────
# create_camera / create_camera_from_config
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateCamera:

    @patch("cameras.camera_factory.RTSPCamera")
    def test_creates_rtsp_camera(self, MockRTSP, sample_rtsp_camera_config, sample_global_config, mock_logger):
        create_camera("cam1", sample_rtsp_camera_config, sample_global_config, mock_logger)
        MockRTSP.assert_called_once()

    @patch("cameras.camera_factory.USBCamera")
    def test_creates_usb_camera(self, MockUSB, sample_usb_camera_config, sample_global_config, mock_logger):
        create_camera("cam1", sample_usb_camera_config, sample_global_config, mock_logger)
        MockUSB.assert_called_once()

    def test_unsupported_type_raises(self, sample_global_config, mock_logger):
        with pytest.raises(ValueError, match="Unsupported camera type"):
            create_camera("cam1", {'type': 'thermal'}, sample_global_config, mock_logger)


class TestCreateCameraFromConfig:

    def test_invalid_config_raises(self, sample_global_config, mock_logger):
        """Missing id should cause validation error."""
        with pytest.raises(ValueError, match="Camera configuration errors"):
            create_camera_from_config({'type': 'rtsp'}, sample_global_config, mock_logger)

    @patch("cameras.camera_factory.RTSPCamera")
    def test_valid_config_creates_camera(self, MockRTSP, sample_rtsp_camera_config, sample_global_config, mock_logger):
        create_camera_from_config(sample_rtsp_camera_config, sample_global_config, mock_logger)
        MockRTSP.assert_called_once()
