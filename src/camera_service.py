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
# ONVIF and HTTP auth now handled by camera modules

VERSION = "0.1.0"  # Version bump for multi-camera support

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
        self.timestamp_last_image = time.time() - self.config.get('capture_interval', 300)
        
        # Import and create camera using new architecture
        import sys
        import os
        # Add current directory to path to find cameras module in deployed environment
        current_dir = os.path.dirname(__file__)
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        # Add parent directory as well for when running from bin/ subdirectory
        parent_dir = os.path.dirname(current_dir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
            
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
    
    
    
    
        
    def capture_images(self):
        """Capture images from this specific camera"""
        polling_interval = self.global_config.get('advanced', {}).get('polling_interval', 0.1)
        
        while self.running:
            try:
                current_time = time.time()
                interval = self.config.get('capture_interval', 300)
                
                if current_time - self.timestamp_last_image < interval:
                    # For RTSP cameras, grab frames to keep stream alive
                    if self.camera_type == 'rtsp' and hasattr(self.camera, 'grab_frame'):
                        self.camera.grab_frame()
                    time.sleep(polling_interval)
                    continue
                
                # Capture frame using new unified interface
                frame = self.camera.capture_frame()
                
                if frame is None or not self.camera.validate_frame(frame):
                    self.logger.warning(f"Camera {self.camera_id}: Failed to capture valid frame")
                    if not self.camera.reconnect():
                        self.logger.error(f"Camera {self.camera_id}: Reconnection failed")
                    time.sleep(1)
                    continue
                
                # Add timestamp and camera ID
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                cv2.putText(frame, f"{self.camera_id}: {timestamp}", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                
                # Add metadata
                metadata = {
                    'timestamp': timestamp,
                    'device_id': self.global_config['device']['id'],
                    'camera_id': self.camera_id,
                    'location': self.global_config['device']['location'],
                    'version': VERSION,
                    'camera_type': self.camera_type
                }
                
                # Encode and compress
                _, buffer = cv2.imencode('.jpg', frame)
                image_data = buffer.tobytes()
                
                # Store locally and queue for upload
                filename = f"{self.camera_id}_{timestamp}.jpg"
                img_size = len(image_data) / 1024
                self.logger.info(f"Camera {self.camera_id}: Captured image {filename} ({img_size:.1f}KB)")
                
                self.storage_manager.store_image(image_data, filename, metadata)
                
                # Add to upload queue if uploads are enabled
                self.upload_queue.put((filename, image_data, metadata, self.camera_id))
                
                # Update timestamp for next capture
                self.timestamp_last_image = current_time
                self.logger.debug(f"Camera {self.camera_id}: Next capture in {interval}s")
                
            except Exception as e:
                self.logger.error(f"Camera {self.camera_id}: Capture error: {str(e)}", exc_info=True)
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

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

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
                else:
                    self.logger.error(f"Failed to initialize camera {cam_id}")
            
            if not self.camera_instances:
                self.logger.error("No cameras were successfully initialized")
                sys.exit(1)
                
            self.logger.info(f"Successfully initialized {len(self.camera_instances)} cameras")

        except Exception as e:
            self.logger.error(f"Camera initialization error: {str(e)}", exc_info=True)
            sys.exit(1)

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
            Thread(target=self.storage_manager.run_cleanup_thread, name="StorageManager")
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

    # Configure logging first
    logging.basicConfig(level=getattr(logging, args.log_level))
    logger = logging.getLogger('SAICam')

    try:
        # Initialize service
        service = CameraService(config_path=args.config)

        # Handle testing options
        if args.dry_run:
            logger.info("Dry run completed successfully")
            return

        if args.local_save:
            service.disable_upload()

        # Run service
        service.run()

    except Exception as e:
        logger.error(f"Failed to start service: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

