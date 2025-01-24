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
from threading import Thread
from queue import Queue
import ssl
import shutil
from pathlib import Path
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import json
from systemd import daemon

VERSION = "0.0.1"

class CameraService:
    def __init__(self, config_path='/etc/sai-cam/config.yaml'):
        """Initialize the camera service with all required components"""
        self.config_path = config_path
        self.upload_enabled = True
        self.show_preview = False
        self.load_config()
        self.setup_logging()
        self.setup_storage()
        self.setup_queues()
        self.setup_ssl()
        self.setup_camera()
        self.setup_monitoring()
        self.setup_watchdog()

    def load_config(self):
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as file:
                self.config = yaml.safe_load(file)
        except Exception as e:
            sys.exit(f"Failed to load configuration: {e}")

    def setup_logging(self):
        """Configure logging with rotation"""
        log_dir = '/var/log/sai-cam'
        os.makedirs(log_dir, exist_ok=True)

        self.logger = logging.getLogger('SAICam')

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # File handler with rotation
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            f'{log_dir}/camera_service.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        self.logger.info(f"Starting SAI Camera Service v{VERSION}")

    def setup_storage(self):
        """Initialize local storage system"""
        storage_config = self.config['storage']
        self.storage_path = Path('/opt/sai-cam/storage')
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

    def setup_camera(self):
        """Initialize and configure the camera"""
        try:
            if self.config['camera']['type'] == 'rtsp':
                self.cap = cv2.VideoCapture(self.config['camera']['rtsp_url'])
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                self.cap = cv2.VideoCapture(0)  # USB camera

            resolution = self.config['camera']['resolution']
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
            self.cap.set(cv2.CAP_PROP_FPS, self.config['camera']['fps'])

            if not self.cap.isOpened():
                self.logger.error("Failed to initialize camera")
                sys.exit(1)

            self.logger.info(f"Camera initialized successfully: {resolution}")
        except Exception as e:
            self.logger.error(f"Camera setup error: {e}")
            sys.exit(1)

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

    def enable_preview(self):
        """Enable camera preview window for testing"""
        self.show_preview = True
        self.logger.info("Preview mode enabled")

    def disable_upload(self):
        """Disable image upload for local testing"""
        self.upload_enabled = False
        self.logger.info("Upload disabled - running in local save mode")

    def validate_image(self, frame):
        """Basic image validation"""
        if frame is None or frame.size == 0:
            return False
        # Check for completely black or white frames
        avg_value = cv2.mean(frame)[0]
        if avg_value < 5 or avg_value > 250:
            return False
        return True

    def capture_images(self):
        """Capture images from camera"""
        while self.running:
            try:
                ret, frame = self.cap.read()
                if not ret or not self.validate_image(frame):
                    self.logger.warning("Failed to capture valid frame")
                    self.reconnect_camera()
                    continue

                # Show preview if enabled
                if self.show_preview:
                    cv2.imshow('Camera Preview', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        self.running = False
                        break

                # Add timestamp
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                cv2.putText(frame, timestamp, (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                # Add metadata
                metadata = {
                    'timestamp': timestamp,
                    'device_id': self.config['device']['id'],
                    'location': self.config['device']['location'],
                    'version': VERSION
                }

                # Encode and compress
                _, buffer = cv2.imencode('.jpg', frame)
                image_data = self.compress_image(buffer.tobytes())

                # Store locally and queue for upload
                filename = f"{timestamp}.jpg"
                self.storage_manager.store_image(image_data, filename, metadata)

                if self.upload_enabled:
                    self.upload_queue.put((filename, image_data, metadata))

                time.sleep(self.config['camera']['capture_interval'])

            except Exception as e:
                self.logger.error(f"Capture error: {e}")
                time.sleep(1)

    def upload_images(self):
        """Upload images to server"""
        if not self.upload_enabled:
            return

        while self.running:
            try:
                if not self.upload_queue.empty():
                    filename, image_data, metadata = self.upload_queue.get()

                    files = {
                        'image': (filename, image_data, 'image/jpeg'),
                        'metadata': ('metadata.json', json.dumps(metadata), 'application/json')
                    }

                    response = requests.post(
                        self.config['server']['url'],
                        files=files,
                        verify=self.config['server']['ssl_verify'],
                        timeout=self.config['server']['timeout']
                    )

                    if response.status_code == 200:
                        self.storage_manager.mark_as_uploaded(filename)
                        self.logger.debug(f"Successfully uploaded {filename}")
                    else:
                        self.logger.error(f"Upload failed: {response.status_code}")

                time.sleep(0.1)
            except Exception as e:
                self.logger.error(f"Upload error: {e}")

    def run(self):
        """Main service run method"""
        threads = [
            Thread(target=self.capture_images),
            Thread(target=self.upload_images),
            Thread(target=self.health_monitor.run),
            Thread(target=self.storage_manager.run_cleanup_thread)
        ]

        if self.watchdog_usec:
            threads.append(Thread(target=self.watchdog_loop))

        for thread in threads:
            thread.daemon = True  # Ensure threads terminate with main process
            thread.start()

        try:
            # Register signal handlers
            signal.signal(signal.SIGTERM, self.handle_shutdown)
            signal.signal(signal.SIGINT, self.handle_shutdown)

            # Keep main thread alive
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            self.cleanup()

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, initiating shutdown...")
        self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        self.running = False
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()
        if self.show_preview:
            cv2.destroyAllWindows()
        self.logger.info("Service stopped")
        sys.exit(0)

    def restart_service(self):
        """Restart the service"""
        self.logger.info("Restarting service...")
        self.cleanup()
        os.execv(sys.executable, ['python'] + sys.argv)

    def reconnect_camera(self):
        """Attempt to reconnect to the camera"""
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()
        time.sleep(2)
        self.setup_camera()

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
            if self.get_current_size_gb() >= self.max_size_gb:
                self.logger.warning("Storage limit reached, forcing cleanup")
                self.cleanup_old_files()

            # Store image
            file_path = self.base_path / filename
            with open(file_path, 'wb') as f:
                f.write(image_data)

            # Store metadata if provided
            if metadata:
                metadata_file = self.metadata_path / f"{filename}.json"
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f)

            self.logger.debug(f"Stored image: {filename}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to store image {filename}: {e}")
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
            self.logger.error(f"Failed to mark {filename} as uploaded: {e}")
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
                            # Remove image and its metadata
                            file.unlink()
                            meta_file = self.uploaded_path / 'metadata' / f"{file.name}.json"
                            if meta_file.exists():
                                meta_file.unlink()

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
                            file.unlink()
                            meta_file = self.metadata_path / f"{file.name}.json"
                            if meta_file.exists():
                                meta_file.unlink()

                            if self.get_current_size_gb() < self.cleanup_threshold_gb:
                                break

                self.logger.info(f"Cleanup completed. New size: {self.get_current_size_gb():.2f}GB")

        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")

    def run_cleanup_thread(self):
        """Run periodic cleanup"""
        while self.running:
            try:
                self.cleanup_old_files()
                time.sleep(3600)  # Check every hour
            except Exception as e:
                self.logger.error(f"Cleanup thread error: {e}")
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
            self.logger.error(f"Health check error: {e}")
            self.metrics['error_count'] += 1

    def run(self):
        """Run periodic health checks"""
        while self.running:
            try:
                self.check_system_health()
                time.sleep(self.config['health_check_interval'])
            except Exception as e:
                self.logger.error(f"Health monitor thread error: {e}")
                time.sleep(60)  # Wait a minute before retrying

def main():
    """Main entry point with enhanced CLI options"""
    parser = argparse.ArgumentParser(description='SAI Camera Service')

    # Camera configuration
    parser.add_argument('--camera-type', choices=['usb', 'rtsp'],
                       help='Camera type (default: from config)', default=None)
    parser.add_argument('--camera-source',
                       help='Camera source (USB index or RTSP URL)', default=None)
    parser.add_argument('--resolution', type=str,
                       help='Camera resolution in WxH format (e.g., 1280x720)', default=None)
    parser.add_argument('--fps', type=int,
                       help='Camera FPS (default: from config)', default=None)

    # Service configuration
    parser.add_argument('--config', type=str,
                       help='Path to config file (default: /etc/sai-cam/config.yaml)',
                       default='/etc/sai-cam/config.yaml')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level (default: INFO)', default='INFO')
    parser.add_argument('--capture-interval', type=float,
                       help='Capture interval in seconds (default: from config)',
                       default=None)

    # Testing options
    parser.add_argument('--local-save', action='store_true',
                       help='Save images locally without uploading')
    parser.add_argument('--show-preview', action='store_true',
                       help='Show camera preview window (testing only)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Initialize camera and exit (testing only)')

    args = parser.parse_args()

    # Configure logging first
    logging.basicConfig(level=getattr(logging, args.log_level))
    logger = logging.getLogger('SAICam')

    try:
        # Load config file
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)

        # Override config with command line arguments
        if args.camera_type:
            config['camera']['type'] = args.camera_type
        if args.camera_source:
            if args.camera_type == 'rtsp':
                config['camera']['rtsp_url'] = args.camera_source
            else:
                config['camera']['source'] = int(args.camera_source)
        if args.resolution:
            w, h = map(int, args.resolution.split('x'))
            config['camera']['resolution'] = [w, h]
        if args.fps:
            config['camera']['fps'] = args.fps
        if args.capture_interval:
            config['camera']['capture_interval'] = args.capture_interval

        # Initialize service
        service = CameraService(config_path=args.config)

        # Handle testing options
        if args.dry_run:
            logger.info("Dry run completed successfully")
            return

        if args.show_preview:
            service.enable_preview()

        if args.local_save:
            service.disable_upload()

        # Run service
        service.run()

    except Exception as e:
        logger.error(f"Failed to start service: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
