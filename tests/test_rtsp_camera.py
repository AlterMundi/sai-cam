"""Tests for src/cameras/rtsp_camera.py — RTSP camera implementation."""

import numpy as np
from unittest.mock import patch, MagicMock

import pytest

from cameras.rtsp_camera import RTSPCamera


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cam_config(**overrides):
    base = {
        'id': 'cam-rtsp-01',
        'type': 'rtsp',
        'rtsp_url': 'rtsp://admin:secret@192.168.220.10:554/stream1',
        'resolution': [1920, 1080],
        'fps': 15,
        'capture_interval': 120,
        'buffer_size': 0,
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
    """Reset cv2 mock state between tests."""
    import cv2
    cv2.VideoCapture.reset_mock()
    cv2.VideoCapture.side_effect = None
    yield


@pytest.fixture
def cam(mock_logger):
    return RTSPCamera('cam-rtsp-01', _cam_config(), _global_config(), mock_logger)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestRTSPCameraInit:

    def test_stores_rtsp_url(self, cam):
        assert cam.rtsp_url == 'rtsp://admin:secret@192.168.220.10:554/stream1'

    def test_resolution_and_fps(self, cam):
        assert cam.resolution == (1920, 1080)
        assert cam.fps == 15

    def test_missing_rtsp_url_raises(self, mock_logger):
        cfg = _cam_config()
        del cfg['rtsp_url']
        with pytest.raises(ValueError, match="rtsp_url"):
            RTSPCamera('c1', cfg, _global_config(), mock_logger)

    def test_buffer_size_default(self, mock_logger):
        cfg = _cam_config()
        del cfg['buffer_size']
        cam = RTSPCamera('c1', cfg, _global_config(), mock_logger)
        assert cam.buffer_size == 0


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestRTSPCameraSetup:

    @patch("time.sleep")
    def test_setup_success(self, mock_sleep, cam):
        import cv2
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, np.zeros((1080, 1920, 3), dtype=np.uint8))
        mock_cap.get.return_value = 15.0
        cv2.VideoCapture.return_value = mock_cap

        assert cam.setup() is True
        assert cam.is_connected is True
        assert cam.reconnect_attempts == 0

    def test_setup_cap_not_opened(self, cam):
        import cv2
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        cv2.VideoCapture.return_value = mock_cap
        assert cam.setup() is False

    @patch("time.sleep")
    def test_setup_stream_closes_after_init(self, mock_sleep, cam):
        """isOpened returns True first, False after init_wait."""
        import cv2
        mock_cap = MagicMock()
        mock_cap.isOpened.side_effect = [True, False]
        cv2.VideoCapture.return_value = mock_cap
        assert cam.setup() is False

    @patch("time.sleep")
    def test_setup_test_frame_fails(self, mock_sleep, cam):
        import cv2
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)
        mock_cap.get.return_value = 15.0
        cv2.VideoCapture.return_value = mock_cap

        assert cam.setup() is False
        # Should release cap on frame failure
        mock_cap.release.assert_called_once()

    @patch("time.sleep")
    def test_setup_exception(self, mock_sleep, cam):
        import cv2
        cv2.VideoCapture.side_effect = RuntimeError("connection refused")
        assert cam.setup() is False
        assert cam.is_connected is False


# ---------------------------------------------------------------------------
# capture_frame
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestRTSPCameraCaptureFrame:

    def test_not_connected_returns_none(self, cam):
        cam.is_connected = False
        assert cam.capture_frame() is None

    def test_no_frame_returns_none(self, cam):
        cam.is_connected = True
        cam.latest_frame = None
        assert cam.capture_frame() is None

    def test_success_returns_frame(self, cam):
        cam.is_connected = True
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cam.latest_frame = frame
        result = cam.capture_frame()
        assert result is not None
        assert result.shape == (1080, 1920, 3)


# ---------------------------------------------------------------------------
# grab_frame
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestRTSPCameraGrabFrame:

    def test_not_connected_returns_false(self, cam):
        cam.is_connected = False
        assert cam.grab_frame() is False

    def test_success(self, cam):
        cam.is_connected = True
        assert cam.grab_frame() is True


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestRTSPCameraCleanup:

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
        cam.cleanup()
        assert cam.is_connected is False


# ---------------------------------------------------------------------------
# reconnect
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestRTSPCameraReconnect:

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
class TestRTSPCameraInfo:

    def test_info_when_disconnected(self, cam):
        cam.is_connected = False
        info = cam.get_camera_info()
        assert info['camera_id'] == 'cam-rtsp-01'
        assert info['type'] == 'rtsp'
        assert info['is_connected'] is False
        assert info['stream_open'] is False
        assert info['rtsp_url'] == cam.rtsp_url

    def test_info_when_connected(self, cam):
        cam.is_connected = True
        cam.cap = MagicMock()
        cam.cap.isOpened.return_value = True
        cam.cap.get.return_value = 15.0

        info = cam.get_camera_info()
        assert info['is_connected'] is True
        assert info['stream_open'] is True
        assert 'actual_resolution' in info
