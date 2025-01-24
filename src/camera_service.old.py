#!/usr/bin/env python3

import cv2
import requests
import time
import sys
import logging
import os
import yaml
import signal
from datetime import datetime
from threading import Thread
from queue import Queue
import ssl
import shutil
from pathlib import Path
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from systemd import daemon
import json

class CameraService:
    def __init__(self):
        """Initialize the camera service with all required components"""
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
            with open('/etc/sai-cam/config.yaml', 'r') as file:
                self.config = yaml.safe_load(file)
        except Exception as e:
            sys.exit(f"Failed to load configuration: {e}")

    def setup_logging(self):
        """Configure logging with rotation"""
        log_dir = '/var/log/sai-cam'
        os.makedirs(log_dir, exist_ok=True)

        self.logger = logging.getLogger('SAICam')
        self.logger.setLevel(logging.INFO)

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

    def capture_images(self):
        """Capture images from camera"""
        while self.running:
            try:
                ret, frame = self.cap.read()
                if not ret:
                    self.logger.warning("Failed to capture frame")
                    self.reconnect_camera()
                    continue

                # Add timestamp
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                cv2.putText(frame, timestamp, (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                # Add metadata
                metadata = {
                    'timestamp': timestamp,
                    'device_id': self.config['device']['id'],
                    'location': self.config['device']['location']
                }

                # Encode and compress
                _, buffer = cv2.imencode('.jpg', frame)
                image_data = self.compress_image(buffer.tobytes())

                # Store locally and queue for upload
                filename = f"{timestamp}.jpg"
                self.storage_manager.store_image(image_data, filename, metadata)
                self.upload_queue.put((filename, image_data, metadata))

                time.sleep(self.config['camera']['capture_interval'])

            except Exception as e:
                self.logger.error(f"Capture error: {e}")
                time.sleep(1)

    def upload_images(self):
        """Upload images to server"""
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
        self.logger.info("Service stopped")
        sys.exit(0)

    def restart_service(self):
        """Restart the service"""
        self.logger.info("Restarting service...")
        self.cleanup()
        os.execv(sys.executable, ['python'] + sys.argv)

def main():
    """Main entry point"""
    service = CameraService()
    service.run()

if __name__ == '__main__':
    main()

