"""
Shared fixtures and import setup for sai-cam test suite.

Pre-mocks unavailable system packages (systemd, cv2, onvif) so that
test modules can import production code without hardware or root access.
"""

import os
import sys
import logging
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. Add src/ to sys.path so production modules are importable
# ---------------------------------------------------------------------------
_src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
_src_dir = os.path.abspath(_src_dir)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# ---------------------------------------------------------------------------
# 2. Pre-mock heavy / unavailable packages before any test imports them
# ---------------------------------------------------------------------------
_MOCK_MODULES = [
    'systemd',
    'systemd.daemon',
    'cv2',
    'onvif',
    'watchdog',
    'watchdog.observers',
    'watchdog.events',
]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# ---------------------------------------------------------------------------
# 3. Pytest fixtures available to all test files
# ---------------------------------------------------------------------------
import pytest


@pytest.fixture
def mock_logger():
    """A real logging.Logger wired to a list handler for assertions."""
    logger = logging.getLogger(f'test.{id(object())}')
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    class ListHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

    handler = ListHandler()
    logger.addHandler(handler)
    logger._test_handler = handler  # expose for assertions
    return logger


@pytest.fixture
def sample_global_config():
    """Minimal global config dict matching production YAML structure."""
    return {
        'device': {
            'id': 'test-node-01',
            'location': 'Test Lab',
            'description': 'Unit test node',
        },
        'storage': {
            'base_path': '/tmp/sai-cam-test/storage',
            'max_size_gb': 1,
            'cleanup_threshold_gb': 0.8,
            'retention_days': 7,
        },
        'server': {
            'url': 'https://api.example.com/upload',
            'auth_token': 'test-token-123',
            'ssl_verify': False,
            'cert_path': '/etc/ssl/certs/ca-certificates.crt',
            'timeout': 30,
        },
        'monitoring': {
            'health_check_interval': 60,
            'max_cpu_percent': 80,
            'max_memory_percent': 85,
            'max_disk_percent': 90,
            'restart_on_failure': False,
        },
        'advanced': {
            'polling_interval': 0.1,
            'reconnect_delay': 5,
            'reconnect_attempts': 3,
        },
        'logging': {
            'level': 'WARNING',
            'log_dir': '/tmp/sai-cam-test/logs',
            'log_file': 'test.log',
        },
        'cameras': [],
    }


@pytest.fixture
def sample_rtsp_camera_config():
    """Single RTSP camera config dict."""
    return {
        'id': 'cam-rtsp-01',
        'type': 'rtsp',
        'rtsp_url': 'rtsp://admin:secret@192.168.220.10:554/stream1',
        'resolution': [1920, 1080],
        'fps': 15,
        'capture_interval': 120,
        'position': 'North Tower',
        'username': 'admin',
        'password': 'secret',
    }


@pytest.fixture
def sample_usb_camera_config():
    """Single USB camera config dict."""
    return {
        'id': 'cam-usb-01',
        'type': 'usb',
        'device_path': '/dev/video0',
        'device_index': 0,
        'resolution': [1280, 720],
        'fps': 30,
        'capture_interval': 300,
    }


@pytest.fixture
def sample_onvif_camera_config():
    """Single ONVIF camera config dict."""
    return {
        'id': 'cam-onvif-01',
        'type': 'onvif',
        'address': '192.168.220.20',
        'username': 'admin',
        'password': 'secret',
        'resolution': [1920, 1080],
        'fps': 15,
        'capture_interval': 180,
        'position': 'South Gate',
    }


@pytest.fixture
def sample_cameras_list(sample_rtsp_camera_config, sample_usb_camera_config, sample_onvif_camera_config):
    """List of all three camera config dicts."""
    return [sample_rtsp_camera_config, sample_usb_camera_config, sample_onvif_camera_config]
