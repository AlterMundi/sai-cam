"""Tests for src/logging_utils.py — redact_url_credentials, RateLimitedLogger, CameraStateTracker."""

import time
import logging
from unittest.mock import patch

import pytest

from logging_utils import redact_url_credentials, RateLimitedLogger, CameraStateTracker


# ──────────────────────────────────────────────────────────────────────────────
# redact_url_credentials
# ──────────────────────────────────────────────────────────────────────────────

class TestRedactUrlCredentials:

    def test_rtsp_url_redacted(self):
        url = "rtsp://admin:secret@192.168.1.10:554/stream"
        assert redact_url_credentials(url) == "rtsp://admin:***@192.168.1.10:554/stream"

    def test_http_url_redacted(self):
        url = "http://user:password123@example.com/path"
        assert redact_url_credentials(url) == "http://user:***@example.com/path"

    def test_https_url_redacted(self):
        url = "https://user:pass@host.com"
        assert redact_url_credentials(url) == "https://user:***@host.com"

    def test_no_credentials_unchanged(self):
        url = "rtsp://192.168.1.10:554/stream"
        assert redact_url_credentials(url) == url

    def test_none_passthrough(self):
        assert redact_url_credentials(None) is None

    def test_empty_passthrough(self):
        assert redact_url_credentials("") == ""

    def test_special_chars_in_password(self):
        """Password with special chars (no @ in password) gets redacted."""
        url = "rtsp://admin:p$ss!w0rd#@192.168.1.10:554/stream"
        result = redact_url_credentials(url)
        assert "***@192.168.1.10" in result
        assert "p$ss" not in result

    def test_plain_string_unchanged(self):
        assert redact_url_credentials("just a string") == "just a string"


# ──────────────────────────────────────────────────────────────────────────────
# RateLimitedLogger
# ──────────────────────────────────────────────────────────────────────────────

class TestRateLimitedLogger:

    def test_first_message_always_logged(self, mock_logger):
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("Camera offline", key="cam1")
        assert len(mock_logger._test_handler.records) == 1

    @patch("logging_utils.time")
    def test_second_within_interval_suppressed(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("Camera offline", key="cam1")
        mock_time.time.return_value = 1030.0  # +30s, still within interval
        rl.warning("Camera offline", key="cam1")
        assert len(mock_logger._test_handler.records) == 1

    @patch("logging_utils.time")
    def test_message_after_interval_logged(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("Camera offline", key="cam1")
        mock_time.time.return_value = 1061.0  # past interval
        rl.warning("Camera offline", key="cam1")
        assert len(mock_logger._test_handler.records) == 2

    @patch("logging_utils.time")
    def test_suppressed_count_in_format(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("offline", key="k1")
        mock_time.time.return_value = 1010.0
        rl.warning("offline", key="k1")  # suppressed
        mock_time.time.return_value = 1020.0
        rl.warning("offline", key="k1")  # suppressed
        mock_time.time.return_value = 1070.0
        rl.warning("offline", key="k1")  # logged with count
        assert len(mock_logger._test_handler.records) == 2
        assert "repeated 2x" in mock_logger._test_handler.records[1].getMessage()

    @patch("logging_utils.time")
    def test_different_keys_independent(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("msg A", key="keyA")
        rl.warning("msg B", key="keyB")
        assert len(mock_logger._test_handler.records) == 2

    @patch("logging_utils.time")
    def test_custom_interval_override(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("msg", key="k", interval=10)
        mock_time.time.return_value = 1011.0  # past custom 10s
        rl.warning("msg", key="k", interval=10)
        assert len(mock_logger._test_handler.records) == 2

    def test_clear_key(self, mock_logger):
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("msg", key="k1")
        rl.clear_key("k1")
        rl.warning("msg", key="k1")  # should log again
        assert len(mock_logger._test_handler.records) == 2

    def test_clear_all(self, mock_logger):
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("a", key="k1")
        rl.warning("b", key="k2")
        rl.clear_all()
        rl.warning("a", key="k1")
        rl.warning("b", key="k2")
        assert len(mock_logger._test_handler.records) == 4

    def test_debug_level(self, mock_logger):
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.debug("debug msg", key="d1")
        assert mock_logger._test_handler.records[0].levelno == logging.DEBUG

    def test_info_level(self, mock_logger):
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.info("info msg", key="i1")
        assert mock_logger._test_handler.records[0].levelno == logging.INFO

    def test_error_level(self, mock_logger):
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.error("error msg", key="e1")
        assert mock_logger._test_handler.records[0].levelno == logging.ERROR

    def test_critical_level(self, mock_logger):
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.critical("critical msg", key="c1")
        assert mock_logger._test_handler.records[0].levelno == logging.CRITICAL

    def test_key_defaults_to_message(self, mock_logger):
        """When no key given, the message text is used as key."""
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.warning("same msg")
        rl.warning("same msg")  # same key → suppressed
        assert len(mock_logger._test_handler.records) == 1

    @patch("logging_utils.time")
    def test_format_message_no_suppressed(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        rl = RateLimitedLogger(mock_logger, default_interval=60)
        rl.info("hello", key="k")
        assert "repeated" not in mock_logger._test_handler.records[0].getMessage()


# ──────────────────────────────────────────────────────────────────────────────
# CameraStateTracker
# ──────────────────────────────────────────────────────────────────────────────

class TestCameraStateTracker:

    def test_initial_state_healthy(self, mock_logger):
        t = CameraStateTracker("cam1", 60, mock_logger)
        assert t.state == CameraStateTracker.STATE_HEALTHY

    @patch("logging_utils.time")
    def test_one_failure_is_failing(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        t.record_failure("err")
        assert t.state == CameraStateTracker.STATE_FAILING

    @patch("logging_utils.time")
    def test_three_failures_is_offline(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        for _ in range(3):
            mock_time.time.return_value += 100
            t.record_failure("err")
        assert t.state == CameraStateTracker.STATE_OFFLINE

    @patch("logging_utils.time")
    def test_success_resets_to_healthy(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        t.record_failure("err")
        assert t.state == CameraStateTracker.STATE_FAILING
        t.record_success()
        assert t.state == CameraStateTracker.STATE_HEALTHY

    @patch("logging_utils.time")
    def test_backoff_multiplier_1x(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        assert t._backoff_multiplier == 1

    @patch("logging_utils.time")
    def test_backoff_doubles_after_failure(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        t.record_failure("err")
        assert t._backoff_multiplier == 2  # doubled from 1 to 2

    @patch("logging_utils.time")
    def test_backoff_progression(self, mock_time, mock_logger):
        """Backoff: 1 → 2 → 4 → 8 → 12 (cap)."""
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 10, mock_logger)
        expected = [2, 4, 8, 12, 12]
        for exp in expected:
            mock_time.time.return_value += 200  # past any backoff
            t.record_failure("err")
            assert t._backoff_multiplier == exp, f"Expected {exp}, got {t._backoff_multiplier}"

    @patch("logging_utils.time")
    def test_backoff_cap_at_12(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 10, mock_logger)
        for _ in range(20):
            mock_time.time.return_value += 500
            t.record_failure("err")
        assert t._backoff_multiplier == 12

    @patch("logging_utils.time")
    def test_should_attempt_capture_healthy(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        assert t.should_attempt_capture() is True

    @patch("logging_utils.time")
    def test_should_attempt_capture_during_backoff(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        t.record_failure("err")
        # Now we're at backoff — next attempt is scheduled ahead
        mock_time.time.return_value = 1001.0  # still within backoff
        assert t.should_attempt_capture() is False

    @patch("logging_utils.time")
    def test_get_status_dict_keys(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        status = t.get_status()
        expected_keys = {
            "camera_id", "state", "consecutive_failures",
            "backoff_multiplier", "current_backoff_seconds",
            "time_until_next_attempt", "last_success_age"
        }
        assert set(status.keys()) == expected_keys

    @patch("logging_utils.time")
    def test_record_failure_returns_true_first_time(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        result = t.record_failure("err")
        assert result is True

    @patch("logging_utils.time")
    def test_record_failure_returns_false_during_backoff(self, mock_time, mock_logger):
        mock_time.time.return_value = 1000.0
        t = CameraStateTracker("cam1", 60, mock_logger)
        t.record_failure("err")  # schedules next attempt
        mock_time.time.return_value = 1001.0  # still within backoff
        result = t.record_failure("err")
        assert result is False
