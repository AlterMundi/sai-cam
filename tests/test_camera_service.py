"""Tests for CameraInstance and CameraService from src/camera_service.py."""

import time
from threading import Event
from unittest.mock import patch, MagicMock

import pytest

from camera_service import CameraService, CameraInstance


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_camera_instance(mock_logger):
    """Create a CameraInstance with all heavy deps mocked."""
    cam_config = {
        'id': 'cam-test-01',
        'type': 'rtsp',
        'rtsp_url': 'rtsp://admin:pw@192.168.1.10/stream',
        'capture_interval': 120,
    }
    global_config = {
        'device': {'id': 'node-01', 'location': 'Lab'},
        'advanced': {'reconnect_attempts': 3, 'polling_interval': 0.1},
    }
    storage = MagicMock()
    queue = MagicMock()

    with patch("camera_service.CameraStateTracker") as MockTracker, \
         patch("cameras.camera_factory.create_camera_from_config") as MockFactory:
        MockFactory.return_value = MagicMock()
        instance = CameraInstance(
            camera_id='cam-test-01',
            camera_config=cam_config,
            global_config=global_config,
            logger=mock_logger,
            storage_manager=storage,
            upload_queue=queue,
        )
    return instance


def _make_service(mock_logger):
    """Create a CameraService bypassing __init__ and manually setting required attrs."""
    svc = object.__new__(CameraService)
    svc.config = {
        'device': {'id': 'node-01', 'location': 'Lab'},
        'storage': {'base_path': '/tmp/test-storage', 'max_size_gb': 1, 'cleanup_threshold_gb': 0.8, 'retention_days': 7},
        'server': {'url': 'https://api.test/upload', 'auth_token': 'tok', 'ssl_verify': False, 'cert_path': '', 'timeout': 30},
        'monitoring': {'health_check_interval': 60, 'max_cpu_percent': 80, 'max_memory_percent': 85, 'restart_on_failure': False},
        'advanced': {'reconnect_attempts': 3, 'polling_interval': 0.1},
        'cameras': [],
        '_start_time': time.time(),
    }
    svc.logger = mock_logger
    svc.camera_instances = {}
    svc.camera_threads = {}
    svc.failed_cameras = {}
    svc.running = True
    svc.upload_queue = MagicMock()
    svc.storage_manager = MagicMock()
    svc.health_monitor = MagicMock()
    svc.health_monitor.metrics = {'check_count': 0, 'warning_count': 0, 'error_count': 0, 'last_check': 0}
    return svc


# ──────────────────────────────────────────────────────────────────────────────
# CameraInstance init
# ──────────────────────────────────────────────────────────────────────────────

class TestCameraInstanceInit:

    def test_stores_camera_id_and_config(self, mock_logger):
        inst = _make_camera_instance(mock_logger)
        assert inst.camera_id == 'cam-test-01'
        assert inst.config['type'] == 'rtsp'

    def test_capture_interval(self, mock_logger):
        inst = _make_camera_instance(mock_logger)
        assert inst.capture_interval == 120

    def test_force_capture_event_is_event(self, mock_logger):
        inst = _make_camera_instance(mock_logger)
        assert isinstance(inst.force_capture_event, Event)

    def test_stop_sets_running_false(self, mock_logger):
        inst = _make_camera_instance(mock_logger)
        inst.stop()
        assert inst.running is False


# ──────────────────────────────────────────────────────────────────────────────
# _handle_command
# ──────────────────────────────────────────────────────────────────────────────

class TestHandleCommand:

    def test_health_returns_health_data(self, mock_logger):
        svc = _make_service(mock_logger)
        with patch.object(svc, '_get_health_data', return_value={'status': 'ok'}):
            result = svc._handle_command({'action': 'health'})
        assert result == {'status': 'ok'}

    def test_force_capture_sets_event(self, mock_logger):
        svc = _make_service(mock_logger)
        inst = MagicMock()
        inst.force_capture_event = Event()
        svc.camera_instances['cam1'] = inst
        result = svc._handle_command({'action': 'force_capture', 'camera_id': 'cam1'})
        assert result['ok'] is True
        assert inst.force_capture_event.is_set()

    def test_force_capture_unknown_camera(self, mock_logger):
        svc = _make_service(mock_logger)
        result = svc._handle_command({'action': 'force_capture', 'camera_id': 'unknown'})
        assert 'error' in result

    def test_restart_camera_calls_method(self, mock_logger):
        svc = _make_service(mock_logger)
        with patch.object(svc, '_restart_camera', return_value={'ok': True}) as mock_restart:
            result = svc._handle_command({'action': 'restart_camera', 'camera_id': 'cam1'})
        mock_restart.assert_called_once_with('cam1')
        assert result['ok'] is True

    def test_unknown_action_returns_error(self, mock_logger):
        svc = _make_service(mock_logger)
        result = svc._handle_command({'action': 'explode'})
        assert 'error' in result


# ──────────────────────────────────────────────────────────────────────────────
# _record_camera_failure
# ──────────────────────────────────────────────────────────────────────────────

class TestRecordCameraFailure:

    def test_first_failure_attempts_1(self, mock_logger):
        svc = _make_service(mock_logger)
        svc._record_camera_failure('cam1', {'capture_interval': 60})
        _, attempts, _ = svc.failed_cameras['cam1']
        assert attempts == 1

    def test_subsequent_failure_increments(self, mock_logger):
        svc = _make_service(mock_logger)
        svc._record_camera_failure('cam1', {'capture_interval': 60})
        svc._record_camera_failure('cam1', {'capture_interval': 60})
        _, attempts, _ = svc.failed_cameras['cam1']
        assert attempts == 2

    def test_backoff_cap_at_12x(self, mock_logger):
        svc = _make_service(mock_logger)
        cam_config = {'capture_interval': 10}
        for _ in range(20):
            svc._record_camera_failure('cam1', cam_config)
        _, attempts, _ = svc.failed_cameras['cam1']
        # The multiplier is min(2^(attempts-1), 12)
        # After 20 failures, multiplier capped at 12
        assert attempts == 20


# ──────────────────────────────────────────────────────────────────────────────
# _get_health_data
# ──────────────────────────────────────────────────────────────────────────────

class TestGetHealthData:

    @patch("camera_service.psutil")
    def test_returns_expected_top_level_keys(self, mock_psutil, mock_logger):
        mock_psutil.cpu_percent.return_value = 10
        mem = MagicMock()
        mem.percent = 30
        mock_psutil.virtual_memory.return_value = mem
        disk = MagicMock()
        disk.percent = 40
        mock_psutil.disk_usage.return_value = disk

        svc = _make_service(mock_logger)
        data = svc._get_health_data()
        assert 'timestamp' in data
        assert 'version' in data
        assert 'system' in data
        assert 'cameras' in data
        assert 'failed_cameras' in data
        assert 'threads' in data
        assert 'health_monitor' in data

    @patch("camera_service.psutil")
    def test_includes_camera_state_data(self, mock_psutil, mock_logger):
        mock_psutil.cpu_percent.return_value = 10
        mem = MagicMock()
        mem.percent = 30
        mock_psutil.virtual_memory.return_value = mem
        disk = MagicMock()
        disk.percent = 40
        mock_psutil.disk_usage.return_value = disk

        svc = _make_service(mock_logger)
        # Add a mock camera instance with state tracker
        mock_instance = MagicMock()
        mock_instance.state_tracker.get_status.return_value = {'state': 'healthy', 'consecutive_failures': 0}
        svc.camera_instances['cam1'] = mock_instance
        svc.camera_threads['cam1'] = MagicMock(is_alive=MagicMock(return_value=True))

        data = svc._get_health_data()
        assert 'cam1' in data['cameras']
        assert data['cameras']['cam1']['state'] == 'healthy'
