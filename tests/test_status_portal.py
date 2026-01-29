"""Tests for src/status_portal.py — Flask routes and helper functions."""

import json
import copy
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

# Import the Flask app and helpers
import status_portal
from status_portal import app


@pytest.fixture(autouse=True)
def _setup_portal(mock_logger):
    """Set module-level globals before every test."""
    status_portal.logger = mock_logger
    status_portal.config = {
        'device': {'id': 'test-node', 'location': 'Lab', 'description': 'Unit test'},
        'cameras': [
            {
                'id': 'cam1',
                'type': 'rtsp',
                'address': '192.168.220.10',
                'rtsp_url': 'rtsp://admin:secret@192.168.220.10/stream',
                'password': 'secret',
                'capture_interval': 120,
                'position': 'North',
            }
        ],
        'storage': {'base_path': '/opt/sai-cam/storage', 'max_size_gb': 10},
        'server': {'auth_token': 'tok-123', 'url': 'https://api.test/upload'},
        'monitoring': {'health_check_interval': 60},
    }
    app.config['TESTING'] = True
    yield


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


# ──────────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────────

class TestGetSystemInfo:

    @patch("status_portal.psutil")
    def test_returns_dict_structure(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 25.0
        mem = MagicMock()
        mem.percent = 40.0
        mem.used = 2 * 1024 ** 3
        mem.total = 8 * 1024 ** 3
        mock_psutil.virtual_memory.return_value = mem
        disk = MagicMock()
        disk.percent = 50.0
        disk.used = 10 * 1024 ** 3
        disk.total = 100 * 1024 ** 3
        mock_psutil.disk_usage.return_value = disk

        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch("os.path.exists", return_value=False):
                info = status_portal.get_system_info()

        assert 'cpu_percent' in info
        assert 'memory_percent' in info
        assert 'disk_percent' in info

    @patch("status_portal.psutil")
    def test_handles_no_temperature(self, mock_psutil):
        mock_psutil.cpu_percent.return_value = 10.0
        mem = MagicMock()
        mem.percent = 20.0
        mem.used = 1 * 1024 ** 3
        mem.total = 4 * 1024 ** 3
        mock_psutil.virtual_memory.return_value = mem
        disk = MagicMock()
        disk.percent = 30.0
        disk.used = 5 * 1024 ** 3
        disk.total = 50 * 1024 ** 3
        mock_psutil.disk_usage.return_value = disk

        with patch("os.path.exists", return_value=False):
            info = status_portal.get_system_info()
        assert info['temperature'] is None


class TestGetNetworkInfo:

    @patch("status_portal.subprocess")
    @patch("status_portal.psutil")
    def test_filters_lo_and_docker(self, mock_psutil, mock_subprocess):
        lo_addr = MagicMock()
        lo_addr.family = 2
        lo_addr.address = '127.0.0.1'
        eth_addr = MagicMock()
        eth_addr.family = 2
        eth_addr.address = '192.168.1.100'

        mock_psutil.net_if_addrs.return_value = {
            'lo': [lo_addr],
            'eth0': [eth_addr],
        }

        # Mock subprocess calls (ping, ip route)
        mock_subprocess.run.return_value = MagicMock(returncode=1, stdout='', stderr='')
        mock_subprocess.TimeoutExpired = Exception

        info = status_portal.get_network_info()
        assert 'lo' not in info.get('interfaces', {})
        assert 'eth0' in info.get('interfaces', {})

    @patch("status_portal.subprocess")
    @patch("status_portal.psutil")
    def test_upstream_online_offline(self, mock_psutil, mock_subprocess):
        mock_psutil.net_if_addrs.return_value = {}
        # First call is ping, second is ip route
        mock_subprocess.run.return_value = MagicMock(returncode=1, stdout='', stderr='')
        mock_subprocess.TimeoutExpired = Exception

        info = status_portal.get_network_info()
        assert info['upstream_online'] is False


class TestDetectFeatures:

    def test_returns_all_keys(self):
        features = status_portal.detect_features()
        expected_keys = {'wifi_ap', 'cameras', 'storage', 'monitoring', 'onvif', 'rtsp', 'usb_camera'}
        assert set(features.keys()) == expected_keys


class TestGetCameraStatus:

    @patch("status_portal.query_health_socket")
    def test_maps_health_socket_data(self, mock_socket):
        mock_socket.return_value = {
            'cameras': {
                'cam1': {
                    'state': 'healthy',
                    'thread_alive': True,
                    'consecutive_failures': 0,
                    'last_success_age': 30,
                }
            },
            'failed_cameras': {},
        }
        with patch("status_portal.Path") as MockPath:
            MockPath.return_value.exists.return_value = False
            cameras = status_portal.get_camera_status()

        assert len(cameras) == 1
        assert cameras[0]['id'] == 'cam1'
        assert cameras[0]['online'] is True

    @patch("status_portal.query_health_socket")
    def test_camera_offline_not_online(self, mock_socket):
        mock_socket.return_value = {
            'cameras': {
                'cam1': {
                    'state': 'offline',
                    'thread_alive': False,
                    'consecutive_failures': 5,
                    'last_success_age': 3600,
                }
            },
            'failed_cameras': {},
        }
        with patch("status_portal.Path") as MockPath:
            MockPath.return_value.exists.return_value = False
            cameras = status_portal.get_camera_status()

        assert cameras[0]['online'] is False
        assert cameras[0]['error'] == 'Offline'


class TestGetStorageInfo:

    @patch("status_portal.Path")
    def test_with_storage_path(self, MockPath):
        mock_path = MagicMock()
        MockPath.return_value = mock_path
        mock_path.exists.return_value = True

        # Storage images
        img_mock = MagicMock()
        img_mock.stat.return_value.st_size = 100 * 1024  # 100KB
        mock_path.glob.return_value = [img_mock, img_mock]

        # uploaded subdir
        uploaded_mock = MagicMock()
        uploaded_mock.exists.return_value = True
        uploaded_img = MagicMock()
        uploaded_img.stat.return_value.st_size = 50 * 1024
        uploaded_mock.glob.return_value = [uploaded_img]
        mock_path.__truediv__ = lambda self, x: uploaded_mock

        info = status_portal.get_storage_info()
        assert info is not None
        assert 'total_images' in info

    @patch("status_portal.Path")
    def test_without_storage_path(self, MockPath):
        mock_path = MagicMock()
        MockPath.return_value = mock_path
        mock_path.exists.return_value = False
        assert status_portal.get_storage_info() is None


# ──────────────────────────────────────────────────────────────────────────────
# GET routes
# ──────────────────────────────────────────────────────────────────────────────

class TestGetRoutes:

    @patch("status_portal.get_wifi_ap_info", return_value=None)
    @patch("status_portal.get_storage_info", return_value=None)
    @patch("status_portal.get_network_info", return_value={})
    @patch("status_portal.get_camera_status", return_value=[])
    @patch("status_portal.get_system_info", return_value={'cpu_percent': 10})
    @patch("status_portal.detect_features")
    @patch("status_portal.is_wifi_ap_active", return_value=False)
    def test_api_status_200(self, mock_wifi, mock_features, mock_sys, mock_cam, mock_net, mock_stor, mock_wifi_info, client):
        mock_features.return_value = {
            'wifi_ap': False, 'cameras': False, 'storage': False,
            'monitoring': True, 'onvif': False, 'rtsp': False, 'usb_camera': False,
        }
        resp = client.get('/api/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'node' in data
        assert 'data' in data

    @patch("status_portal.get_camera_status", return_value=[{'id': 'cam1'}])
    def test_api_cameras_returns_list(self, mock_cam, client):
        resp = client.get('/api/status/cameras')
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    @patch("status_portal.get_system_info", return_value={'cpu_percent': 5})
    def test_api_system_returns_metrics(self, mock_sys, client):
        resp = client.get('/api/status/system')
        assert resp.status_code == 200
        assert 'cpu_percent' in resp.get_json()

    @patch("status_portal.get_recent_logs", return_value=["line1", "line2"])
    def test_api_logs_returns_logs(self, mock_logs, client):
        resp = client.get('/api/logs?lines=10')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'logs' in data
        assert len(data['logs']) == 2

    def test_api_config_redacts_passwords(self, client):
        resp = client.get('/api/config')
        assert resp.status_code == 200
        data = resp.get_json()
        cam = data['cameras'][0]
        assert cam['password'] == '***'
        assert 'secret' not in cam.get('rtsp_url', '')

    def test_api_config_redacts_auth_token(self, client):
        resp = client.get('/api/config')
        data = resp.get_json()
        assert data['server']['auth_token'] == '***'

    @patch("status_portal.query_health_socket")
    def test_api_health_200(self, mock_socket, client):
        mock_socket.return_value = {'status': 'ok'}
        resp = client.get('/api/health')
        assert resp.status_code == 200

    @patch("status_portal.query_health_socket")
    def test_api_health_503_when_unavailable(self, mock_socket, client):
        mock_socket.return_value = None
        resp = client.get('/api/health')
        assert resp.status_code == 503


# ──────────────────────────────────────────────────────────────────────────────
# POST routes
# ──────────────────────────────────────────────────────────────────────────────

class TestPostRoutes:

    @patch("status_portal.send_camera_command")
    def test_force_capture_calls_command(self, mock_cmd, client):
        mock_cmd.return_value = {'ok': True, 'camera_id': 'cam1'}
        resp = client.post('/api/cameras/cam1/capture')
        assert resp.status_code == 200
        mock_cmd.assert_called_once_with('force_capture', 'cam1')

    @patch("status_portal.send_camera_command")
    def test_restart_calls_command(self, mock_cmd, client):
        mock_cmd.return_value = {'ok': True}
        resp = client.post('/api/cameras/cam1/restart')
        assert resp.status_code == 200
        mock_cmd.assert_called_once_with('restart_camera', 'cam1')

    @patch("status_portal.send_camera_command")
    def test_capture_503_when_unavailable(self, mock_cmd, client):
        mock_cmd.return_value = None
        resp = client.post('/api/cameras/cam1/capture')
        assert resp.status_code == 503

    @patch("status_portal.send_camera_command")
    def test_restart_503_when_unavailable(self, mock_cmd, client):
        mock_cmd.return_value = None
        resp = client.post('/api/cameras/cam1/restart')
        assert resp.status_code == 503

    @patch("builtins.open", side_effect=PermissionError("denied"))
    def test_position_permission_error(self, mock_open, client):
        resp = client.post('/api/cameras/cam1/position',
                          json={'position': 'East'},
                          content_type='application/json')
        assert resp.status_code == 403

    @patch("status_portal.yaml")
    def test_position_404_for_unknown_camera(self, mock_yaml, client, tmp_path):
        # Create a temp config file with no matching camera
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        app.config['CONFIG_PATH'] = str(config_file)
        mock_yaml.safe_load.return_value = {'cameras': [{'id': 'other_cam'}]}
        resp = client.post('/api/cameras/cam_unknown/position',
                          json={'position': 'West'},
                          content_type='application/json')
        assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Service status
# ──────────────────────────────────────────────────────────────────────────────

class TestServiceStatus:

    @patch("status_portal.subprocess")
    def test_service_active(self, mock_subprocess, client):
        active_result = MagicMock(returncode=0, stdout='active\n', stderr='')
        show_result = MagicMock(returncode=0, stdout='ActiveEnterTimestamp=Wed 2026-01-14 21:51:30 -03\n', stderr='')
        mock_subprocess.run.side_effect = [active_result, show_result]
        mock_subprocess.TimeoutExpired = Exception

        resp = client.get('/api/service/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['active'] is True

    @patch("status_portal.subprocess")
    def test_service_inactive(self, mock_subprocess, client):
        mock_subprocess.run.return_value = MagicMock(returncode=3, stdout='inactive\n', stderr='')
        mock_subprocess.TimeoutExpired = Exception

        resp = client.get('/api/service/status')
        data = resp.get_json()
        assert data['active'] is False
