#!/usr/bin/env python3

import cv2
import requests
import time
import sys
import logging
import os
import yaml
import signal
import argparse
from datetime import datetime
from threading import Thread, Lock
from queue import Queue
import ssl
import shutil
from pathlib import Path
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import json
from systemd import daemon
from concurrent.futures import ThreadPoolExecutor
import copy
import numpy as np

# Set up path for deployed environment before local imports
# In deployment: /opt/sai-cam/bin/camera_service.py needs to find /opt/sai-cam/logging_utils.py
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
for _path in [_current_dir, _parent_dir]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Import logging utilities
from logging_utils import RateLimitedLogger, CameraStateTracker

VERSION = "0.2.1"  # Added camera retry on init failure

# Force FFMPEG to use TCP transport for all RTSP connections
# Default: H.264 for broad compatibility (EZViz cameras, Raspberry Pi 3B)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|video_codec;h264|pixel_format;yuv420p"

# Alternative for cameras with H.265 support and systems with hardware acceleration:
# os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|video_codec;h265|hwaccel;vaapi|hwaccel_device;/dev/dri/renderD128|pixel_format;yuv420p"

class CameraInstance:
    """Represents a single camera instance with its own configuration and state"""

    def __init__(self, camera_id, camera_config, global_config, logger, storage_manager, upload_queue):
        self.camera_id = camera_id
        self.config = camera_config
        self.global_config = global_config
        self.logger = logger
        self.storage_manager = storage_manager
        self.upload_queue = upload_queue
        self.running = True

        # Get capture interval for this camera
        self.capture_interval = self.config.get('capture_interval', 300)
        self.timestamp_last_image = time.time() - self.capture_interval

        # Initialize state tracker for backoff management
        self.state_tracker = CameraStateTracker(
            camera_id=camera_id,
            capture_interval=self.capture_interval,
            logger=logger
        )

        # Import camera factory (path already configured at module level)
        from cameras import create_camera_from_config
        self.camera = create_camera_from_config(camera_config, global_config, logger)
        self.camera_type = camera_config.get('type', 'rtsp')
        
    def setup_camera(self):
        """Initialize this specific camera using new architecture"""
        try:
            return self.camera.setup()
        except Exception as e:
            self.logger.error(f"Camera {self.camera_id}: Setup error: {str(e)}", exc_info=True)
            return False

    def _get_cpu_temp(self):
        """Get CPU temperature (Raspberry Pi and other Linux systems)"""
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Try common thermal zone names
                for zone in ['cpu_thermal', 'coretemp', 'cpu-thermal', 'soc_thermal']:
                    if zone in temps and temps[zone]:
                        return round(temps[zone][0].current, 1)
                # Return first available temperature
                for zone, entries in temps.items():
                    if entries:
                        return round(entries[0].current, 1)
        except Exception:
            pass
        return None

    def capture_images(self):
        """Capture images from this specific camera with backoff for failures"""
        polling_interval = self.global_config.get('advanced', {}).get('polling_interval', 0.1)

        while self.running:
            try:
                current_time = time.time()

                # Check if camera is in backoff period (offline/failing)
                if not self.state_tracker.should_attempt_capture():
                    # For RTSP cameras, still grab frames to keep stream alive
                    if self.camera_type == 'rtsp' and hasattr(self.camera, 'grab_frame'):
                        self.camera.grab_frame()
                    time.sleep(polling_interval)
                    continue

                # Check if it's time for scheduled capture
                if current_time - self.timestamp_last_image < self.capture_interval:
                    # For RTSP cameras, grab frames to keep stream alive
                    if self.camera_type == 'rtsp' and hasattr(self.camera, 'grab_frame'):
                        self.camera.grab_frame()
                    time.sleep(polling_interval)
                    continue

                # Capture frame using unified interface
                frame = self.camera.capture_frame()

                if frame is None or not self.camera.validate_frame(frame):
                    # Record failure and check if we should attempt reconnection
                    if self.state_tracker.record_failure("failed to capture valid frame"):
                        # Attempt reconnection (camera.reconnect handles its own retry logic)
                        self.camera.reconnect()
                    # Sleep for backoff period
                    wait_time = min(self.state_tracker.time_until_next_attempt(), 10)
                    time.sleep(max(wait_time, 1))
                    continue

                # Success! Record it to reset backoff
                self.state_tracker.record_success()

                # Add timestamp and camera ID overlay
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                cv2.putText(frame, f"{self.camera_id}: {timestamp}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                # Build rich metadata for ML training
                metadata = {
                    # Core identification (existing fields)
                    'timestamp': timestamp,
                    'device_id': self.global_config['device']['id'],
                    'camera_id': self.camera_id,
                    'location': self.global_config['device']['location'],
                    'version': VERSION,
                    'camera_type': self.camera_type,

                    # Device context
                    'device': {
                        'uptime_seconds': round(time.time() - self.global_config.get('_start_time', time.time()), 1),
                        'description': self.global_config['device'].get('description', ''),
                    },

                    # System metrics at capture time
                    'system': {
                        'cpu_percent': psutil.cpu_percent(),
                        'memory_percent': round(psutil.virtual_memory().percent, 1),
                        'disk_percent': round(psutil.disk_usage('/').percent, 1),
                        'cpu_temp': self._get_cpu_temp(),
                    },

                    # Camera context
                    'camera': {
                        'capture_interval': self.capture_interval,
                        'position': self.config.get('position', {}),
                        'resolution': self.config.get('resolution', [1280, 720]),
                    },

                    # Image quality hints
                    'image': {
                        'brightness_avg': round(float(np.mean(frame)), 1),
                        'dimensions': [frame.shape[1], frame.shape[0]],
                    },

                    # Environmental context
                    'environment': {
                        'capture_time_utc': datetime.utcnow().isoformat() + 'Z',
                        'timezone': time.strftime('%z'),
                    },
                }

                # Encode image
                _, buffer = cv2.imencode('.jpg', frame)
                image_data = buffer.tobytes()

                # Store and queue for upload
                filename = f"{self.camera_id}_{timestamp}.jpg"
                img_size = len(image_data) / 1024
                self.logger.info(f"Camera {self.camera_id}: Captured {filename} ({img_size:.1f}KB)")

                self.storage_manager.store_image(image_data, filename, metadata)
                self.upload_queue.put((filename, image_data, metadata, self.camera_id))

                # Update timestamp for next capture
                self.timestamp_last_image = current_time
                self.logger.debug(f"Camera {self.camera_id}: Next capture in {self.capture_interval}s")

            except Exception as e:
                self.state_tracker.record_failure(f"exception: {str(e)}")
                self.logger.debug(f"Camera {self.camera_id}: Capture exception details", exc_info=True)
                time.sleep(1)
    
    
    def stop(self):
        """Stop this camera instance using new architecture"""
        self.running = False
        
        # Use new camera cleanup method
        self.camera.cleanup()
        
        self.logger.info(f"Camera {self.camera_id}: Stopped")

class CameraService:
    def __init__(self, config_path='/etc/sai-cam/config.yaml'):
        """Initialize the camera service with all required components"""
        self.config_path = config_path
        self.upload_enabled = True
        self.camera_instances = {}
        self.camera_threads = {}
        self.failed_cameras = {}  # Track cameras that failed initialization: {cam_id: (config, attempts, next_retry_time)}
        self.load_config()
        self.setup_logging()
        self.setup_storage()
        self.setup_queues()
        self.setup_ssl()
        self.setup_cameras()
        self.setup_monitoring()
        self.setup_watchdog()

    def load_config(self):
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as file:
                self.config = yaml.safe_load(file)
            # Track service start time for uptime calculation in metadata
            self.config['_start_time'] = time.time()
        except Exception as e:
            sys.exit(f"Failed to load configuration: {e}")

    def setup_logging(self):
        """Configure structured logging with rotation and consistent levels"""
        log_dir = self.config.get('logging', {}).get('log_dir', '/var/log/sai-cam')
        os.makedirs(log_dir, exist_ok=True)

        self.logger = logging.getLogger('SAICam')
        # Clear any existing handlers to prevent duplicates
        if self.logger.handlers:
            self.logger.handlers = []

        # Prevent propagation to root logger (avoids duplicate output)
        self.logger.propagate = False

        # Set the base log level from command line args or config
        log_level = getattr(logging, self.config.get('logging', {}).get('level', 'INFO'))
        self.logger.setLevel(log_level)

        # Create a more structured formatter with consistent fields
        formatter = logging.Formatter(
            '%(asctime)s [%(name)s] [%(levelname)s] [%(process)d] [v' + VERSION + '] %(message)s'
        )

        # File handler with rotation
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            f"{log_dir}/{self.config.get('logging', {}).get('log_file', 'camera_service.log')}",
            maxBytes=self.config.get('logging', {}).get('max_size_bytes', 10*1024*1024),
            backupCount=self.config.get('logging', {}).get('backup_count', 5)
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Only add console handler if running interactively (not as systemd service)
        # When running as service, stdout/stderr go to journal or file anyway
        is_interactive = sys.stdout.isatty() or os.environ.get('SAI_CAM_CONSOLE_LOG', '') == '1'
        if is_interactive:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
            self.logger.debug("Console logging enabled (interactive mode)")
        else:
            self.logger.debug("Console logging disabled (service mode)")

        self.logger.info(f"Starting SAI Camera Service v{VERSION}")
        self.logger.debug(f"Configuration loaded from: {self.config_path}")
        self.logger.debug(f"Logging level set to: {logging.getLevelName(self.logger.level)}")

    def setup_storage(self):
        """Initialize local storage system"""
        storage_config = self.config['storage']

        self.storage_path = Path(storage_config['base_path'])
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.storage_manager = StorageManager(
            base_path=self.storage_path,
            max_size_gb=storage_config['max_size_gb'],
            cleanup_threshold_gb=storage_config['cleanup_threshold_gb'],
            retention_days=storage_config['retention_days'],
            logger=self.logger
        )

    def setup_queues(self):
        """Initialize queue system for image processing"""
        self.image_queue = Queue(maxsize=100)
        self.upload_queue = Queue(maxsize=1000)
        self.running = True

    def setup_ssl(self):
        """Configure SSL context for secure communications"""
        self.ssl_context = ssl.create_default_context()
        if self.config['server']['ssl_verify']:
            self.ssl_context.verify_mode = ssl.CERT_REQUIRED
            self.ssl_context.load_verify_locations(
                self.config['server']['cert_path']
            )

    def setup_cameras(self):
        """Initialize and configure all cameras from config"""
        try:
            # Set FFMPEG debug based on config
            os.environ["OPENCV_FFMPEG_DEBUG"] = "1" if self.config.get('advanced', {}).get('ffmpeg_debug', False) else "0"
            
            # Check if we have multiple cameras or single camera config
            if 'cameras' in self.config:
                cameras_config = self.config['cameras']
                self.logger.info(f"Initializing {len(cameras_config)} cameras")
            else:
                # Backward compatibility: Create a single camera config
                cameras_config = [{
                    'id': 'cam1',
                    'type': self.config['camera'].get('type', 'rtsp'),
                    'rtsp_url': self.config['camera']['rtsp_url'],
                    'resolution': self.config['camera'].get('resolution', [1280, 720]),
                    'fps': self.config['camera'].get('fps', 30),
                    'capture_interval': self.config['camera'].get('capture_interval', 300)
                }]
                self.logger.info("Using legacy single-camera configuration")
            
            # Initialize each camera instance
            for cam_config in cameras_config:
                cam_id = cam_config['id']
                self._try_initialize_camera(cam_id, cam_config)

            total_cameras = len(cameras_config)
            active_cameras = len(self.camera_instances)
            failed_cameras = len(self.failed_cameras)

            if active_cameras == 0 and failed_cameras > 0:
                # All cameras failed but we'll retry them - don't exit
                self.logger.warning(
                    f"No cameras initialized successfully ({failed_cameras} failed). "
                    f"Will retry failed cameras periodically."
                )
            elif active_cameras == 0:
                self.logger.error("No cameras configured or all failed permanently")
                sys.exit(1)
            else:
                self.logger.info(
                    f"Initialized {active_cameras}/{total_cameras} cameras"
                    + (f" ({failed_cameras} will retry)" if failed_cameras > 0 else "")
                )

        except Exception as e:
            self.logger.error(f"Camera initialization error: {str(e)}", exc_info=True)
            sys.exit(1)

    def _try_initialize_camera(self, cam_id: str, cam_config: dict, is_retry: bool = False) -> bool:
        """
        Try to initialize a single camera.

        Args:
            cam_id: Camera identifier
            cam_config: Camera configuration dict
            is_retry: True if this is a retry attempt

        Returns:
            True if successful, False if failed
        """
        try:
            if is_retry:
                self.logger.info(f"Retrying initialization for camera {cam_id}")
            else:
                self.logger.info(f"Setting up camera {cam_id}")

            # Create camera instance
            instance = CameraInstance(
                camera_id=cam_id,
                camera_config=cam_config,
                global_config=self.config,
                logger=self.logger,
                storage_manager=self.storage_manager,
                upload_queue=self.upload_queue
            )

            # Initialize camera
            if instance.setup_camera():
                self.camera_instances[cam_id] = instance
                # Remove from failed list if it was there
                if cam_id in self.failed_cameras:
                    del self.failed_cameras[cam_id]
                    self.logger.info(f"Camera {cam_id}: Successfully recovered")
                return True
            else:
                self._record_camera_failure(cam_id, cam_config)
                return False

        except Exception as e:
            self.logger.error(f"Camera {cam_id}: Initialization exception: {str(e)}")
            self._record_camera_failure(cam_id, cam_config)
            return False

    def _record_camera_failure(self, cam_id: str, cam_config: dict):
        """Record a camera initialization failure and schedule retry."""
        capture_interval = cam_config.get('capture_interval', 300)

        if cam_id in self.failed_cameras:
            # Increment attempts and calculate next retry with exponential backoff
            config, attempts, _ = self.failed_cameras[cam_id]
            attempts += 1
            # Backoff: 1x, 2x, 4x, 8x, 12x (max) of capture_interval
            multiplier = min(2 ** (attempts - 1), 12)
        else:
            attempts = 1
            multiplier = 1

        retry_interval = capture_interval * multiplier
        next_retry = time.time() + retry_interval

        self.failed_cameras[cam_id] = (cam_config, attempts, next_retry)
        self.logger.warning(
            f"Camera {cam_id}: Failed to initialize (attempt {attempts}), "
            f"will retry in {retry_interval}s ({multiplier}x interval)"
        )

    def retry_failed_cameras(self):
        """Periodically retry initializing failed cameras."""
        # Use rate-limited logger for status updates
        rl_logger = RateLimitedLogger(self.logger, default_interval=300)

        while self.running:
            try:
                if not self.failed_cameras:
                    time.sleep(30)
                    continue

                now = time.time()
                cameras_to_retry = []

                # Find cameras ready for retry
                for cam_id, (cam_config, attempts, next_retry) in list(self.failed_cameras.items()):
                    if now >= next_retry:
                        cameras_to_retry.append((cam_id, cam_config))

                # Retry each camera
                for cam_id, cam_config in cameras_to_retry:
                    if self._try_initialize_camera(cam_id, cam_config, is_retry=True):
                        # Start capture thread for newly initialized camera
                        if cam_id in self.camera_instances:
                            instance = self.camera_instances[cam_id]
                            thread = Thread(
                                target=instance.capture_images,
                                name=f"Camera-{cam_id}"
                            )
                            thread.daemon = True
                            thread.start()
                            self.camera_threads[cam_id] = thread
                            self.logger.info(f"Started capture thread for recovered camera {cam_id}")

                # Log status periodically if there are still failed cameras
                if self.failed_cameras:
                    failed_list = ', '.join(self.failed_cameras.keys())
                    rl_logger.info(
                        f"Cameras pending retry: {failed_list}",
                        key="failed_cameras_status"
                    )

                time.sleep(10)  # Check every 10 seconds

            except Exception as e:
                self.logger.error(f"Camera retry thread error: {str(e)}", exc_info=True)
                time.sleep(60)

    def start_capture_threads(self):
        """Start capture threads for all camera instances"""
        for cam_id, instance in self.camera_instances.items():
            if cam_id not in self.camera_threads or not self.camera_threads[cam_id].is_alive():
                thread = Thread(
                    target=instance.capture_images,
                    name=f"Camera-{cam_id}"
                )
                thread.daemon = True
                thread.start()
                self.camera_threads[cam_id] = thread
                self.logger.info(f"Started capture thread for camera {cam_id}")

    def capture_images(self):
        """Main capture coordinator - starts individual camera threads"""
        self.start_capture_threads()
        while self.running:
            # Monitor camera threads and restart if needed
            alive_threads = sum(1 for t in self.camera_threads.values() if t.is_alive())
            if alive_threads < len(self.camera_instances) and self.running:
                self.logger.warning(f"Only {alive_threads}/{len(self.camera_instances)} camera threads are running, restarting failed threads")
                self.start_capture_threads()
            time.sleep(10)

    def compress_image(self, image_data):
        """Compress image data if needed"""
        # For simple implementation, just return the data
        # For better performance, could use PIL or other compression
        return image_data

    def disable_upload(self):
        """Disable image upload for local testing"""
        self.upload_enabled = False
        self.logger.info("Upload disabled - running in local save mode")

    def upload_images(self):
        """Upload images to server"""
        if not self.upload_enabled:
            self.logger.info("Upload functionality disabled")
            return

        while self.running:
            try:
                if not self.upload_queue.empty():
                    filename, image_data, metadata, camera_id = self.upload_queue.get()
                    img_size = len(image_data) / 1024
                    self.logger.info(f"Camera {camera_id}: Uploading {filename} ({img_size:.1f}KB) to {self.config['server']['url']}")

                    files = {
                        'image': (filename, image_data, 'image/jpeg'),
                        'metadata': ('metadata.json', json.dumps(metadata), 'application/json')
                    }

                    headers = {
                        "Authorization": f"Bearer {self.config['server']['auth_token']}",
                    }

                    response = requests.post(
                        self.config['server']['url'],
                        headers=headers,
                        files=files,
                        verify=self.config['server']['ssl_verify'],
                        timeout=self.config['server']['timeout']
                    )

                    if response.status_code == 200:
                        self.storage_manager.mark_as_uploaded(filename)
                        response_time = response.elapsed.total_seconds()
                        self.logger.info(f"Successfully uploaded {filename} in {response_time:.2f}s")
                    else:
                        self.logger.error(f"Upload failed for {filename}: HTTP {response.status_code} - {response.text[:100]}")

                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"Upload error: {str(e)}", exc_info=True)
                time.sleep(1)

    def setup_monitoring(self):
        """Initialize system monitoring"""
        self.health_monitor = HealthMonitor(
            self.config['monitoring'],
            self.logger,
            self.restart_service
        )

    def setup_watchdog(self):
        """Configure systemd watchdog integration"""
        self.watchdog_usec = int(os.environ.get('WATCHDOG_USEC', 0))
        if self.watchdog_usec:
            self.logger.info(f"Watchdog enabled with {self.watchdog_usec/1000000}s timeout")
            daemon.notify('READY=1')
        else:
            self.logger.info("Watchdog not enabled")

    def send_watchdog_notification(self):
        """Send heartbeat to systemd watchdog"""
        if self.watchdog_usec:
            daemon.notify('WATCHDOG=1')

    def watchdog_loop(self):
        """Dedicated thread for watchdog notifications"""
        while self.running:
            self.send_watchdog_notification()
            time.sleep(self.watchdog_usec/2000000)  # Sleep for half the timeout period

    def run(self):
        """Main service run method"""
        threads = [
            Thread(target=self.capture_images, name="CaptureCoordinator"),
            Thread(target=self.upload_images, name="UploadProcessor"),
            Thread(target=self.health_monitor.run, name="HealthMonitor"),
            Thread(target=self.storage_manager.run_cleanup_thread, name="StorageManager"),
            Thread(target=self.retry_failed_cameras, name="CameraRetry"),
            Thread(target=self.health_socket_server, name="HealthSocket"),
        ]

        if self.watchdog_usec:
            threads.append(Thread(target=self.watchdog_loop, name="WatchdogNotifier"))

        for thread in threads:
            thread.daemon = True  # Ensure threads terminate with main process
            thread.start()

        try:
            # Register signal handlers
            signal.signal(signal.SIGTERM, self.handle_shutdown)
            signal.signal(signal.SIGINT, self.handle_shutdown)
            signal.signal(signal.SIGHUP, self.handle_reload)

            # Keep main thread alive
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            self.cleanup()

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, initiating shutdown...")
        self.cleanup()

    def handle_reload(self, signum, frame):
        """Handle SIGHUP for config hot-reload"""
        self.logger.info("Received SIGHUP, reloading configuration...")

        try:
            # Load new config
            with open(self.config_path, 'r') as file:
                new_config = yaml.safe_load(file)
        except Exception as e:
            self.logger.error(f"Failed to reload config: {e}")
            return

        changes = []
        restart_required = []
        old_config = self.config

        # 1. Logging level (safe to reload)
        new_level = new_config.get('logging', {}).get('level', 'INFO')
        old_level = old_config.get('logging', {}).get('level', 'INFO')
        if new_level != old_level:
            log_level = getattr(logging, new_level, logging.INFO)
            self.logger.setLevel(log_level)
            for handler in self.logger.handlers:
                handler.setLevel(log_level)
            changes.append(f"logging.level: {old_level} -> {new_level}")

        # 2. Monitoring thresholds (safe to reload)
        for key in ['health_check_interval', 'max_memory_percent', 'max_cpu_percent']:
            new_val = new_config.get('monitoring', {}).get(key)
            old_val = old_config.get('monitoring', {}).get(key)
            if new_val is not None and new_val != old_val:
                self.health_monitor.config[key] = new_val
                changes.append(f"monitoring.{key}: {old_val} -> {new_val}")

        # 3. Server settings (safe to reload - used per-upload)
        for key in ['url', 'auth_token', 'timeout', 'ssl_verify']:
            new_val = new_config.get('server', {}).get(key)
            old_val = old_config.get('server', {}).get(key)
            if new_val is not None and new_val != old_val:
                display_old = '***' if 'token' in key else old_val
                display_new = '***' if 'token' in key else new_val
                changes.append(f"server.{key}: {display_old} -> {display_new}")

        # 4. Advanced settings (safe to reload)
        for key in ['polling_interval', 'reconnect_delay', 'reconnect_attempts']:
            new_val = new_config.get('advanced', {}).get(key)
            old_val = old_config.get('advanced', {}).get(key)
            if new_val is not None and new_val != old_val:
                changes.append(f"advanced.{key}: {old_val} -> {new_val}")

        # Check for changes that require restart (warn only)
        if new_config.get('cameras') != old_config.get('cameras'):
            restart_required.append('cameras')
        if new_config.get('storage', {}).get('base_path') != old_config.get('storage', {}).get('base_path'):
            restart_required.append('storage.base_path')
        if new_config.get('network') != old_config.get('network'):
            restart_required.append('network')
        if new_config.get('device') != old_config.get('device'):
            restart_required.append('device')

        # Preserve _start_time from original config
        new_config['_start_time'] = old_config.get('_start_time', time.time())

        # Update config reference
        self.config = new_config

        # Log results
        if changes:
            self.logger.info(f"Config reload applied {len(changes)} change(s):")
            for change in changes:
                self.logger.info(f"  - {change}")
        else:
            self.logger.info("Config reload: no safe changes detected")

        if restart_required:
            self.logger.warning(
                f"Config reload: the following changes require service restart to take effect: "
                f"{', '.join(restart_required)}"
            )

    def health_socket_server(self):
        """Serve health status via Unix domain socket for status_portal integration"""
        import socket as sock

        socket_path = '/run/sai-cam/health.sock'

        # Ensure directory exists (systemd RuntimeDirectory should create it, but fallback)
        socket_dir = os.path.dirname(socket_path)
        try:
            os.makedirs(socket_dir, exist_ok=True)
        except PermissionError:
            self.logger.warning(f"Cannot create {socket_dir}, health socket disabled")
            return

        # Remove stale socket file
        if os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except Exception as e:
                self.logger.warning(f"Cannot remove stale socket {socket_path}: {e}")
                return

        try:
            server = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
            server.bind(socket_path)
            os.chmod(socket_path, 0o666)  # Allow portal to connect
            server.listen(5)
            server.settimeout(1.0)  # Allow checking self.running
            self.logger.info(f"Health socket server listening on {socket_path}")
        except Exception as e:
            self.logger.warning(f"Failed to start health socket server: {e}")
            return

        while self.running:
            try:
                conn, _ = server.accept()
                try:
                    health_data = self._get_health_data()
                    response = json.dumps(health_data)
                    conn.sendall(response.encode('utf-8'))
                finally:
                    conn.close()
            except sock.timeout:
                continue
            except Exception as e:
                self.logger.debug(f"Health socket error: {e}")

        # Cleanup on shutdown
        try:
            server.close()
            if os.path.exists(socket_path):
                os.unlink(socket_path)
        except Exception:
            pass

    def _get_health_data(self):
        """Collect current health state for socket response"""
        return {
            'timestamp': datetime.now().isoformat(),
            'version': VERSION,
            'uptime_seconds': round(time.time() - self.config.get('_start_time', time.time()), 1),

            # System metrics
            'system': {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': round(psutil.virtual_memory().percent, 1),
                'disk_percent': round(psutil.disk_usage('/').percent, 1),
            },

            # Health monitor metrics
            'health_monitor': {
                'check_count': self.health_monitor.metrics.get('check_count', 0),
                'warning_count': self.health_monitor.metrics.get('warning_count', 0),
                'error_count': self.health_monitor.metrics.get('error_count', 0),
                'last_check': self.health_monitor.metrics.get('last_check', 0),
            },

            # Thread health
            'threads': {
                'total': len(self.camera_threads),
                'alive': sum(1 for t in self.camera_threads.values() if t.is_alive()),
                'cameras': {
                    cam_id: t.is_alive() if t else False
                    for cam_id, t in self.camera_threads.items()
                }
            },

            # Per-camera state from CameraStateTracker
            'cameras': {
                cam_id: {
                    **instance.state_tracker.get_status(),
                    'thread_alive': self.camera_threads.get(cam_id) is not None
                        and self.camera_threads[cam_id].is_alive(),
                }
                for cam_id, instance in self.camera_instances.items()
            },

            # Failed cameras pending retry
            'failed_cameras': {
                cam_id: {
                    'attempts': attempts,
                    'next_retry': next_retry,
                }
                for cam_id, (config, attempts, next_retry) in self.failed_cameras.items()
            },
        }

    def cleanup(self):
        """Clean up resources"""
        self.running = False
        
        # Stop all camera instances
        for cam_id, instance in self.camera_instances.items():
            self.logger.info(f"Stopping camera {cam_id}")
            instance.stop()
            
        self.logger.info("Service stopped")
        sys.exit(0)

    def restart_service(self):
        """Restart the service"""
        self.logger.info("Restarting service...")
        self.cleanup()
        os.execv(sys.executable, ['python'] + sys.argv)

class StorageManager:
    def __init__(self, base_path, max_size_gb, cleanup_threshold_gb,
                 retention_days, logger):
        """Initialize the storage manager"""
        self.base_path = Path(base_path)
        self.max_size_gb = max_size_gb
        self.cleanup_threshold_gb = cleanup_threshold_gb
        self.retention_days = retention_days
        self.logger = logger
        self.running = True

        # Create storage directories
        self.uploaded_path = self.base_path / 'uploaded'
        self.uploaded_path.mkdir(parents=True, exist_ok=True)

        # Initialize metadata storage
        self.metadata_path = self.base_path / 'metadata'
        self.metadata_path.mkdir(parents=True, exist_ok=True)

    def get_current_size_gb(self):
        """Calculate current storage usage"""
        try:
            total_size = sum(f.stat().st_size for f in self.base_path.rglob('*') if f.is_file())
            return total_size / (1024**3)  # Convert to GB
        except Exception as e:
            self.logger.error(f"Error calculating storage size: {e}")
            return 0

    def store_image(self, image_data, filename, metadata=None):
        """Store image and its metadata"""
        try:
            # Check storage limits before storing
            current_size = self.get_current_size_gb()
            self.logger.debug(f"Current storage usage: {current_size:.2f}GB/{self.max_size_gb}GB")
            if current_size >= self.max_size_gb:
                self.logger.warning(f"Storage limit reached ({current_size:.2f}GB/{self.max_size_gb}GB), forcing cleanup")
                self.cleanup_old_files()

            # Store image
            file_path = self.base_path / filename
            with open(file_path, 'wb') as f:
                f.write(image_data)
            self.logger.debug(f"Image saved to: {file_path}")

            # Store metadata if provided
            if metadata:
                metadata_file = self.metadata_path / f"{filename}.json"
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f)
                self.logger.debug(f"Metadata saved to: {metadata_file}")

            img_size = len(image_data) / 1024
            self.logger.info(f"Stored image: {filename} ({img_size:.1f}KB)")
            return True
        except Exception as e:
            self.logger.error(f"Failed to store image {filename}: {str(e)}", exc_info=True)
            return False

    def mark_as_uploaded(self, filename):
        """Mark file as successfully uploaded"""
        try:
            # Move image
            src_path = self.base_path / filename
            dst_path = self.uploaded_path / filename
            if src_path.exists():
                shutil.move(src_path, dst_path)

            # Move metadata if exists
            meta_src = self.metadata_path / f"{filename}.json"
            meta_dst = self.uploaded_path / 'metadata' / f"{filename}.json"
            if meta_src.exists():
                meta_dst.parent.mkdir(exist_ok=True)
                shutil.move(meta_src, meta_dst)

            self.logger.debug(f"Marked as uploaded: {filename}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to mark {filename} as uploaded: {str(e)}", exc_info=True)
            return False

    def cleanup_old_files(self):
        """Remove old files to maintain storage limits"""
        try:
            current_size = self.get_current_size_gb()

            if current_size > self.cleanup_threshold_gb:
                self.logger.info(f"Starting storage cleanup. Current size: {current_size:.2f}GB")

                # Remove old uploaded files first
                if self.uploaded_path.exists():
                    uploaded_files = sorted(
                        self.uploaded_path.glob('*.jpg'),
                        key=lambda x: x.stat().st_mtime
                    )
                    for file in uploaded_files:
                        if (datetime.now().timestamp() - file.stat().st_mtime) > \
                           (self.retention_days * 24 * 3600):
                            try:
                                # Remove image and its metadata
                                file.unlink()
                                meta_file = self.uploaded_path / 'metadata' / f"{file.name}.json"
                                if meta_file.exists():
                                    meta_file.unlink()
                            except FileNotFoundError:
                                # File already deleted, skip silently
                                self.logger.debug(f"Cleanup: File already removed: {file.name}")
                                continue
                            except Exception as e:
                                # Log other errors but continue cleanup
                                self.logger.warning(f"Failed to delete {file.name}: {str(e)}")
                                continue

                            if self.get_current_size_gb() < self.cleanup_threshold_gb:
                                break

                # If still above threshold, remove old non-uploaded files
                if self.get_current_size_gb() > self.cleanup_threshold_gb:
                    non_uploaded_files = sorted(
                        self.base_path.glob('*.jpg'),
                        key=lambda x: x.stat().st_mtime
                    )
                    for file in non_uploaded_files:
                        if (datetime.now().timestamp() - file.stat().st_mtime) > \
                           (self.retention_days * 24 * 3600):
                            try:
                                file.unlink()
                                meta_file = self.metadata_path / f"{file.name}.json"
                                if meta_file.exists():
                                    meta_file.unlink()
                            except FileNotFoundError:
                                # File already deleted, skip silently
                                self.logger.debug(f"Cleanup: File already removed: {file.name}")
                                continue
                            except Exception as e:
                                # Log other errors but continue cleanup
                                self.logger.warning(f"Failed to delete {file.name}: {str(e)}")
                                continue

                            if self.get_current_size_gb() < self.cleanup_threshold_gb:
                                break

                self.logger.info(f"Cleanup completed. New size: {self.get_current_size_gb():.2f}GB")

        except Exception as e:
            self.logger.error(f"Cleanup error: {str(e)}", exc_info=True)

    def run_cleanup_thread(self):
        """Run periodic cleanup"""
        while self.running:
            try:
                self.cleanup_old_files()
                time.sleep(3600)  # Check every hour
            except Exception as e:
                self.logger.error(f"Cleanup thread error: {str(e)}", exc_info=True)
                time.sleep(60)  # Wait a minute before retrying

class HealthMonitor:
    def __init__(self, config, logger, restart_callback):
        """Initialize the health monitor"""
        self.config = config
        self.logger = logger
        self.restart_callback = restart_callback
        self.running = True

        # Initialize metrics
        self.metrics = {
            'start_time': time.time(),
            'last_check': time.time(),
            'check_count': 0,
            'warning_count': 0,
            'error_count': 0
        }

    def check_system_health(self):
        """Check system resources and health"""
        try:
            # Update metrics
            self.metrics['check_count'] += 1
            self.metrics['last_check'] = time.time()

            # Check CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.config['max_cpu_percent']:
                self.metrics['warning_count'] += 1
                self.logger.warning(f"High CPU usage: {cpu_percent}%")

            # Check memory usage
            memory = psutil.virtual_memory()
            if memory.percent > self.config['max_memory_percent']:
                self.metrics['warning_count'] += 1
                self.logger.warning(f"High memory usage: {memory.percent}%")

            # Check disk usage
            disk = psutil.disk_usage('/')
            if disk.percent > 90:  # Hard-coded threshold for disk space
                self.metrics['warning_count'] += 1
                self.logger.warning(f"High disk usage: {disk.percent}%")

            # Check system temperature if available
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        for entry in entries:
                            if entry.current > 80:  # Generic high temp threshold
                                self.metrics['warning_count'] += 1
                                self.logger.warning(f"High temperature {name}: {entry.current}°C")

            # Trigger restart if configured and thresholds exceeded
            if (self.config.get('restart_on_failure', False) and
                (cpu_percent > self.config['max_cpu_percent'] or
                 memory.percent > self.config['max_memory_percent'])):
                self.logger.error("Critical resource usage detected, initiating restart")
                self.metrics['error_count'] += 1
                self.restart_callback()

            # Log metrics periodically
            if self.metrics['check_count'] % 60 == 0:  # Log every 60 checks
                uptime = time.time() - self.metrics['start_time']
                self.logger.info(
                    f"Health metrics - Uptime: {uptime:.0f}s, "
                    f"Warnings: {self.metrics['warning_count']}, "
                    f"Errors: {self.metrics['error_count']}"
                )

        except Exception as e:
            self.logger.error(f"Health check error: {str(e)}", exc_info=True)
            self.metrics['error_count'] += 1

    def run(self):
        """Run periodic health checks"""
        while self.running:
            try:
                self.check_system_health()
                time.sleep(self.config['health_check_interval'])
            except Exception as e:
                self.logger.error(f"Health monitor thread error: {str(e)}", exc_info=True)
                time.sleep(60)  # Wait a minute before retrying

def main():
    """Main entry point with enhanced CLI options"""
    parser = argparse.ArgumentParser(description='SAI Camera Service')

    # Service configuration
    parser.add_argument('--config', type=str,
                        help='Path to config file (default: /etc/sai-cam/config.yaml)',
                        default='/etc/sai-cam/config.yaml')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Logging level (default: INFO)', default='INFO')

    # Testing options
    parser.add_argument('--local-save', action='store_true',
                        help='Save images locally without uploading')
    parser.add_argument('--dry-run', action='store_true',
                        help='Initialize camera and exit (testing only)')

    args = parser.parse_args()

    # Minimal early logging setup (will be replaced by CameraService.setup_logging)
    # Only log critical startup errors before proper logging is configured
    early_logger = logging.getLogger('SAICam.startup')
    early_logger.setLevel(getattr(logging, args.log_level))
    if not early_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
        early_logger.addHandler(handler)

    try:
        # Initialize service (this sets up proper logging)
        service = CameraService(config_path=args.config)

        # Handle testing options
        if args.dry_run:
            service.logger.info("Dry run completed successfully")
            return

        if args.local_save:
            service.disable_upload()

        # Run service
        service.run()

    except Exception as e:
        early_logger.error(f"Failed to start service: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

