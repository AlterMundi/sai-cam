"""
Camera Factory

Factory pattern implementation for creating camera instances.
Provides transparent camera instantiation based on configuration.
"""

from typing import Dict, Any
import logging

from .base_camera import BaseCamera
from .usb_camera import USBCamera
from .rtsp_camera import RTSPCamera
from .onvif_camera import ONVIFCameraImpl


def create_camera(camera_id: str, camera_config: Dict[str, Any], 
                 global_config: Dict[str, Any], logger: logging.Logger) -> BaseCamera:
    """
    Create a camera instance based on configuration
    
    Args:
        camera_id: Unique identifier for the camera
        camera_config: Camera-specific configuration dict
        global_config: Global service configuration dict
        logger: Logger instance
        
    Returns:
        BaseCamera: Camera instance implementing the common interface
        
    Raises:
        ValueError: If camera type is unsupported or configuration is invalid
        ImportError: If required dependencies are missing
    """
    camera_type = camera_config.get('type', 'rtsp').lower()
    
    logger.debug(f"Creating camera {camera_id} of type {camera_type}")
    
    if camera_type == 'usb':
        return USBCamera(camera_id, camera_config, global_config, logger)
    elif camera_type == 'rtsp':
        return RTSPCamera(camera_id, camera_config, global_config, logger)
    elif camera_type == 'onvif':
        return ONVIFCameraImpl(camera_id, camera_config, global_config, logger)
    else:
        raise ValueError(f"Unsupported camera type: {camera_type}. Supported types: usb, rtsp, onvif")


def get_supported_camera_types() -> list:
    """
    Get list of supported camera types
    
    Returns:
        list: List of supported camera type strings
    """
    return ['usb', 'rtsp', 'onvif']


def validate_camera_config(camera_config: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate camera configuration
    
    Args:
        camera_config: Camera configuration dict
        
    Returns:
        dict: Dictionary of validation errors (empty if valid)
    """
    errors = {}
    
    # Check required fields
    if 'id' not in camera_config:
        errors['id'] = "Camera ID is required"
    
    camera_type = camera_config.get('type', 'rtsp').lower()
    if camera_type not in get_supported_camera_types():
        errors['type'] = f"Unsupported camera type: {camera_type}"
        return errors  # Return early if type is invalid
    
    # Type-specific validation
    if camera_type == 'usb':
        if not camera_config.get('device_path') and camera_config.get('device_index') is None:
            errors['device'] = "USB cameras require either 'device_path' or 'device_index'"
    
    elif camera_type == 'rtsp':
        if not camera_config.get('rtsp_url'):
            errors['rtsp_url'] = "RTSP cameras require 'rtsp_url'"
    
    elif camera_type == 'onvif':
        if not camera_config.get('address'):
            errors['address'] = "ONVIF cameras require 'address'"
    
    # Validate common optional fields
    if 'resolution' in camera_config:
        resolution = camera_config['resolution']
        if not isinstance(resolution, list) or len(resolution) != 2:
            errors['resolution'] = "Resolution must be [width, height]"
        elif not all(isinstance(x, int) and x > 0 for x in resolution):
            errors['resolution'] = "Resolution values must be positive integers"
    
    if 'fps' in camera_config:
        fps = camera_config['fps']
        if not isinstance(fps, (int, float)) or fps <= 0:
            errors['fps'] = "FPS must be a positive number"
    
    if 'capture_interval' in camera_config:
        interval = camera_config['capture_interval']
        if not isinstance(interval, (int, float)) or interval <= 0:
            errors['capture_interval'] = "Capture interval must be a positive number"
    
    return errors


def create_camera_from_config(camera_config: Dict[str, Any], 
                            global_config: Dict[str, Any], 
                            logger: logging.Logger) -> BaseCamera:
    """
    Create camera with validation from configuration
    
    Args:
        camera_config: Camera configuration dict
        global_config: Global service configuration dict
        logger: Logger instance
        
    Returns:
        BaseCamera: Configured camera instance
        
    Raises:
        ValueError: If configuration is invalid
    """
    # Validate configuration
    errors = validate_camera_config(camera_config)
    if errors:
        error_msg = "Camera configuration errors: " + ", ".join([f"{k}: {v}" for k, v in errors.items()])
        raise ValueError(error_msg)
    
    camera_id = camera_config['id']
    return create_camera(camera_id, camera_config, global_config, logger)