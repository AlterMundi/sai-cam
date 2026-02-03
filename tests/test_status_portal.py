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

# ──────────────────────────────────────────────────────────────────────────────
# Update routes
# ──────────────────────────────────────────────────────────────────────────────

class TestUpdateRoutes:

    @patch("status_portal.UPDATE_MANAGER_AVAILABLE", True)
    @patch("status_portal.get_update_info")
    def test_api_update_status_returns_info(self, mock_info, client):
        mock_info.return_value = {
            'status': 'up_to_date',
            'current_version': '0.2.9',
            'latest_available': '0.2.9',
            'update_available': False,
            'channel': 'stable',
            'consecutive_failures': 0,
            'last_check': '2026-02-01T10:00:00',
            'last_update': '',
            'previous_version': '',
        }
        resp = client.get('/api/update/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'up_to_date'
        assert data['current_version'] == '0.2.9'
        assert data['update_available'] is False

    @patch("status_portal.UPDATE_MANAGER_AVAILABLE", False)
    def test_api_update_status_501_when_unavailable(self, client):
        resp = client.get('/api/update/status')
        assert resp.status_code == 501
        assert 'error' in resp.get_json()

    @patch("status_portal.UPDATE_MANAGER_AVAILABLE", True)
    @patch("status_portal.get_update_info")
    def test_api_update_status_shows_update_available(self, mock_info, client):
        mock_info.return_value = {
            'status': 'up_to_date',
            'current_version': '0.2.8',
            'latest_available': '0.3.0',
            'update_available': True,
            'channel': 'stable',
            'consecutive_failures': 0,
            'last_check': '2026-02-01T10:00:00',
            'last_update': '',
            'previous_version': '',
        }
        resp = client.get('/api/update/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['update_available'] is True
        assert data['latest_available'] == '0.3.0'

    @patch("status_portal.UPDATE_MANAGER_AVAILABLE", True)
    @patch("status_portal.get_update_info")
    @patch("status_portal.get_wifi_ap_info", return_value=None)
    @patch("status_portal.get_storage_info", return_value=None)
    @patch("status_portal.get_network_info", return_value={})
    @patch("status_portal.get_camera_status", return_value=[])
    @patch("status_portal.get_system_info", return_value={'cpu_percent': 10})
    @patch("status_portal.detect_features")
    @patch("status_portal.is_wifi_ap_active", return_value=False)
    def test_api_status_includes_update_field(self, mock_wifi, mock_feat, mock_sys,
                                               mock_cam, mock_net, mock_stor,
                                               mock_wifi_info, mock_update, client):
        mock_feat.return_value = {
            'wifi_ap': False, 'cameras': False, 'storage': False,
            'monitoring': True, 'onvif': False, 'rtsp': False, 'usb_camera': False,
        }
        mock_update.return_value = {
            'status': 'updated', 'current_version': '0.2.9',
            'latest_available': '0.2.9', 'update_available': False,
            'channel': 'stable', 'consecutive_failures': 0,
            'last_check': '', 'last_update': '', 'previous_version': '',
        }
        resp = client.get('/api/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'update' in data['data']
        assert data['data']['update']['status'] == 'updated'


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


# ──────────────────────────────────────────────────────────────────────────────
# _tail_file helper
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestTailFile:

    def test_tail_file_returns_last_lines(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("\n".join([f"line{i}" for i in range(100)]))

        result = status_portal._tail_file(log_file, lines=10)
        assert len(result) == 10
        assert result[-1] == "line99"

    def test_tail_file_empty_file(self, tmp_path):
        log_file = tmp_path / "empty.log"
        log_file.write_text("")

        result = status_portal._tail_file(log_file, lines=10)
        assert result == []

    def test_tail_file_missing_file(self, tmp_path):
        missing = tmp_path / "missing.log"
        result = status_portal._tail_file(missing, lines=10)
        assert result == []

    def test_tail_file_fewer_lines_than_requested(self, tmp_path):
        log_file = tmp_path / "small.log"
        log_file.write_text("line1\nline2\nline3\n")

        result = status_portal._tail_file(log_file, lines=10)
        assert len(result) == 3


# ──────────────────────────────────────────────────────────────────────────────
# Fleet Auth
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestFleetAuth:

    def test_fleet_auth_rejects_missing_token(self, client):
        status_portal.config['fleet'] = {'token': 'secret-token'}
        resp = client.post('/api/fleet/service/restart')
        assert resp.status_code == 401

    def test_fleet_auth_rejects_wrong_token(self, client):
        status_portal.config['fleet'] = {'token': 'secret-token'}
        resp = client.post('/api/fleet/service/restart',
                          headers={'Authorization': 'Bearer wrong-token'})
        assert resp.status_code == 401

    def test_fleet_auth_rejects_when_not_configured(self, client):
        status_portal.config['fleet'] = {}
        resp = client.post('/api/fleet/service/restart',
                          headers={'Authorization': 'Bearer any'})
        assert resp.status_code == 503


# ──────────────────────────────────────────────────────────────────────────────
# Fleet Routes
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestFleetRoutes:

    def test_fleet_ping_no_auth_required(self, client):
        """Ping is public for discovery."""
        resp = client.get('/api/fleet/ping')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert 'version' in data
        assert 'node_id' in data

    @patch("status_portal.subprocess")
    def test_fleet_update_apply_success(self, mock_subprocess, client):
        status_portal.config['fleet'] = {'token': 'tok'}
        # is-active returns non-zero (not running)
        mock_subprocess.run.return_value = MagicMock(returncode=3)
        mock_subprocess.Popen = MagicMock()
        mock_subprocess.DEVNULL = -1

        resp = client.post('/api/fleet/update/apply',
                          headers={'Authorization': 'Bearer tok'})
        assert resp.status_code == 200
        assert resp.get_json()['triggered'] is True

    @patch("status_portal.subprocess")
    def test_fleet_update_apply_already_running(self, mock_subprocess, client):
        status_portal.config['fleet'] = {'token': 'tok'}
        mock_subprocess.run.return_value = MagicMock(returncode=0)

        resp = client.post('/api/fleet/update/apply',
                          headers={'Authorization': 'Bearer tok'})
        assert resp.status_code == 409

    @patch("status_portal.subprocess")
    def test_fleet_service_restart(self, mock_subprocess, client):
        status_portal.config['fleet'] = {'token': 'tok'}
        mock_subprocess.Popen = MagicMock()
        mock_subprocess.DEVNULL = -1

        resp = client.post('/api/fleet/service/restart',
                          headers={'Authorization': 'Bearer tok'})
        assert resp.status_code == 200
        assert resp.get_json()['triggered'] is True

    @patch("status_portal.subprocess")
    def test_fleet_reboot(self, mock_subprocess, client):
        status_portal.config['fleet'] = {'token': 'tok'}
        mock_subprocess.Popen = MagicMock()
        mock_subprocess.DEVNULL = -1

        resp = client.post('/api/fleet/reboot',
                          headers={'Authorization': 'Bearer tok'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['scheduled'] is True
        assert data['delay'] == '1 min'

    @patch("status_portal.yaml")
    def test_fleet_config_allowed_key(self, mock_yaml, client, tmp_path):
        status_portal.config['fleet'] = {
            'token': 'tok',
            'allowed_config_keys': ['updates.channel', 'logging.level']
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text("updates:\n  channel: stable\n")
        app.config['CONFIG_PATH'] = str(config_file)
        mock_yaml.safe_load.return_value = {'updates': {'channel': 'stable'}}

        with patch("builtins.open", MagicMock()):
            resp = client.post('/api/fleet/config',
                              headers={'Authorization': 'Bearer tok'},
                              json={'key': 'updates.channel', 'value': 'beta'},
                              content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

    def test_fleet_config_forbidden_key(self, client):
        status_portal.config['fleet'] = {
            'token': 'tok',
            'allowed_config_keys': ['updates.channel']
        }

        resp = client.post('/api/fleet/config',
                          headers={'Authorization': 'Bearer tok'},
                          json={'key': 'server.auth_token', 'value': 'hacked'},
                          content_type='application/json')
        assert resp.status_code == 403

    def test_fleet_config_missing_body(self, client):
        status_portal.config['fleet'] = {'token': 'tok'}

        resp = client.post('/api/fleet/config',
                          headers={'Authorization': 'Bearer tok'},
                          content_type='application/json')
        assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Health Sub-Routes
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestHealthSubRoutes:

    @patch("status_portal.query_health_socket")
    def test_health_cameras_returns_camera_data(self, mock_socket, client):
        mock_socket.return_value = {
            'cameras': {'cam1': {'state': 'healthy'}},
            'failed_cameras': {},
            'timestamp': '2026-01-01T00:00:00',
        }
        resp = client.get('/api/health/cameras')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'cameras' in data
        assert 'cam1' in data['cameras']

    @patch("status_portal.query_health_socket")
    def test_health_cameras_503_when_unavailable(self, mock_socket, client):
        mock_socket.return_value = None
        resp = client.get('/api/health/cameras')
        assert resp.status_code == 503

    @patch("status_portal.query_health_socket")
    def test_health_threads_returns_thread_data(self, mock_socket, client):
        mock_socket.return_value = {
            'threads': {'total': 2, 'alive': 2},
            'timestamp': '2026-01-01T00:00:00',
        }
        resp = client.get('/api/health/threads')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'threads' in data
        assert data['threads']['total'] == 2

    @patch("status_portal.query_health_socket")
    def test_health_threads_503_when_unavailable(self, mock_socket, client):
        mock_socket.return_value = None
        resp = client.get('/api/health/threads')
        assert resp.status_code == 503

    @patch("status_portal.query_health_socket")
    def test_health_system_returns_system_data(self, mock_socket, client):
        mock_socket.return_value = {
            'system': {'cpu_percent': 10, 'memory_percent': 30},
            'health_monitor': {'check_count': 5},
            'uptime_seconds': 3600,
            'version': '0.2.9',
            'timestamp': '2026-01-01T00:00:00',
        }
        resp = client.get('/api/health/system')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'system' in data
        assert data['system']['cpu_percent'] == 10

    @patch("status_portal.query_health_socket")
    def test_health_system_503_when_unavailable(self, mock_socket, client):
        mock_socket.return_value = None
        resp = client.get('/api/health/system')
        assert resp.status_code == 503


# ──────────────────────────────────────────────────────────────────────────────
# Log Level Routes
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestLogLevelRoutes:

    def test_get_log_level(self, client):
        status_portal.config['logging'] = {'level': 'INFO'}
        resp = client.get('/api/log_level')
        assert resp.status_code == 200
        assert resp.get_json()['level'] == 'INFO'

    def test_get_log_level_default(self, client):
        status_portal.config.pop('logging', None)
        resp = client.get('/api/log_level')
        assert resp.status_code == 200
        assert resp.get_json()['level'] == 'WARNING'

    def test_set_log_level_invalid(self, client):
        resp = client.post('/api/log_level',
                          json={'level': 'TRACE'},
                          content_type='application/json')
        assert resp.status_code == 400

    @patch("status_portal.subprocess")
    @patch("status_portal.os.kill")
    @patch("status_portal.load_config")
    def test_set_log_level_success(self, mock_load, mock_kill, mock_subprocess, client, tmp_path):
        """Test setting log level (integration-style with real temp file)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("logging:\n  level: 'WARNING'\n")

        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout='12345\n')

        # Patch Path to point to our temp file
        original_path = status_portal.Path

        def patched_path(p):
            if p == '/etc/sai-cam/config.yaml':
                return original_path(config_file)
            return original_path(p)

        with patch.object(status_portal, 'Path', side_effect=patched_path):
            resp = client.post('/api/log_level',
                              json={'level': 'DEBUG'},
                              content_type='application/json')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['level'] == 'DEBUG'


# ──────────────────────────────────────────────────────────────────────────────
# WiFi AP Routes
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestWifiApRoutes:

    @patch("status_portal.subprocess")
    def test_wifi_enable_success(self, mock_subprocess, client):
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        mock_subprocess.TimeoutExpired = Exception

        resp = client.post('/api/wifi_ap/enable')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    @patch("status_portal.subprocess")
    def test_wifi_enable_failure(self, mock_subprocess, client):
        mock_subprocess.run.return_value = MagicMock(returncode=1, stdout='', stderr='connection failed')
        mock_subprocess.TimeoutExpired = Exception

        resp = client.post('/api/wifi_ap/enable')
        assert resp.status_code == 500
        data = resp.get_json()
        assert data['success'] is False

    @patch("status_portal.subprocess")
    def test_wifi_disable_success(self, mock_subprocess, client):
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout='', stderr='')
        mock_subprocess.TimeoutExpired = Exception

        resp = client.post('/api/wifi_ap/disable')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    @patch("status_portal.subprocess")
    def test_wifi_disable_timeout(self, mock_subprocess, client):
        mock_subprocess.run.side_effect = Exception("timeout")  # simulating TimeoutExpired
        mock_subprocess.TimeoutExpired = Exception

        resp = client.post('/api/wifi_ap/disable')
        assert resp.status_code == 500


# ──────────────────────────────────────────────────────────────────────────────
# api_logs bounds
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestApiLogsBounds:

    @patch("status_portal.get_recent_logs", return_value=["line1"])
    def test_logs_negative_clamped(self, mock_logs, client):
        resp = client.get('/api/logs?lines=-10')
        assert resp.status_code == 200
        mock_logs.assert_called_with(1)  # Clamped to 1

    @patch("status_portal.get_recent_logs", return_value=["line1"])
    def test_logs_huge_clamped(self, mock_logs, client):
        resp = client.get('/api/logs?lines=99999')
        assert resp.status_code == 200
        mock_logs.assert_called_with(1000)  # Clamped to 1000

    @patch("status_portal.get_recent_logs", return_value=["line1"])
    def test_logs_invalid_uses_default(self, mock_logs, client):
        resp = client.get('/api/logs?lines=not_a_number')
        assert resp.status_code == 200
        mock_logs.assert_called_with(50)  # Default


# ──────────────────────────────────────────────────────────────────────────────
# api_latest_image
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestApiLatestImage:

    @patch("status_portal.Path")
    def test_latest_image_storage_not_found(self, MockPath, client):
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        MockPath.return_value = mock_path

        resp = client.get('/api/images/cam1/latest')
        assert resp.status_code == 404

    @patch("status_portal.Path")
    def test_latest_image_no_images(self, MockPath, client):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.glob.return_value = []
        # uploaded subpath
        uploaded = MagicMock()
        uploaded.exists.return_value = True
        uploaded.glob.return_value = []
        mock_path.__truediv__ = lambda self, x: uploaded
        MockPath.return_value = mock_path

        resp = client.get('/api/images/cam1/latest')
        assert resp.status_code == 404

    @patch("status_portal.send_from_directory")
    @patch("status_portal.Path")
    def test_latest_image_found(self, MockPath, mock_send, client):
        # Create mock image file
        mock_img = MagicMock()
        mock_img.name = 'cam1_2026-01-01_00-00-00.jpg'
        mock_img.parent = Path('/opt/sai-cam/storage')
        mock_stat = MagicMock()
        mock_stat.st_mtime = 1000
        mock_img.stat.return_value = mock_stat

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.glob.return_value = [mock_img]

        uploaded = MagicMock()
        uploaded.exists.return_value = False
        mock_path.__truediv__ = lambda self, x: uploaded

        MockPath.return_value = mock_path
        mock_send.return_value = "image data"

        resp = client.get('/api/images/cam1/latest')
        # Should call send_from_directory
        mock_send.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# query_health_socket
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestQueryHealthSocket:

    @patch("status_portal.os.path.exists")
    def test_socket_not_found(self, mock_exists):
        mock_exists.return_value = False
        result = status_portal.query_health_socket()
        assert result is None

    @patch("status_portal.socket")
    @patch("status_portal.os.path.exists")
    def test_socket_connection_error(self, mock_exists, mock_socket_mod):
        mock_exists.return_value = True
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = ConnectionRefusedError("refused")
        mock_socket_mod.socket.return_value = mock_socket
        mock_socket_mod.AF_UNIX = 1
        mock_socket_mod.SOCK_STREAM = 1

        result = status_portal.query_health_socket()
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# send_camera_command
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestSendCameraCommand:

    @patch("status_portal.os.path.exists")
    def test_socket_not_found(self, mock_exists):
        mock_exists.return_value = False
        result = status_portal.send_camera_command('restart_camera', 'cam1')
        assert result is None

    @patch("status_portal.socket")
    @patch("status_portal.os.path.exists")
    def test_socket_error_returns_error_dict(self, mock_exists, mock_socket_mod):
        mock_exists.return_value = True
        mock_socket = MagicMock()
        mock_socket.connect.side_effect = ConnectionRefusedError("refused")
        mock_socket_mod.socket.return_value = mock_socket
        mock_socket_mod.AF_UNIX = 1
        mock_socket_mod.SOCK_STREAM = 1

        result = status_portal.send_camera_command('restart_camera', 'cam1')
        assert 'error' in result
