"""Tests for HealthMonitor from src/camera_service.py."""

import time
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from camera_service import HealthMonitor


def _make_monitor(mock_logger, config_overrides=None, restart_callback=None):
    config = {
        'health_check_interval': 60,
        'max_cpu_percent': 80,
        'max_memory_percent': 85,
        'max_disk_percent': 90,
        'restart_on_failure': False,
    }
    if config_overrides:
        config.update(config_overrides)
    return HealthMonitor(config, mock_logger, restart_callback or MagicMock())


# ──────────────────────────────────────────────────────────────────────────────
# Constructor
# ──────────────────────────────────────────────────────────────────────────────

class TestHealthMonitorInit:

    def test_initial_metrics_dict(self, mock_logger):
        hm = _make_monitor(mock_logger)
        assert hm.metrics['check_count'] == 0
        assert hm.metrics['warning_count'] == 0
        assert hm.metrics['error_count'] == 0
        assert 'start_time' in hm.metrics

    def test_stores_config_and_callback(self, mock_logger):
        cb = MagicMock()
        hm = _make_monitor(mock_logger, restart_callback=cb)
        assert hm.config['max_cpu_percent'] == 80
        assert hm.restart_callback is cb


# ──────────────────────────────────────────────────────────────────────────────
# check_system_health
# ──────────────────────────────────────────────────────────────────────────────

class TestCheckSystemHealth:

    @patch("camera_service.psutil")
    def test_increments_check_count(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=10, mem=30, disk=50)
        hm = _make_monitor(mock_logger)
        hm.check_system_health()
        assert hm.metrics['check_count'] == 1

    @patch("camera_service.psutil")
    def test_high_cpu_warns(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=95, mem=30, disk=50)
        hm = _make_monitor(mock_logger)
        hm.check_system_health()
        assert hm.metrics['warning_count'] >= 1
        warnings = [r for r in mock_logger._test_handler.records if r.levelno >= 30]
        assert any("CPU" in r.getMessage() for r in warnings)

    @patch("camera_service.psutil")
    def test_normal_cpu_no_warn(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=10, mem=30, disk=50)
        hm = _make_monitor(mock_logger)
        hm.check_system_health()
        assert hm.metrics['warning_count'] == 0

    @patch("camera_service.psutil")
    def test_high_memory_warns(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=10, mem=95, disk=50)
        hm = _make_monitor(mock_logger)
        hm.check_system_health()
        warnings = [r for r in mock_logger._test_handler.records if r.levelno >= 30]
        assert any("memory" in r.getMessage().lower() for r in warnings)

    @patch("camera_service.psutil")
    def test_high_disk_warns(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=10, mem=30, disk=95)
        hm = _make_monitor(mock_logger)
        hm.check_system_health()
        warnings = [r for r in mock_logger._test_handler.records if r.levelno >= 30]
        assert any("disk" in r.getMessage().lower() for r in warnings)

    @patch("camera_service.psutil")
    def test_high_temp_warns(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=10, mem=30, disk=50, temp=85.0)
        hm = _make_monitor(mock_logger)
        hm.check_system_health()
        warnings = [r for r in mock_logger._test_handler.records if r.levelno >= 30]
        assert any("temperature" in r.getMessage().lower() for r in warnings)

    @patch("camera_service.psutil")
    def test_no_temp_sensors_ok(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=10, mem=30, disk=50, temp=None)
        hm = _make_monitor(mock_logger)
        hm.check_system_health()  # should not raise
        assert hm.metrics['error_count'] == 0

    @patch("camera_service.psutil")
    def test_restart_on_failure_triggers_callback(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=95, mem=95, disk=50)
        cb = MagicMock()
        hm = _make_monitor(mock_logger, config_overrides={'restart_on_failure': True}, restart_callback=cb)
        hm.check_system_health()
        cb.assert_called_once()

    @patch("camera_service.psutil")
    def test_restart_on_failure_false_skips_callback(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=95, mem=95, disk=50)
        cb = MagicMock()
        hm = _make_monitor(mock_logger, config_overrides={'restart_on_failure': False}, restart_callback=cb)
        hm.check_system_health()
        cb.assert_not_called()

    @patch("camera_service.psutil")
    def test_exception_increments_error_count(self, mock_psutil, mock_logger):
        mock_psutil.cpu_percent.side_effect = RuntimeError("boom")
        hm = _make_monitor(mock_logger)
        hm.check_system_health()
        assert hm.metrics['error_count'] == 1

    @patch("camera_service.psutil")
    def test_periodic_logging_at_count_60(self, mock_psutil, mock_logger):
        _setup_psutil(mock_psutil, cpu=10, mem=30, disk=50)
        hm = _make_monitor(mock_logger)
        hm.metrics['check_count'] = 59  # next check will be 60
        hm.check_system_health()
        info_records = [r for r in mock_logger._test_handler.records if r.levelno == 20]
        assert any("Health metrics" in r.getMessage() for r in info_records)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _setup_psutil(mock_psutil, cpu=10, mem=30, disk=50, temp=None):
    """Configure mock psutil with given resource percentages."""
    mock_psutil.cpu_percent.return_value = cpu

    mem_info = MagicMock()
    mem_info.percent = mem
    mock_psutil.virtual_memory.return_value = mem_info

    disk_info = MagicMock()
    disk_info.percent = disk
    mock_psutil.disk_usage.return_value = disk_info

    if temp is not None:
        entry = MagicMock()
        entry.current = temp
        mock_psutil.sensors_temperatures.return_value = {'cpu_thermal': [entry]}
    else:
        mock_psutil.sensors_temperatures.return_value = {}

    # Ensure hasattr check passes
    mock_psutil.sensors_temperatures.__name__ = 'sensors_temperatures'
