"""
USB Camera Implementation

Implements camera interface for USB/webcam devices.
Supports both device paths (/dev/videoX) and device indices.
"""

import time
from typing import Optional, Dict, Any
import numpy as np
import cv2
from threading import Lock
import os

from .base_camera import BaseCamera


class USBCamera(BaseCamera):
    """USB camera implementation using OpenCV VideoCapture"""
    
    def __init__(self, camera_id: str, camera_config: Dict[str, Any], 
                 global_config: Dict[str, Any], logger):
        super().__init__(camera_id, camera_config, global_config, logger)
        
        self.cap = None
        self.lock = Lock()
        
        # USB-specific configuration
        self.device_path = camera_config.get('device_path')
        self.device_index = camera_config.get('device_index')
        
        # Determine device identifier
        if self.device_path:
            self.device_id = self.device_path
        elif self.device_index is not None:
            self.device_id = self.device_index
        else:
            # Default to /dev/video0 or index 0
            self.device_id = camera_config.get('device_id', '/dev/video0')
            if isinstance(self.device_id, str) and not os.path.exists(self.device_id):
                self.device_id = 0  # Fallback to index 0
        
        self.resolution = self.get_resolution()
        self.fps = self.get_fps()
        
        # USB camera settings
        self.buffer_size = camera_config.get('buffer_size', 1)
        self.init_wait = global_config.get('advanced', {}).get('camera_init_wait', 2)
        
        # Auto-exposure and other camera controls
        self.auto_exposure = camera_config.get('auto_exposure', True)
        self.brightness = camera_config.get('brightness')
        self.contrast = camera_config.get('contrast')
        self.saturation = camera_config.get('saturation')
    
    def setup(self) -> bool:
        """Initialize USB camera connection"""
        try:
            self.logger.info(f"Camera {self.camera_id}: Initializing USB camera at {self.device_id}")
            
            # Check if device exists (for device paths)
            if isinstance(self.device_id, str) and not os.path.exists(self.device_id):
                self.logger.error(f"Camera {self.camera_id}: Device {self.device_id} does not exist")
                return False
            
            with self.lock:
                # Initialize the capture
                self.cap = cv2.VideoCapture(self.device_id)
                
                if not self.cap.isOpened():
                    self.logger.error(f"Camera {self.camera_id}: Failed to open USB camera")
                    return False
                
                # Set camera properties
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
                
                # Set camera controls if specified
                if not self.auto_exposure:
                    self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # Manual exposure
                
                if self.brightness is not None:
                    self.cap.set(cv2.CAP_PROP_BRIGHTNESS, self.brightness)
                
                if self.contrast is not None:
                    self.cap.set(cv2.CAP_PROP_CONTRAST, self.contrast)
                
                if self.saturation is not None:
                    self.cap.set(cv2.CAP_PROP_SATURATION, self.saturation)
                
                # Wait for camera to initialize
                time.sleep(self.init_wait)
                
                # Test frame capture
                ret, test_frame = self.cap.read()
                if not ret or test_frame is None:
                    self.logger.error(f"Camera {self.camera_id}: Failed to capture test frame")
                    return False
                
                # Get actual camera properties
                actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                
                self.logger.info(f"Camera {self.camera_id}: USB camera initialized successfully: {actual_width}x{actual_height} @ {actual_fps:.1f}fps")
                
                self.is_connected = True
                self.reset_reconnect_attempts()
                return True
                
        except Exception as e:
            self.logger.error(f"Camera {self.camera_id}: USB setup error: {str(e)}", exc_info=True)
            self.is_connected = False
            return False
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture frame from USB camera"""
        if not self.is_connected:
            return None
        
        try:
            with self.lock:
                if not self.cap or not self.cap.isOpened():
                    self.logger.warning(f"Camera {self.camera_id}: USB camera not available")
                    return None
                
                self.logger.debug(f"Camera {self.camera_id}: Capturing new USB frame")
                ret, frame = self.cap.read()
                
                if not ret or frame is None:
                    self.logger.warning(f"Camera {self.camera_id}: Failed to read USB frame")
                    return None
                
                return frame
                
        except Exception as e:
            self.logger.error(f"Camera {self.camera_id}: USB capture error: {str(e)}", exc_info=True)
            return None
    
    def set_camera_property(self, prop: int, value: float) -> bool:
        """Set camera property"""
        try:
            with self.lock:
                if self.cap and self.cap.isOpened():
                    return self.cap.set(prop, value)
                return False
        except Exception as e:
            self.logger.error(f"Camera {self.camera_id}: Error setting property {prop}={value}: {e}")
            return False
    
    def get_camera_property(self, prop: int) -> float:
        """Get camera property"""
        try:
            with self.lock:
                if self.cap and self.cap.isOpened():
                    return self.cap.get(prop)
                return -1
        except Exception:
            return -1
    
    def list_available_devices(self) -> list:
        """List available USB camera devices"""
        devices = []
        
        # Check /dev/video* devices
        for i in range(10):
            device_path = f"/dev/video{i}"
            if os.path.exists(device_path):
                devices.append(device_path)
        
        # Test device indices
        for i in range(5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                devices.append(i)
                cap.release()
        
        return devices
    
    def reconnect(self) -> bool:
        """Attempt to reconnect to USB camera"""
        if not self.increment_reconnect_attempts():
            return False
        
        self.logger.warning(f"Camera {self.camera_id}: Attempting USB reconnection (attempt {self.reconnect_attempts})")
        
        # Clean up existing connection
        self.cleanup()
        
        # Wait before reconnecting
        reconnect_delay = self.global_config.get('advanced', {}).get('reconnect_delay', 5)
        time.sleep(reconnect_delay)
        
        # Attempt to reconnect
        return self.setup()
    
    def cleanup(self) -> None:
        """Clean up USB camera resources"""
        self.logger.debug(f"Camera {self.camera_id}: Cleaning up USB resources")
        
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
        
        self.is_connected = False
    
    def get_camera_info(self) -> Dict[str, Any]:
        """Get USB camera information"""
        info = {
            'camera_id': self.camera_id,
            'type': 'usb',
            'device_id': self.device_id,
            'resolution': self.resolution,
            'fps': self.fps,
            'is_connected': self.is_connected,
            'reconnect_attempts': self.reconnect_attempts,
            'capture_interval': self.get_capture_interval(),
            'auto_exposure': self.auto_exposure
        }
        
        # Add actual camera properties if connected
        if self.cap and self.is_connected:
            try:
                with self.lock:
                    if self.cap.isOpened():
                        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                        brightness = self.cap.get(cv2.CAP_PROP_BRIGHTNESS)
                        contrast = self.cap.get(cv2.CAP_PROP_CONTRAST)
                        
                        info.update({
                            'actual_resolution': [actual_width, actual_height],
                            'actual_fps': actual_fps,
                            'brightness': brightness,
                            'contrast': contrast,
                            'camera_open': True
                        })
            except Exception:
                info['camera_open'] = False
        else:
            info['camera_open'] = False
        
        return info