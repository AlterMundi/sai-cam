"""
ONVIF Camera Implementation

Implements camera interface for ONVIF-compatible IP cameras.
Based on the proven onvif-test.py implementation.
"""

import time
from typing import Optional, Dict, Any
import numpy as np
import requests
from requests.auth import HTTPDigestAuth
import cv2

try:
    from onvif import ONVIFCamera
except ImportError:
    ONVIFCamera = None

from .base_camera import BaseCamera


class ONVIFCameraImpl(BaseCamera):
    """ONVIF camera implementation using snapshot capture"""
    
    def __init__(self, camera_id: str, camera_config: Dict[str, Any], 
                 global_config: Dict[str, Any], logger):
        super().__init__(camera_id, camera_config, global_config, logger)
        
        if ONVIFCamera is None:
            raise ImportError("onvif library not available. Install with: pip install onvif")
        
        self.onvif_camera = None
        self.snapshot_uri = None
        self.media_service = None
        
        # ONVIF-specific configuration
        # Use environment variables with config file fallback
        import sys
        import os
        # Add parent directory to path to find config_helper in deployed environment
        parent_dir = os.path.dirname(os.path.dirname(__file__))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        
        from config_helper import ConfigHelper
        self.config_helper = ConfigHelper(logger)
        
        self.address = self.config_helper.get_secure_value(
            'CAMERA_IP', 
            camera_config.get('address'),
            required=True,
            description=f"IP address for ONVIF camera {camera_id}"
        )
        self.port = int(self.config_helper.get_secure_value(
            'CAMERA_PORT',
            camera_config.get('port'),
            default=8000
        ))
        self.username = self.config_helper.get_secure_value(
            'CAMERA_USERNAME',
            camera_config.get('username'),
            default='admin'
        )
        self.password = self.config_helper.get_secure_value(
            'CAMERA_PASSWORD',
            camera_config.get('password'),
            required=True,
            is_password=True,
            description=f"password for ONVIF camera {camera_id}"
        )
        self.timeout = camera_config.get('timeout', 30)
        
        if not self.address:
            raise ValueError(f"Camera {camera_id}: 'address' is required for ONVIF cameras")
    
    def setup(self) -> bool:
        """Initialize ONVIF camera connection"""
        try:
            self.logger.info(f"Camera {self.camera_id}: Initializing ONVIF camera at {self.address}:{self.port}")
            
            # Initialize ONVIF camera connection with WSDL path
            # Detect correct WSDL path based on Python version and environment
            import sys
            import os
            from pathlib import Path
            
            # Allow WSDL path to be configured via environment variable or config
            wsdl_path = self.config_helper.get_secure_value(
                'ONVIF_WSDL_PATH',
                self.config.get('wsdl_path'),
                description=f"ONVIF WSDL path for camera {self.camera_id}"
            )
            
            if not wsdl_path:
                # Auto-detect WSDL path
                import glob
                potential_paths = [
                    f'/opt/sai-cam/venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/wsdl/',
                    '/opt/sai-cam/venv/lib/python3.4/site-packages/wsdl/',  # Legacy path from working script
                    f'/opt/sai-cam/venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/onvif/wsdl/',
                    # Additional common paths
                    '/usr/local/lib/python3*/site-packages/wsdl/',
                    './venv/lib/python3*/site-packages/wsdl/',
                ]

                # Track checked paths for error reporting
                checked_paths = []

                # Find the first existing WSDL path
                for path in potential_paths:
                    # Handle glob patterns
                    if '*' in path:
                        matches = glob.glob(path)
                        if matches:
                            resolved_path = matches[0]
                            if os.path.exists(resolved_path):
                                wsdl_path = resolved_path
                                self.logger.debug(f"Camera {self.camera_id}: Auto-detected WSDL path: {wsdl_path}")
                                break
                        checked_paths.append(f"{path} (no matches)")
                    elif os.path.exists(path):
                        wsdl_path = path
                        self.logger.debug(f"Camera {self.camera_id}: Auto-detected WSDL path: {wsdl_path}")
                        break
                    else:
                        checked_paths.append(path)

            if wsdl_path:
                self.onvif_camera = ONVIFCamera(
                    self.address,
                    self.port,
                    self.username,
                    self.password,
                    wsdl_path
                )
            else:
                # Log actionable error with checked paths
                self.logger.error(
                    f"Camera {self.camera_id}: ONVIF WSDL files not found. "
                    f"Checked paths: {', '.join(checked_paths[:3])}"
                )
                self.logger.error(
                    f"Camera {self.camera_id}: To fix WSDL issue: "
                    f"1) Reinstall onvif-zeep: pip install --force-reinstall onvif-zeep, "
                    f"2) Set ONVIF_WSDL_PATH environment variable, or "
                    f"3) Add 'wsdl_path' to camera config in config.yaml"
                )
                # Attempt without WSDL path (some library versions may work)
                self.logger.warning(f"Camera {self.camera_id}: Attempting ONVIF connection without explicit WSDL path...")
                try:
                    self.onvif_camera = ONVIFCamera(
                        self.address,
                        self.port,
                        self.username,
                        self.password
                    )
                except Exception as wsdl_error:
                    self.logger.error(
                        f"Camera {self.camera_id}: ONVIF connection failed without WSDL: {wsdl_error}. "
                        f"This camera requires WSDL files to function."
                    )
                    self.is_connected = False
                    return False
            
            # Test basic connectivity
            try:
                device_info = self.onvif_camera.devicemgmt.GetDeviceInformation()
                self.logger.info(f"Camera {self.camera_id}: Connected to {device_info.Manufacturer} {device_info.Model}")
            except Exception as e:
                self.logger.warning(f"Camera {self.camera_id}: Could not get device info: {e}")
            
            # Get media service
            self.media_service = self.onvif_camera.create_media_service()
            
            # Get available profiles
            profiles = self.media_service.GetProfiles()
            if not profiles:
                self.logger.error(f"Camera {self.camera_id}: No ONVIF profiles found")
                return False
            
            # Use the first available profile
            profile = profiles[0]
            self.logger.info(f"Camera {self.camera_id}: Using ONVIF profile: {profile.Name}")
            
            # Get snapshot URI
            snapshot_uri_response = self.media_service.GetSnapshotUri({'ProfileToken': profile.token})
            self.snapshot_uri = snapshot_uri_response.Uri
            self.logger.info(f"Camera {self.camera_id}: ONVIF snapshot URI obtained")
            self.logger.debug(f"Camera {self.camera_id}: Snapshot URI: {self.snapshot_uri}")
            
            self.is_connected = True
            self.reset_reconnect_attempts()
            return True
            
        except Exception as e:
            self.logger.error(f"Camera {self.camera_id}: ONVIF setup error: {str(e)}", exc_info=True)
            self.is_connected = False
            return False
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """Capture snapshot from ONVIF camera"""
        if not self.is_connected or not self.snapshot_uri:
            # Debug level - CameraStateTracker handles user-visible logging
            self.logger.debug(f"Camera {self.camera_id}: Not connected or no snapshot URI")
            return None

        try:
            self.logger.debug(f"Camera {self.camera_id}: Downloading ONVIF snapshot")

            # Download snapshot using HTTP Digest authentication
            response = requests.get(
                self.snapshot_uri,
                auth=HTTPDigestAuth(self.username, self.password),
                timeout=self.timeout
            )

            if response.status_code == 200:
                # Convert image bytes to OpenCV format
                nparr = np.frombuffer(response.content, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if frame is not None:
                    self.logger.debug(f"Camera {self.camera_id}: ONVIF snapshot captured")
                    return frame
                else:
                    self.logger.debug(f"Camera {self.camera_id}: Failed to decode image data")
                    return None
            else:
                # Log HTTP errors at debug level (CameraStateTracker handles consolidated logging)
                self.logger.debug(f"Camera {self.camera_id}: ONVIF snapshot HTTP {response.status_code}")
                if response.status_code == 401:
                    # Auth errors are more serious - log at warning but still rate-limited by caller
                    self.logger.warning(f"Camera {self.camera_id}: Authentication failed - check credentials")
                return None

        except requests.exceptions.Timeout:
            self.logger.debug(f"Camera {self.camera_id}: ONVIF snapshot timeout")
            return None
        except requests.exceptions.ConnectionError:
            self.logger.debug(f"Camera {self.camera_id}: ONVIF connection error")
            return None
        except Exception as e:
            self.logger.debug(f"Camera {self.camera_id}: ONVIF capture error: {str(e)}")
            return None
    
    def reconnect(self) -> bool:
        """Attempt to reconnect to ONVIF camera"""
        if not self.increment_reconnect_attempts():
            return False

        # Debug level - CameraStateTracker logs consolidated status
        self.logger.debug(f"Camera {self.camera_id}: ONVIF reconnection attempt {self.reconnect_attempts}")

        # Clean up existing connection
        self.cleanup()

        # Wait before reconnecting
        reconnect_delay = self.global_config.get('advanced', {}).get('reconnect_delay', 5)
        time.sleep(reconnect_delay)

        # Attempt to reconnect
        return self.setup()
    
    def cleanup(self) -> None:
        """Clean up ONVIF camera resources"""
        self.logger.debug(f"Camera {self.camera_id}: Cleaning up ONVIF resources")
        
        self.onvif_camera = None
        self.media_service = None
        self.snapshot_uri = None
        self.is_connected = False
    
    def get_camera_info(self) -> Dict[str, Any]:
        """Get ONVIF camera information"""
        info = {
            'camera_id': self.camera_id,
            'type': 'onvif',
            'address': self.address,
            'port': self.port,
            'username': self.username,
            'is_connected': self.is_connected,
            'snapshot_uri_available': self.snapshot_uri is not None,
            'reconnect_attempts': self.reconnect_attempts,
            'capture_interval': self.get_capture_interval()
        }
        
        # Add device information if available
        if self.onvif_camera and self.is_connected:
            try:
                device_info = self.onvif_camera.devicemgmt.GetDeviceInformation()
                info.update({
                    'manufacturer': device_info.Manufacturer,
                    'model': device_info.Model,
                    'firmware_version': device_info.FirmwareVersion,
                    'serial_number': device_info.SerialNumber
                })
            except Exception:
                pass
        
        return info