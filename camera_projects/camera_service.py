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
import json

class CameraService:
    def __init__(self):
        self.load_config()
        self.setup_logging()
        self.setup_storage()
        self.setup_queues()
        self.setup_ssl()
        self.setup_camera()
        self.setup_monitoring()
        
    def load_config(self):
        """Load configuration from YAML file"""
        try:
            with open('/etc/camera_service/config.yaml', 'r') as file:
                self.config = yaml.safe_load(file)
        except Exception as e:
            sys.exit(f"Failed to load configuration: {e}")

    def setup_logging(self):
        """Configure logging with rotation"""
        log_dir = '/var/log/camera_service'
        os.makedirs(log_dir, exist_ok=True)
        
        self.logger = logging.getLogger('CameraService')
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
        self.storage_path = Path(storage_config['base_path'])
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize storage manager
        self.storage_manager = StorageManager(
            base_path=self.storage_path,
            max_size_gb=storage_config['max_size_gb'],
            cleanup_threshold_gb=storage_config['cleanup_threshold_gb'],
            retention_days=storage_config['retention_days'],
            logger=self.logger
        )

    def setup_queues(self):
        """Initialize queue system"""
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
        self.cap = cv2.VideoCapture(0)
        resolution = self.config['camera']['resolution']
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, self.config['camera']['fps'])
        
        if not self.cap.isOpened():
            self.logger.error("Failed to initialize camera")
            sys.exit(1)

    def setup_monitoring(self):
        """Initialize system monitoring"""
        self.health_monitor = HealthMonitor(
            self.config['monitoring'],
            self.logger,
            self.restart_service
        )

    def compress_image(self, image_data):
        """Compress image to target size"""
        if not self.config['compression']['enabled']:
            return image_data
            
        target_size = self.config['compression']['target_size_kb'] * 1024
        quality = 95
        min_quality = self.config['compression']['min_quality']
        
        while len(image_data) > target_size and quality > min_quality:
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            _, image_data = cv2.imencode('.jpg', 
                                       cv2.imdecode(
                                           np.frombuffer(image_data, np.uint8),
                                           cv2.IMREAD_COLOR
                                       ),
                                       encode_param)
            quality -= 5
            
        return image_data

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
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cv2.putText(frame, timestamp, (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                # Encode and compress
                _, buffer = cv2.imencode('.jpg', frame)
                compressed_data = self.compress_image(buffer.tobytes())

                # Store locally and queue for upload
                filename = f"{timestamp.replace(' ', '_')}.jpg"
                self.storage_manager.store_image(compressed_data, filename)
                self.upload_queue.put((filename, compressed_data))

                time.sleep(self.config['camera']['capture_interval'])

            except Exception as e:
                self.logger.error(f"Capture error: {e}")
                time.sleep(1)

    def upload_images(self):
        """Upload images to server"""
        while self.running:
            try:
                if not self.upload_queue.empty():
                    filename, image_data = self.upload_queue.get()
                    if self.upload_with_retry(filename, image_data):
                        self.storage_manager.mark_as_uploaded(filename)
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
        
        for thread in threads:
            thread.start()
            
        try:
            for thread in threads:
                thread.join()
        except KeyboardInterrupt:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        self.running = False
        self.cap.release()
        self.logger.info("Service stopped")

class StorageManager:
    def __init__(self, base_path, max_size_gb, cleanup_threshold_gb, 
                 retention_days, logger):
        self.base_path = Path(base_path)
        self.max_size_gb = max_size_gb
        self.cleanup_threshold_gb = cleanup_threshold_gb
        self.retention_days = retention_days
        self.logger = logger
        self.running = True

    def store_image(self, image_data, filename):
        """Store image locally"""
        file_path = self.base_path / filename
        with open(file_path, 'wb') as f:
            f.write(image_data)

    def mark_as_uploaded(self, filename):
        """Mark file as successfully uploaded"""
        file_path = self.base_path / filename
        uploaded_path = self.base_path / 'uploaded' / filename
        uploaded_path.parent.mkdir(exist_ok=True)
        shutil.move(file_path, uploaded_path)

    def cleanup_old_files(self):
        """Remove old files to maintain storage limits"""
        try:
            current_size = sum(f.stat().st_size for f in self.base_path.rglob('*')) / (1024**3)
            
            if current_size > self.cleanup_threshold_gb:
                self.logger.info("Starting storage cleanup")
                
                # Remove old uploaded files first
                uploaded_path = self.base_path / 'uploaded'
                if uploaded_path.exists():
                    for file in sorted(uploaded_path.glob('*.jpg'),
                                     key=lambda x: x.stat().st_mtime):
                        file.unlink()
                        current_size = sum(f.stat().st_size for f in 
                                        self.base_path.rglob('*')) / (1024**3)
                        if current_size < self.cleanup_threshold_gb:
                            break

                # If still above threshold, remove old non-uploaded files
                if current_size > self.cleanup_threshold_gb:
                    for file in sorted(self.base_path.glob('*.jpg'),
                                     key=lambda x: x.stat().st_mtime):
                        file.unlink()
                        current_size = sum(f.stat().st_size for f in 
                                        self.base_path.rglob('*')) / (1024**3)
                        if current_size < self.cleanup_threshold_gb:
                            break

        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")

    def run_cleanup_thread(self):
        """Run periodic cleanup"""
        while self.running:
            self.cleanup_old_files()
            time.sleep(3600)  # Check every hour

class HealthMonitor:
    def __init__(self, config, logger, restart_callback):
        self.config = config
        self.logger = logger
        self.restart_callback = restart_callback
        self.running = True

    def check_system_health(self):
        """Check system resources"""
        cpu_percent = psutil.cpu_percent()
        memory_percent = psutil.virtual_memory().percent
        
        if (cpu_percent > self.config['max_cpu_percent'] or 
            memory_percent > self.config['max_memory_percent']):
            self.logger.warning(f"System resources critical: CPU={cpu_percent}%, "
                              f"Memory={memory_percent}%")
            if self.config['restart_on_failure']:
                self.restart_callback()

    def run(self):
        """Run periodic health checks"""
        while self.running:
            self.check_system_health()
            time.sleep(self.config['health_check_interval'])

def main():
    service = CameraService()
    service.run()

if __name__ == '__main__':
    main()
