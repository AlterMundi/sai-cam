"""
SAI-Cam Camera Module

Provides unified camera interface supporting multiple camera types:
- USB cameras
- RTSP network cameras  
- ONVIF cameras

All camera types implement the same interface for transparent usage.
"""

from .base_camera import BaseCamera
from .camera_factory import create_camera, create_camera_from_config, validate_camera_config, get_supported_camera_types
from .usb_camera import USBCamera
from .rtsp_camera import RTSPCamera
from .onvif_camera import ONVIFCameraImpl

__all__ = [
    'BaseCamera', 
    'create_camera', 
    'create_camera_from_config',
    'validate_camera_config',
    'get_supported_camera_types',
    'USBCamera',
    'RTSPCamera', 
    'ONVIFCameraImpl'
]