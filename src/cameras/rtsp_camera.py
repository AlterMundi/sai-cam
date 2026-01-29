"""
RTSP Camera Implementation

Implements camera interface for RTSP network cameras.
Based on the existing camera_service.py RTSP implementation.
"""

import time
from typing import Optional, Dict, Any
import numpy as np
import cv2
from threading import Lock

from .base_camera import BaseCamera
try:
    from ..logging_utils import redact_url_credentials
except ImportError:
    from logging_utils import redact_url_credentials


class RTSPCamera(BaseCamera):
    """RTSP camera implementation using OpenCV VideoCapture"""
    
    def __init__(self, camera_id: str, camera_config: Dict[str, Any], 
                 global_config: Dict[str, Any], logger):
        super().__init__(camera_id, camera_config, global_config, logger)
        
        self.cap = None
        self.lock = Lock()
        
        # RTSP-specific configuration
        self.rtsp_url = camera_config.get('rtsp_url')
        if not self.rtsp_url:
            raise ValueError(f"Camera {camera_id}: 'rtsp_url' is required for RTSP cameras")
        
        self.resolution = self.get_resolution()
        self.fps = self.get_fps()
        
        # Advanced RTSP settings
        self.buffer_size = camera_config.get('buffer_size', 0)
        self.init_wait = global_config.get('advanced', {}).get('camera_init_wait', 2)
    
    def setup(self) -> bool:
        """Initialize RTSP camera connection"""
        try:
            self.logger.info(f"Camera {self.camera_id}: Initializing RTSP with URL: {redact_url_credentials(self.rtsp_url)}")
            
            with self.lock:
                # Initialize the capture with FFMPEG backend
                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                
                if not self.cap.isOpened():
                    self.logger.error(f"Camera {self.camera_id}: Failed to open RTSP stream")
                    return False
                
                # Set camera properties
                self.cap.set(cv2.CAP_PROP_FPS, self.fps)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
                
                self.logger.debug(f"Camera {self.camera_id}: FPS set to {self.fps}")
                self.logger.debug(f"Camera {self.camera_id}: Resolution set to {self.resolution[0]}x{self.resolution[1]}")
                
                # Wait for initialization
                time.sleep(self.init_wait)
                
                if not self.cap.isOpened():
                    self.logger.error(f"Camera {self.camera_id}: RTSP stream not available after initialization")
                    return False
                
                # Get actual camera properties
                actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = self.cap.get(cv2.CAP_PROP_FPS)

                # Validate connection with a test frame read
                # isOpened() can return True before auth completes
                ret, test_frame = self.cap.read()
                if not ret or test_frame is None:
                    self.logger.error(
                        f"Camera {self.camera_id}: RTSP stream opened but test frame failed "
                        f"(likely auth rejected or codec unsupported)"
                    )
                    self.cap.release()
                    self.cap = None
                    return False

                self.logger.info(
                    f"Camera {self.camera_id}: RTSP initialized and validated: "
                    f"{actual_width}x{actual_height} @ {actual_fps:.1f}fps"
                )

                self.is_connected = True
                self.reset_reconnect_attempts()
                return True
                
        except Exception as e:
            self.logger.error(f"Camera {self.camera_id}: RTSP setup error: {str(e)}", exc_info=True)
            self.is_connected = False
            return False
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture frame from RTSP stream"""
        if not self.is_connected:
            return None

        try:
            with self.lock:
                if not self.cap or not self.cap.isOpened():
                    self.logger.warning(f"Camera {self.camera_id}: RTSP stream closed unexpectedly")
                    self.is_connected = False
                    return None

                ret, frame = self.cap.read()

                if not ret or frame is None:
                    self.logger.warning(f"Camera {self.camera_id}: Frame read failed (stream may have dropped)")
                    return None

                return frame

        except Exception as e:
            self.logger.warning(f"Camera {self.camera_id}: RTSP capture error: {str(e)}")
            return None
    
    def grab_frame(self) -> bool:
        """Grab frame without retrieving (useful for keeping stream alive)"""
        if not self.is_connected:
            return False
        
        try:
            with self.lock:
                if self.cap and self.cap.isOpened():
                    return self.cap.grab()
                return False
        except Exception:
            return False
    
    def reconnect(self) -> bool:
        """Attempt to reconnect to RTSP stream"""
        if not self.increment_reconnect_attempts():
            return False

        # Debug level - CameraStateTracker logs consolidated status
        self.logger.debug(f"Camera {self.camera_id}: RTSP reconnection attempt {self.reconnect_attempts}")

        # Clean up existing connection
        self.cleanup()

        # Wait before reconnecting
        reconnect_delay = self.global_config.get('advanced', {}).get('reconnect_delay', 5)
        time.sleep(reconnect_delay)

        # Attempt to reconnect
        return self.setup()
    
    def cleanup(self) -> None:
        """Clean up RTSP camera resources"""
        self.logger.debug(f"Camera {self.camera_id}: Cleaning up RTSP resources")
        
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
        
        self.is_connected = False
    
    def get_camera_info(self) -> Dict[str, Any]:
        """Get RTSP camera information"""
        info = {
            'camera_id': self.camera_id,
            'type': 'rtsp',
            'rtsp_url': self.rtsp_url,
            'resolution': self.resolution,
            'fps': self.fps,
            'is_connected': self.is_connected,
            'reconnect_attempts': self.reconnect_attempts,
            'capture_interval': self.get_capture_interval()
        }
        
        # Add actual stream properties if connected
        if self.cap and self.is_connected:
            try:
                with self.lock:
                    if self.cap.isOpened():
                        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                        
                        info.update({
                            'actual_resolution': [actual_width, actual_height],
                            'actual_fps': actual_fps,
                            'stream_open': True
                        })
            except Exception:
                info['stream_open'] = False
        else:
            info['stream_open'] = False
        
        return info