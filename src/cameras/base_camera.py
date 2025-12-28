"""
Base Camera Interface

Abstract base class that defines the common interface for all camera types.
This ensures consistent behavior across USB, RTSP, and ONVIF cameras.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
import numpy as np
import logging
import time


class BaseCamera(ABC):
    """Abstract base class for all camera implementations"""
    
    def __init__(self, camera_id: str, camera_config: Dict[str, Any], 
                 global_config: Dict[str, Any], logger: logging.Logger):
        """
        Initialize camera with configuration
        
        Args:
            camera_id: Unique identifier for this camera
            camera_config: Camera-specific configuration
            global_config: Global service configuration  
            logger: Logger instance
        """
        self.camera_id = camera_id
        self.config = camera_config
        self.global_config = global_config
        self.logger = logger
        self.is_connected = False
        self.last_frame_time = 0
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = global_config.get('advanced', {}).get('reconnect_attempts', 3)
        
    @abstractmethod
    def setup(self) -> bool:
        """
        Initialize and connect to the camera
        
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def capture_frame(self) -> Optional[np.ndarray]:
        """
        Capture a single frame from the camera
        
        Returns:
            numpy.ndarray: Captured frame in BGR format, or None if failed
        """
        pass
    
    @abstractmethod
    def reconnect(self) -> bool:
        """
        Attempt to reconnect to the camera
        
        Returns:
            bool: True if reconnection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def cleanup(self) -> None:
        """Clean up camera resources"""
        pass
    
    @abstractmethod
    def get_camera_info(self) -> Dict[str, Any]:
        """
        Get camera information and status
        
        Returns:
            dict: Camera information including type, status, resolution, etc.
        """
        pass
    
    def validate_frame(self, frame: Optional[np.ndarray]) -> bool:
        """
        Validate captured frame
        
        Args:
            frame: Frame to validate
            
        Returns:
            bool: True if frame is valid, False otherwise
        """
        if frame is None or frame.size == 0:
            return False
            
        # Check for completely black or white frames
        avg_value = np.mean(frame)
        
        # Log warnings for low/high brightness but don't reject frames
        if avg_value < 5:
            self.logger.warning(f"Camera {self.camera_id}: Low brightness frame detected (avg={avg_value:.1f}) - possible low light conditions")
        elif avg_value > 250:
            self.logger.warning(f"Camera {self.camera_id}: High brightness frame detected (avg={avg_value:.1f}) - possible overexposure")
        
        # Only reject completely empty or corrupted frames
        return True
    
    def get_capture_interval(self) -> int:
        """Get capture interval for this camera"""
        return self.config.get('capture_interval', 300)
    
    def should_capture_now(self) -> bool:
        """Check if it's time to capture a new frame"""
        current_time = time.time()
        interval = self.get_capture_interval()
        return (current_time - self.last_frame_time) >= interval
    
    def update_frame_timestamp(self) -> None:
        """Update timestamp of last captured frame"""
        self.last_frame_time = time.time()
    
    def get_resolution(self) -> Tuple[int, int]:
        """Get configured resolution for this camera"""
        resolution = self.config.get('resolution', [1280, 720])
        return tuple(resolution)
    
    def get_fps(self) -> int:
        """Get configured FPS for this camera"""
        return self.config.get('fps', 30)
    
    def increment_reconnect_attempts(self) -> bool:
        """
        Increment reconnection attempt counter

        Returns:
            bool: True if should continue attempting, False if max reached
        """
        self.reconnect_attempts += 1
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            # Don't log here - CameraStateTracker handles consolidated logging
            return False
        return True
    
    def reset_reconnect_attempts(self) -> None:
        """Reset reconnection attempt counter"""
        self.reconnect_attempts = 0
    
    def __str__(self) -> str:
        """String representation of camera"""
        return f"{self.__class__.__name__}(id={self.camera_id}, type={self.config.get('type', 'unknown')})"