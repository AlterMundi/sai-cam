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


# ──────────────────────────────────────────────────────────────────────────────
# _restart_camera
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestRestartCamera:

    def test_restart_found_camera_success(self, mock_logger):
        """Restarting an active camera stops it and reinitializes."""
        svc = _make_service(mock_logger)
        # Create a mock camera instance
        mock_instance = MagicMock()
        mock_instance.config = {'id': 'cam1', 'type': 'rtsp', 'capture_interval': 60}
        svc.camera_instances['cam1'] = mock_instance

        # Mock the thread
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        svc.camera_threads['cam1'] = mock_thread

        def fake_init(cam_id, cam_config, is_retry=False):
            # Simulate successful reinitialization
            new_instance = MagicMock()
            new_instance.capture_images = MagicMock()
            svc.camera_instances[cam_id] = new_instance
            return True

        with patch.object(svc, '_try_initialize_camera', side_effect=fake_init):
            result = svc._restart_camera('cam1')

        assert result['ok'] is True
        assert result['action'] == 'restarted'
        mock_instance.stop.assert_called_once()

    def test_restart_failed_camera_queues_retry(self, mock_logger):
        """Restarting a failed camera resets its retry timer."""
        svc = _make_service(mock_logger)
        # Camera in failed_cameras, not camera_instances
        cam_config = {'id': 'cam1', 'type': 'rtsp', 'capture_interval': 60}
        svc.failed_cameras['cam1'] = (cam_config, 3, time.time() + 1000)

        result = svc._restart_camera('cam1')

        assert result['ok'] is True
        assert result['action'] == 'retry_queued'
        # Check that next_retry was reset to 0
        _, attempts, next_retry = svc.failed_cameras['cam1']
        assert attempts == 0
        assert next_retry == 0

    def test_restart_unknown_camera_returns_error(self, mock_logger):
        """Restarting an unknown camera returns an error."""
        svc = _make_service(mock_logger)
        result = svc._restart_camera('unknown-cam')
        assert 'error' in result
        assert 'not found' in result['error']

    def test_restart_camera_reinit_fails(self, mock_logger):
        """When reinitialization fails, return ok=False."""
        svc = _make_service(mock_logger)
        mock_instance = MagicMock()
        mock_instance.config = {'id': 'cam1', 'type': 'rtsp', 'capture_interval': 60}
        svc.camera_instances['cam1'] = mock_instance
        svc.camera_threads['cam1'] = MagicMock()

        with patch.object(svc, '_try_initialize_camera', return_value=False):
            result = svc._restart_camera('cam1')

        assert result['ok'] is False
        assert result['action'] == 'restart_failed'


# ──────────────────────────────────────────────────────────────────────────────
# cleanup
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestCameraServiceCleanup:

    @patch("camera_service.sys.exit")
    def test_cleanup_stops_all_cameras(self, mock_exit, mock_logger):
        """cleanup() calls stop() on all camera instances."""
        svc = _make_service(mock_logger)
        cam1 = MagicMock()
        cam2 = MagicMock()
        svc.camera_instances = {'cam1': cam1, 'cam2': cam2}

        svc.cleanup()

        assert svc.running is False
        cam1.stop.assert_called_once()
        cam2.stop.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("camera_service.sys.exit")
    def test_cleanup_when_no_cameras(self, mock_exit, mock_logger):
        """cleanup() works with no cameras."""
        svc = _make_service(mock_logger)
        svc.camera_instances = {}

        svc.cleanup()

        assert svc.running is False
        mock_exit.assert_called_once_with(0)


# ──────────────────────────────────────────────────────────────────────────────
# start_capture_threads
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestStartCaptureThreads:

    @patch("camera_service.Thread")
    def test_starts_threads_for_all_cameras(self, MockThread, mock_logger):
        """start_capture_threads() creates a thread for each camera."""
        svc = _make_service(mock_logger)
        cam1 = MagicMock()
        cam2 = MagicMock()
        svc.camera_instances = {'cam1': cam1, 'cam2': cam2}
        svc.camera_threads = {}

        mock_thread_instance = MagicMock()
        MockThread.return_value = mock_thread_instance

        svc.start_capture_threads()

        assert MockThread.call_count == 2
        assert mock_thread_instance.start.call_count == 2
        assert 'cam1' in svc.camera_threads
        assert 'cam2' in svc.camera_threads

    @patch("camera_service.Thread")
    def test_skips_already_running_threads(self, MockThread, mock_logger):
        """start_capture_threads() doesn't restart alive threads."""
        svc = _make_service(mock_logger)
        cam1 = MagicMock()
        svc.camera_instances = {'cam1': cam1}

        # Thread already running
        existing_thread = MagicMock()
        existing_thread.is_alive.return_value = True
        svc.camera_threads = {'cam1': existing_thread}

        svc.start_capture_threads()

        MockThread.assert_not_called()

    @patch("camera_service.Thread")
    def test_restarts_dead_threads(self, MockThread, mock_logger):
        """start_capture_threads() restarts dead threads."""
        svc = _make_service(mock_logger)
        cam1 = MagicMock()
        svc.camera_instances = {'cam1': cam1}

        # Thread is dead
        dead_thread = MagicMock()
        dead_thread.is_alive.return_value = False
        svc.camera_threads = {'cam1': dead_thread}

        mock_thread_instance = MagicMock()
        MockThread.return_value = mock_thread_instance

        svc.start_capture_threads()

        MockThread.assert_called_once()
        mock_thread_instance.start.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# disable_upload
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestDisableUpload:

    def test_disable_upload_sets_flag_false(self, mock_logger):
        """disable_upload() sets upload_enabled to False."""
        svc = _make_service(mock_logger)
        svc.upload_enabled = True

        svc.disable_upload()

        assert svc.upload_enabled is False

    def test_disable_upload_logs_message(self, mock_logger):
        """disable_upload() logs an info message."""
        svc = _make_service(mock_logger)
        svc.upload_enabled = True

        svc.disable_upload()

        # mock_logger is a real logger with a ListHandler, check records
        records = mock_logger._test_handler.records
        assert any('local save' in r.getMessage().lower() for r in records)


# ──────────────────────────────────────────────────────────────────────────────
# compress_image
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestCompressImage:

    def test_compress_image_returns_same_data(self, mock_logger):
        """compress_image() returns input data unchanged (current impl)."""
        svc = _make_service(mock_logger)
        data = b'\x00\x01\x02\x03\x04\x05'

        result = svc.compress_image(data)

        assert result == data

    def test_compress_image_handles_empty_data(self, mock_logger):
        """compress_image() handles empty data."""
        svc = _make_service(mock_logger)
        data = b''

        result = svc.compress_image(data)

        assert result == b''


# ──────────────────────────────────────────────────────────────────────────────
# CameraInstance.setup_camera
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestCameraInstanceSetup:

    def test_setup_camera_success(self, mock_logger):
        """setup_camera() returns True when camera.setup() succeeds."""
        inst = _make_camera_instance(mock_logger)
        # Replace the camera with a fresh MagicMock
        mock_cam = MagicMock()
        mock_cam.setup.return_value = True
        inst.camera = mock_cam

        result = inst.setup_camera()

        assert result is True
        mock_cam.setup.assert_called_once()

    def test_setup_camera_failure(self, mock_logger):
        """setup_camera() returns False when camera.setup() fails."""
        inst = _make_camera_instance(mock_logger)
        mock_cam = MagicMock()
        mock_cam.setup.return_value = False
        inst.camera = mock_cam

        result = inst.setup_camera()

        assert result is False

    def test_setup_camera_exception(self, mock_logger):
        """setup_camera() returns False and logs on exception."""
        inst = _make_camera_instance(mock_logger)
        mock_cam = MagicMock()
        mock_cam.setup.side_effect = RuntimeError("device busy")
        inst.camera = mock_cam

        result = inst.setup_camera()

        assert result is False
        # mock_logger is a real logger - check records for error
        records = mock_logger._test_handler.records
        assert any(r.levelno >= 40 for r in records)  # ERROR level


# ──────────────────────────────────────────────────────────────────────────────
# CameraInstance._get_cpu_temp
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.smoke
class TestGetCpuTemp:

    @patch("camera_service.psutil")
    def test_cpu_temp_from_cpu_thermal(self, mock_psutil, mock_logger):
        """_get_cpu_temp() returns temp from cpu_thermal zone."""
        inst = _make_camera_instance(mock_logger)
        temp_entry = MagicMock()
        temp_entry.current = 52.5
        mock_psutil.sensors_temperatures.return_value = {'cpu_thermal': [temp_entry]}

        result = inst._get_cpu_temp()

        assert result == 52.5

    @patch("camera_service.psutil")
    def test_cpu_temp_no_sensors(self, mock_psutil, mock_logger):
        """_get_cpu_temp() returns None when no sensors available."""
        inst = _make_camera_instance(mock_logger)
        mock_psutil.sensors_temperatures.return_value = {}

        result = inst._get_cpu_temp()

        assert result is None

    @patch("camera_service.psutil")
    def test_cpu_temp_exception(self, mock_psutil, mock_logger):
        """_get_cpu_temp() returns None on exception."""
        inst = _make_camera_instance(mock_logger)
        mock_psutil.sensors_temperatures.side_effect = RuntimeError("no sensors")

        result = inst._get_cpu_temp()

        assert result is None
