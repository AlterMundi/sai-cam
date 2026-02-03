"""Tests for src/cameras/onvif_camera.py — ONVIF camera implementation."""

import numpy as np
from unittest.mock import patch, MagicMock

import pytest

# The onvif module is pre-mocked in conftest.py, so ONVIFCamera is a MagicMock.
# We need to make sure the import check in onvif_camera.py finds it.
from cameras.onvif_camera import ONVIFCameraImpl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _cam_config(**overrides):
    base = {
        'id': 'cam-onvif-01',
        'type': 'onvif',
        'address': '192.168.220.10',
        'port': 8000,
        'username': 'admin',
        'password': 'secret',
        'resolution': [1920, 1080],
        'fps': 15,
        'capture_interval': 180,
        'timeout': 10,
    }
    base.update(overrides)
    return base


def _global_config(**overrides):
    base = {
        'advanced': {
            'reconnect_attempts': 3,
            'reconnect_delay': 0,
        },
    }
    base.update(overrides)
    return base


@pytest.fixture
def cam(mock_logger):
    """Create an ONVIFCameraImpl with mocked ConfigHelper."""
    with patch("config_helper.ConfigHelper") as MockHelper:
        helper = MagicMock()
        # get_secure_value returns the config fallback value directly
        helper.get_secure_value.side_effect = lambda env_key, config_val, **kw: (
            config_val if config_val is not None else kw.get('default')
        )
        MockHelper.return_value = helper
        return ONVIFCameraImpl('cam-onvif-01', _cam_config(), _global_config(), mock_logger)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestONVIFCameraInit:

    def test_stores_connection_params(self, cam):
        assert cam.address == '192.168.220.10'
        assert cam.port == 8000
        assert cam.username == 'admin'
        assert cam.password == 'secret'

    def test_timeout_stored(self, cam):
        assert cam.timeout == 10

    def test_starts_disconnected(self, cam):
        assert cam.is_connected is False
        assert cam.snapshot_uri is None
        assert cam.onvif_camera is None

    def test_missing_address_raises(self, mock_logger):
        cfg = _cam_config(address=None)
        with patch("config_helper.ConfigHelper") as MockHelper:
            helper = MagicMock()
            helper.get_secure_value.side_effect = lambda env_key, config_val, **kw: (
                config_val if config_val is not None else kw.get('default')
            )
            MockHelper.return_value = helper
            with pytest.raises(ValueError, match="address"):
                ONVIFCameraImpl('c1', cfg, _global_config(), mock_logger)


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestONVIFCameraSetup:

    @patch("cameras.onvif_camera.ONVIFCamera")
    def test_setup_success(self, MockONVIF, cam):
        mock_onvif = MagicMock()
        MockONVIF.return_value = mock_onvif

        # Device info
        device_info = MagicMock()
        device_info.Manufacturer = 'TestCo'
        device_info.Model = 'X100'
        mock_onvif.devicemgmt.GetDeviceInformation.return_value = device_info

        # Media service with profile and snapshot URI
        media = MagicMock()
        mock_onvif.create_media_service.return_value = media
        profile = MagicMock()
        profile.Name = 'Profile1'
        profile.token = 'tok1'
        media.GetProfiles.return_value = [profile]
        snapshot_resp = MagicMock()
        snapshot_resp.Uri = 'http://192.168.220.10/snapshot.jpg'
        media.GetSnapshotUri.return_value = snapshot_resp

        assert cam.setup() is True
        assert cam.is_connected is True
        assert cam.snapshot_uri == 'http://192.168.220.10/snapshot.jpg'
        assert cam.reconnect_attempts == 0

    @patch("cameras.onvif_camera.ONVIFCamera")
    def test_setup_no_profiles(self, MockONVIF, cam):
        mock_onvif = MagicMock()
        MockONVIF.return_value = mock_onvif
        media = MagicMock()
        mock_onvif.create_media_service.return_value = media
        media.GetProfiles.return_value = []

        assert cam.setup() is False

    @patch("cameras.onvif_camera.ONVIFCamera")
    def test_setup_exception(self, MockONVIF, cam):
        MockONVIF.side_effect = RuntimeError("connection refused")
        assert cam.setup() is False
        assert cam.is_connected is False


# ---------------------------------------------------------------------------
# capture_frame
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestONVIFCameraCaptureFrame:

    def test_not_connected_returns_none(self, cam):
        cam.is_connected = False
        assert cam.capture_frame() is None

    def test_no_snapshot_uri_returns_none(self, cam):
        cam.is_connected = True
        cam.snapshot_uri = None
        assert cam.capture_frame() is None

    @patch("cameras.onvif_camera.requests")
    def test_success_200(self, mock_requests, cam):
        cam.is_connected = True
        cam.snapshot_uri = 'http://192.168.220.10/snap.jpg'

        # Create a real JPEG-like response (minimal valid data for cv2.imdecode)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        import cv2
        # cv2 is mocked, so we need to mock imdecode
        cv2.imdecode.return_value = frame
        cv2.IMREAD_COLOR = 1

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'\xff\xd8\xff\xe0' + b'\x00' * 100  # fake JPEG
        mock_requests.get.return_value = mock_resp

        result = cam.capture_frame()
        assert result is not None

    @patch("cameras.onvif_camera.requests")
    def test_http_401_returns_none(self, mock_requests, cam):
        cam.is_connected = True
        cam.snapshot_uri = 'http://192.168.220.10/snap.jpg'

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_requests.get.return_value = mock_resp

        assert cam.capture_frame() is None

    @patch("cameras.onvif_camera.requests")
    def test_http_500_returns_none(self, mock_requests, cam):
        cam.is_connected = True
        cam.snapshot_uri = 'http://192.168.220.10/snap.jpg'

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_requests.get.return_value = mock_resp

        assert cam.capture_frame() is None

    @patch("cameras.onvif_camera.requests")
    def test_timeout_returns_none(self, mock_requests, cam):
        import requests
        cam.is_connected = True
        cam.snapshot_uri = 'http://192.168.220.10/snap.jpg'
        mock_requests.get.side_effect = requests.exceptions.Timeout("timeout")
        mock_requests.exceptions = requests.exceptions

        assert cam.capture_frame() is None

    @patch("cameras.onvif_camera.requests")
    def test_connection_error_returns_none(self, mock_requests, cam):
        import requests
        cam.is_connected = True
        cam.snapshot_uri = 'http://192.168.220.10/snap.jpg'
        mock_requests.get.side_effect = requests.exceptions.ConnectionError("refused")
        mock_requests.exceptions = requests.exceptions

        assert cam.capture_frame() is None

    @patch("cameras.onvif_camera.requests")
    def test_decode_failure_returns_none(self, mock_requests, cam):
        cam.is_connected = True
        cam.snapshot_uri = 'http://192.168.220.10/snap.jpg'

        import cv2
        cv2.imdecode.return_value = None  # decode fails

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'\x00' * 50  # corrupted data
        mock_requests.get.return_value = mock_resp

        assert cam.capture_frame() is None


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestONVIFCameraCleanup:

    def test_cleanup_clears_state(self, cam):
        cam.onvif_camera = MagicMock()
        cam.media_service = MagicMock()
        cam.snapshot_uri = 'http://example.com/snap'
        cam.is_connected = True

        cam.cleanup()

        assert cam.onvif_camera is None
        assert cam.media_service is None
        assert cam.snapshot_uri is None
        assert cam.is_connected is False


# ---------------------------------------------------------------------------
# reconnect
# ---------------------------------------------------------------------------

@pytest.mark.smoke
class TestONVIFCameraReconnect:

    @patch("time.sleep")
    def test_reconnect_calls_cleanup_and_setup(self, mock_sleep, cam):
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
class TestONVIFCameraInfo:

    def test_info_when_disconnected(self, cam):
        info = cam.get_camera_info()
        assert info['camera_id'] == 'cam-onvif-01'
        assert info['type'] == 'onvif'
        assert info['is_connected'] is False
        assert info['snapshot_uri_available'] is False

    def test_info_when_connected_with_device_info(self, cam):
        cam.is_connected = True
        cam.snapshot_uri = 'http://example.com/snap'
        cam.onvif_camera = MagicMock()
        device_info = MagicMock()
        device_info.Manufacturer = 'TestCo'
        device_info.Model = 'X200'
        device_info.FirmwareVersion = '1.0'
        device_info.SerialNumber = 'SN123'
        cam.onvif_camera.devicemgmt.GetDeviceInformation.return_value = device_info

        info = cam.get_camera_info()
        assert info['is_connected'] is True
        assert info['snapshot_uri_available'] is True
        assert info['manufacturer'] == 'TestCo'
        assert info['model'] == 'X200'

    def test_info_device_info_exception_handled(self, cam):
        cam.is_connected = True
        cam.snapshot_uri = 'http://example.com/snap'
        cam.onvif_camera = MagicMock()
        cam.onvif_camera.devicemgmt.GetDeviceInformation.side_effect = RuntimeError("timeout")

        info = cam.get_camera_info()
        assert info['is_connected'] is True
        # manufacturer not present because exception was caught
        assert 'manufacturer' not in info
