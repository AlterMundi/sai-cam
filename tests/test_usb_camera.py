"""Tests for src/cameras/usb_camera.py — USB camera implementation."""

import numpy as np
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from cameras.usb_camera import USBCamera


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cam_config(**overrides):
    base = {
        'id': 'cam-usb-01',
        'type': 'usb',
        'device_path': '/dev/video0',
        'resolution': [1280, 720],
        'fps': 30,
        'capture_interval': 120,
        'buffer_size': 1,
    }
    base.update(overrides)
    return base


def _global_config(**overrides):
    base = {
        'advanced': {
            'reconnect_attempts': 3,
            'reconnect_delay': 0,
            'camera_init_wait': 0,
        },
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _reset_cv2():
    """Reset cv2 mock state between tests (cv2 is a shared MagicMock)."""
    import cv2
    cv2.VideoCapture.reset_mock()
    cv2.VideoCapture.side_effect = None
    yield


@pytest.fixture
def cam(mock_logger):
    """Create a USBCamera with device_path set."""
    return USBCamera('cam-usb-01', _cam_config(), _global_config(), mock_logger)


# ---------------------------------------------------------------------------
# Constructor — device ID resolution
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestUSBCameraInit:

    def test_device_path_used_when_set(self, mock_logger):
        cam = USBCamera('c1', _cam_config(device_path='/dev/video2'), _global_config(), mock_logger)
        assert cam.device_id == '/dev/video2'

    def test_device_index_used_when_set(self, mock_logger):
        cam = USBCamera('c1', _cam_config(device_path=None, device_index=3), _global_config(), mock_logger)
        assert cam.device_id == 3

    @patch("os.path.exists", return_value=False)
    def test_fallback_to_index_when_device_missing(self, mock_exists, mock_logger):
        cfg = _cam_config(device_path=None, device_index=None)
        cam = USBCamera('c1', cfg, _global_config(), mock_logger)
        assert cam.device_id == 0  # fallback

    def test_resolution_and_fps(self, cam):
        assert cam.resolution == (1280, 720)
        assert cam.fps == 30

    def test_buffer_size_default(self, mock_logger):
        cfg = _cam_config()
        del cfg['buffer_size']
        cam = USBCamera('c1', cfg, _global_config(), mock_logger)
        assert cam.buffer_size == 1

    def test_camera_controls_stored(self, mock_logger):
        cfg = _cam_config(auto_exposure=False, brightness=50, contrast=60, saturation=70)
        cam = USBCamera('c1', cfg, _global_config(), mock_logger)
        assert cam.auto_exposure is False
        assert cam.brightness == 50
        assert cam.contrast == 60
        assert cam.saturation == 70

    def test_auto_exposure_default_true(self, cam):
        assert cam.auto_exposure is True


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestUSBCameraSetup:

    @patch("os.path.exists", return_value=True)
    @patch("time.sleep")
    def test_setup_success(self, mock_sleep, mock_exists, cam):
        import cv2
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, np.zeros((720, 1280, 3), dtype=np.uint8))
        mock_cap.get.return_value = 30.0
        cv2.VideoCapture.return_value = mock_cap

        assert cam.setup() is True
        assert cam.is_connected is True
        assert cam.reconnect_attempts == 0

    @patch("os.path.exists", return_value=False)
    def test_setup_device_not_found(self, mock_exists, mock_logger):
        cfg = _cam_config(device_path='/dev/video99')
        c = USBCamera('c1', cfg, _global_config(), mock_logger)
        assert c.setup() is False

    @patch("os.path.exists", return_value=True)
    def test_setup_cap_not_opened(self, mock_exists, cam):
        import cv2
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        cv2.VideoCapture.return_value = mock_cap
        assert cam.setup() is False

    @patch("os.path.exists", return_value=True)
    @patch("time.sleep")
    def test_setup_test_frame_fails(self, mock_sleep, mock_exists, cam):
        import cv2
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)
        cv2.VideoCapture.return_value = mock_cap
        assert cam.setup() is False

    @patch("os.path.exists", return_value=True)
    @patch("time.sleep")
    def test_setup_exception_returns_false(self, mock_sleep, mock_exists, cam):
        import cv2
        cv2.VideoCapture.side_effect = RuntimeError("device busy")
        assert cam.setup() is False
        assert cam.is_connected is False

    @patch("os.path.exists", return_value=True)
    @patch("time.sleep")
    def test_setup_sets_camera_controls(self, mock_sleep, mock_exists, mock_logger):
        cfg = _cam_config(auto_exposure=False, brightness=50, contrast=60, saturation=70)
        c = USBCamera('c1', cfg, _global_config(), mock_logger)

        import cv2
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, np.zeros((720, 1280, 3), dtype=np.uint8))
        mock_cap.get.return_value = 30.0
        cv2.VideoCapture.return_value = mock_cap

        c.setup()

        # Verify camera controls were set (brightness=50, contrast=60, saturation=70)
        set_values = [call[0][1] for call in mock_cap.set.call_args_list]
        assert 50 in set_values
        assert 60 in set_values
        assert 70 in set_values


# ---------------------------------------------------------------------------
# capture_frame
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestUSBCameraCaptureFrame:

    def test_not_connected_returns_none(self, cam):
        cam.is_connected = False
        assert cam.capture_frame() is None

    def test_no_cap_returns_none(self, cam):
        cam.is_connected = True
        cam.cap = None
        assert cam.capture_frame() is None

    def test_cap_closed_returns_none(self, cam):
        cam.is_connected = True
        cam.cap = MagicMock()
        cam.cap.isOpened.return_value = False
        assert cam.capture_frame() is None

    def test_success_returns_frame(self, cam):
        cam.is_connected = True
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        cam.cap = MagicMock()
        cam.cap.isOpened.return_value = True
        cam.cap.read.return_value = (True, frame)
        result = cam.capture_frame()
        assert result is not None
        assert result.shape == (720, 1280, 3)

    def test_read_fails_returns_none(self, cam):
        cam.is_connected = True
        cam.cap = MagicMock()
        cam.cap.isOpened.return_value = True
        cam.cap.read.return_value = (False, None)
        assert cam.capture_frame() is None

    def test_exception_returns_none(self, cam):
        cam.is_connected = True
        cam.cap = MagicMock()
        cam.cap.isOpened.return_value = True
        cam.cap.read.side_effect = RuntimeError("read error")
        assert cam.capture_frame() is None


# ---------------------------------------------------------------------------
# set_camera_property / get_camera_property
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestUSBCameraProperties:

    def test_set_property_success(self, cam):
        cam.cap = MagicMock()
        cam.cap.isOpened.return_value = True
        cam.cap.set.return_value = True
        assert cam.set_camera_property(0, 1.0) is True

    def test_set_property_no_cap(self, cam):
        cam.cap = None
        assert cam.set_camera_property(0, 1.0) is False

    def test_get_property_success(self, cam):
        cam.cap = MagicMock()
        cam.cap.isOpened.return_value = True
        cam.cap.get.return_value = 42.0
        assert cam.get_camera_property(0) == 42.0

    def test_get_property_no_cap(self, cam):
        cam.cap = None
        assert cam.get_camera_property(0) == -1


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestUSBCameraCleanup:

    def test_cleanup_releases_cap(self, cam):
        mock_cap = MagicMock()
        cam.cap = mock_cap
        cam.is_connected = True

        cam.cleanup()

        mock_cap.release.assert_called_once()
        assert cam.cap is None
        assert cam.is_connected is False

    def test_cleanup_when_cap_is_none(self, cam):
        cam.cap = None
        cam.cleanup()  # should not raise
        assert cam.is_connected is False


# ---------------------------------------------------------------------------
# reconnect
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestUSBCameraReconnect:

    @patch("time.sleep")
    def test_reconnect_calls_cleanup_and_setup(self, mock_sleep, cam):
        cam.cap = MagicMock()
        with patch.object(cam, 'setup', return_value=True) as mock_setup:
            result = cam.reconnect()
        assert result is True
        mock_setup.assert_called_once()
        assert cam.reconnect_attempts == 1

    @patch("time.sleep")
    def test_reconnect_fails_after_max_attempts(self, mock_sleep, cam):
        cam.reconnect_attempts = cam.max_reconnect_attempts
        result = cam.reconnect()
        assert result is False


# ---------------------------------------------------------------------------
# get_camera_info
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestUSBCameraInfo:

    def test_info_when_disconnected(self, cam):
        cam.is_connected = False
        info = cam.get_camera_info()
        assert info['camera_id'] == 'cam-usb-01'
        assert info['type'] == 'usb'
        assert info['is_connected'] is False
        assert info['camera_open'] is False

    def test_info_when_connected(self, cam):
        cam.is_connected = True
        cam.cap = MagicMock()
        cam.cap.isOpened.return_value = True
        cam.cap.get.return_value = 30.0

        info = cam.get_camera_info()
        assert info['is_connected'] is True
        assert info['camera_open'] is True
        assert 'actual_resolution' in info
