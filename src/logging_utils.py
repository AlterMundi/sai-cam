"""
Logging Utilities for SAI-Cam

Provides rate-limited logging and other logging utilities to prevent
log spam from repeated errors (e.g., offline cameras).
"""

import time
import logging
from typing import Optional, Dict, Any
from threading import Lock


class RateLimitedLogger:
    """
    A wrapper around a logger that rate-limits repeated messages.

    Same message (identified by a key) will only be logged once per interval.
    Useful for preventing log spam from cameras that are offline or failing repeatedly.

    Usage:
        rl_logger = RateLimitedLogger(logger, default_interval=60)
        rl_logger.warning("Camera offline", key="cam1_offline")  # Logged
        rl_logger.warning("Camera offline", key="cam1_offline")  # Suppressed
        # ... 60 seconds later ...
        rl_logger.warning("Camera offline", key="cam1_offline")  # Logged again
    """

    def __init__(self, logger: logging.Logger, default_interval: float = 60.0):
        """
        Initialize rate-limited logger.

        Args:
            logger: The underlying logger to wrap
            default_interval: Default interval in seconds between repeated logs
        """
        self.logger = logger
        self.default_interval = default_interval
        self._last_logged: Dict[str, float] = {}
        self._suppressed_counts: Dict[str, int] = {}
        self._lock = Lock()

    def _should_log(self, key: str, interval: Optional[float] = None) -> tuple:
        """Check if message should be logged based on rate limiting.

        Returns:
            tuple: (should_log: bool, suppressed_count: int)
        """
        now = time.time()
        interval = interval if interval is not None else self.default_interval

        with self._lock:
            last_time = self._last_logged.get(key, 0)
            if now - last_time >= interval:
                # Log the suppressed count if any
                suppressed = self._suppressed_counts.get(key, 0)
                self._last_logged[key] = now
                self._suppressed_counts[key] = 0
                return (True, suppressed)
            else:
                self._suppressed_counts[key] = self._suppressed_counts.get(key, 0) + 1
                return (False, 0)

    def _format_message(self, msg: str, suppressed: int) -> str:
        """Add suppressed count to message if applicable."""
        if suppressed > 0:
            return f"{msg} (repeated {suppressed}x since last log)"
        return msg

    def debug(self, msg: str, key: Optional[str] = None, interval: Optional[float] = None, **kwargs):
        """Rate-limited debug log."""
        key = key or msg
        should_log, suppressed = self._should_log(key, interval)
        if should_log:
            self.logger.debug(self._format_message(msg, suppressed), **kwargs)

    def info(self, msg: str, key: Optional[str] = None, interval: Optional[float] = None, **kwargs):
        """Rate-limited info log."""
        key = key or msg
        should_log, suppressed = self._should_log(key, interval)
        if should_log:
            self.logger.info(self._format_message(msg, suppressed), **kwargs)

    def warning(self, msg: str, key: Optional[str] = None, interval: Optional[float] = None, **kwargs):
        """Rate-limited warning log."""
        key = key or msg
        should_log, suppressed = self._should_log(key, interval)
        if should_log:
            self.logger.warning(self._format_message(msg, suppressed), **kwargs)

    def error(self, msg: str, key: Optional[str] = None, interval: Optional[float] = None, **kwargs):
        """Rate-limited error log."""
        key = key or msg
        should_log, suppressed = self._should_log(key, interval)
        if should_log:
            self.logger.error(self._format_message(msg, suppressed), **kwargs)

    def critical(self, msg: str, key: Optional[str] = None, interval: Optional[float] = None, **kwargs):
        """Rate-limited critical log."""
        key = key or msg
        should_log, suppressed = self._should_log(key, interval)
        if should_log:
            self.logger.critical(self._format_message(msg, suppressed), **kwargs)

    def clear_key(self, key: str):
        """Clear rate limit state for a specific key (e.g., when camera recovers)."""
        with self._lock:
            self._last_logged.pop(key, None)
            self._suppressed_counts.pop(key, None)

    def clear_all(self):
        """Clear all rate limit state."""
        with self._lock:
            self._last_logged.clear()
            self._suppressed_counts.clear()


class CameraStateTracker:
    """
    Tracks camera state and manages backoff for failed cameras.

    When a camera fails, implements exponential backoff based on capture_interval.
    """

    # Camera states
    STATE_HEALTHY = "healthy"
    STATE_FAILING = "failing"
    STATE_OFFLINE = "offline"

    def __init__(self, camera_id: str, capture_interval: int, logger: logging.Logger):
        """
        Initialize camera state tracker.

        Args:
            camera_id: Camera identifier
            capture_interval: Normal capture interval in seconds
            logger: Logger instance
        """
        self.camera_id = camera_id
        self.capture_interval = capture_interval
        self.logger = logger
        self.rl_logger = RateLimitedLogger(logger, default_interval=capture_interval)

        self._state = self.STATE_HEALTHY
        self._consecutive_failures = 0
        self._last_success_time = time.time()
        self._next_attempt_time = 0
        self._backoff_multiplier = 1
        self._max_backoff_multiplier = 12  # Max 12x capture_interval between retries
        self._lock = Lock()

    @property
    def state(self) -> str:
        """Get current camera state."""
        return self._state

    @property
    def current_backoff(self) -> int:
        """Get current backoff interval in seconds."""
        return self.capture_interval * self._backoff_multiplier

    def record_success(self):
        """Record successful capture - resets backoff and state."""
        with self._lock:
            if self._state != self.STATE_HEALTHY:
                self.logger.info(
                    f"Camera {self.camera_id}: recovered after {self._consecutive_failures} failures"
                )
                # Clear rate limit keys so next error gets logged immediately
                self.rl_logger.clear_key(f"{self.camera_id}_offline")
                self.rl_logger.clear_key(f"{self.camera_id}_failure")

            self._state = self.STATE_HEALTHY
            self._consecutive_failures = 0
            self._last_success_time = time.time()
            self._backoff_multiplier = 1
            self._next_attempt_time = 0

    def record_failure(self, error_msg: str = "capture failed") -> bool:
        """
        Record capture failure.

        Args:
            error_msg: Error description for logging

        Returns:
            True if should attempt reconnection now, False if in backoff period
        """
        with self._lock:
            self._consecutive_failures += 1
            now = time.time()

            # Determine new state based on failure count
            if self._consecutive_failures >= 3:
                new_state = self.STATE_OFFLINE
            else:
                new_state = self.STATE_FAILING

            # Log state transition
            if new_state != self._state:
                if new_state == self.STATE_OFFLINE:
                    self.rl_logger.warning(
                        f"Camera {self.camera_id}: marked offline after {self._consecutive_failures} consecutive failures - "
                        f"will retry every {self.current_backoff}s",
                        key=f"{self.camera_id}_offline"
                    )
                else:
                    self.logger.warning(
                        f"Camera {self.camera_id}: {error_msg} (failure {self._consecutive_failures})"
                    )
                self._state = new_state
            else:
                # Rate-limited logging for repeated failures
                self.rl_logger.warning(
                    f"Camera {self.camera_id}: still offline, next retry in {self.current_backoff}s",
                    key=f"{self.camera_id}_failure",
                    interval=self.current_backoff
                )

            # Check if we should attempt now or wait
            if now < self._next_attempt_time:
                return False  # Still in backoff period

            # Schedule next attempt with exponential backoff
            self._next_attempt_time = now + self.current_backoff

            # Increase backoff for next time (exponential: 1x, 2x, 4x, 8x, 12x max)
            if self._backoff_multiplier < self._max_backoff_multiplier:
                self._backoff_multiplier = min(
                    self._backoff_multiplier * 2,
                    self._max_backoff_multiplier
                )

            return True  # Should attempt reconnection now

    def should_attempt_capture(self) -> bool:
        """Check if enough time has passed to attempt capture."""
        with self._lock:
            if self._state == self.STATE_HEALTHY:
                return True
            return time.time() >= self._next_attempt_time

    def time_until_next_attempt(self) -> float:
        """Get seconds until next capture attempt."""
        with self._lock:
            if self._state == self.STATE_HEALTHY:
                return 0
            remaining = self._next_attempt_time - time.time()
            return max(0, remaining)

    def get_status(self) -> Dict[str, Any]:
        """Get camera status for monitoring."""
        with self._lock:
            return {
                "camera_id": self.camera_id,
                "state": self._state,
                "consecutive_failures": self._consecutive_failures,
                "backoff_multiplier": self._backoff_multiplier,
                "current_backoff_seconds": self.current_backoff,
                "time_until_next_attempt": self.time_until_next_attempt(),
                "last_success_age": time.time() - self._last_success_time
            }
