#!/usr/bin/env python3
"""
SAI-Cam Architecture Demonstration

Shows the transparent camera interface design without requiring
actual camera hardware or dependencies.
"""

import sys
import os
import json
from typing import Dict, Any, Optional
import logging

# Mock cv2 and onvif for demonstration
class MockCV2:
    CAP_FFMPEG = 1
    CAP_PROP_FPS = 2
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_BUFFERSIZE = 5
    IMREAD_COLOR = 1
    
    class VideoCapture:
        def __init__(self, source, backend=None):
            self.source = source
            self.opened = True
            
        def isOpened(self):
            return self.opened
            
        def set(self, prop, value):
            return True
            
        def get(self, prop):
            return 30.0 if prop == MockCV2.CAP_PROP_FPS else 640.0
            
        def read(self):
            import numpy as np
            return True, np.zeros((480, 640, 3), dtype=np.uint8)
            
        def grab(self):
            return True
            
        def release(self):
            self.opened = False

# Mock modules
sys.modules['cv2'] = MockCV2()
sys.modules['onvif'] = type('MockONVIF', (), {
    'ONVIFCamera': lambda *args, **kwargs: type('MockONVIFCamera', (), {
        'devicemgmt': type('MockDeviceMgmt', (), {
            'GetDeviceInformation': lambda: type('MockDeviceInfo', (), {
                'Manufacturer': 'Mock Camera',
                'Model': 'Test Model',
                'FirmwareVersion': '1.0.0',
                'SerialNumber': 'MOCK123'
            })(),
            'GetSystemDateAndTime': lambda: None
        })(),
        'create_media_service': lambda: type('MockMediaService', (), {
            'GetProfiles': lambda: [type('MockProfile', (), {
                'Name': 'Profile1',
                'token': 'token123'
            })()],
            'GetSnapshotUri': lambda x: type('MockSnapshotUri', (), {
                'Uri': 'http://mock.camera/snapshot'
            })()
        })()
    })()
})()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from cameras import (
    get_supported_camera_types,
    validate_camera_config,
    create_camera_from_config
)

def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    return logging.getLogger('ArchitectureDemo')

def demo_config_validation():
    """Demonstrate configuration validation"""
    print("\n" + "="*60)
    print("🔍 CONFIGURATION VALIDATION DEMO")
    print("="*60)
    
    # Test configurations
    test_configs = [
        # Valid USB config
        {
            'id': 'usb_cam1',
            'type': 'usb',
            'device_path': '/dev/video0',
            'resolution': [640, 480],
            'fps': 30
        },
        # Valid RTSP config
        {
            'id': 'rtsp_cam1',
            'type': 'rtsp',
            'rtsp_url': 'rtsp://admin:password@192.168.1.100:554/stream',
            'resolution': [1920, 1080],
            'fps': 30
        },
        # Valid ONVIF config
        {
            'id': 'onvif_cam1',
            'type': 'onvif',
            'address': '192.168.1.101',
            'port': 8000,
            'username': 'admin',
            'password': 'password'
        },
        # Invalid config - missing required field
        {
            'id': 'invalid_cam',
            'type': 'rtsp'
            # Missing rtsp_url
        },
        # Invalid config - bad camera type
        {
            'id': 'bad_type_cam',
            'type': 'invalid_type',
            'some_url': 'test'
        }
    ]
    
    for i, config in enumerate(test_configs, 1):
        print(f"\n📋 Test Config {i}: {config.get('id', 'unknown')}")
        print(f"   Type: {config.get('type', 'unknown')}")
        
        errors = validate_camera_config(config)
        if errors:
            print("   ❌ Validation FAILED:")
            for field, error in errors.items():
                print(f"      • {field}: {error}")
        else:
            print("   ✅ Validation PASSED")

def demo_camera_creation():
    """Demonstrate transparent camera creation"""
    print("\n" + "="*60)
    print("🏭 CAMERA CREATION DEMO")
    print("="*60)
    
    logger = setup_logging()
    
    global_config = {
        'device': {'id': 'demo-node', 'location': 'demo-lab'},
        'advanced': {
            'camera_init_wait': 1,
            'reconnect_attempts': 3,
            'reconnect_delay': 2
        }
    }
    
    # Camera configurations for all types
    camera_configs = [
        {
            'id': 'demo_usb',
            'type': 'usb',
            'device_index': 0,
            'resolution': [640, 480],
            'fps': 30,
            'capture_interval': 10
        },
        {
            'id': 'demo_rtsp',
            'type': 'rtsp',
            'rtsp_url': 'rtsp://demo:demo@demo.local:554/stream',
            'resolution': [1280, 720],
            'fps': 25,
            'capture_interval': 15
        },
        {
            'id': 'demo_onvif',
            'type': 'onvif',
            'address': 'demo.camera.local',
            'port': 8000,
            'username': 'demo',
            'password': 'demo123',
            'capture_interval': 20
        }
    ]
    
    created_cameras = []
    
    for config in camera_configs:
        try:
            print(f"\n🔨 Creating {config['type'].upper()} camera: {config['id']}")
            camera = create_camera_from_config(config, global_config, logger)
            print(f"   ✅ Successfully created: {camera}")
            
            # Get camera info
            info = camera.get_camera_info()
            print(f"   📊 Camera Info:")
            for key, value in info.items():
                print(f"      • {key}: {value}")
            
            created_cameras.append(camera)
            
        except Exception as e:
            print(f"   ❌ Failed to create camera: {e}")
    
    return created_cameras

def demo_unified_interface(cameras):
    """Demonstrate unified camera interface"""
    print("\n" + "="*60)
    print("🔄 UNIFIED INTERFACE DEMO")
    print("="*60)
    
    print("\n🎯 The key benefit: ALL camera types use the SAME interface!")
    print("   Whether USB, RTSP, or ONVIF - the workflow is identical:\n")
    
    # Show unified workflow
    workflow_code = '''
# UNIVERSAL CAMERA WORKFLOW - Works with ANY camera type!

def capture_from_any_camera(camera):
    """This function works transparently with USB, RTSP, or ONVIF cameras"""
    
    # 1. Setup camera (same method for all types)
    if camera.setup():
        print(f"✅ {camera.camera_id} connected")
        
        # 2. Capture frame (same method for all types)
        frame = camera.capture_frame()
        
        # 3. Validate frame (same method for all types)
        if camera.validate_frame(frame):
            print(f"📸 {camera.camera_id} captured valid frame")
            
            # 4. Process frame (your custom logic here)
            processed_frame = process_image(frame)
            
            # 5. Save or upload (same for all cameras)
            save_image(processed_frame, camera.camera_id)
            
        # 6. Cleanup (same method for all types)
        camera.cleanup()
    '''
    
    print(workflow_code)
    
    print("🌟 Benefits of this architecture:")
    print("   • Same code works with any camera type")
    print("   • Easy to add new camera types")
    print("   • Configuration-driven deployment")
    print("   • Consistent error handling")
    print("   • Transparent reconnection logic")
    
    # Demo with actual cameras
    for camera in cameras:
        print(f"\n🔧 Testing workflow with {camera.camera_id} ({camera.config.get('type')})")
        
        # Simulate setup
        try:
            if hasattr(camera, 'setup'):
                success = True  # Mock success for demo
                print(f"   📡 Setup: {'✅ Connected' if success else '❌ Failed'}")
                
                # Show interval behavior
                interval = camera.get_capture_interval()
                print(f"   ⏱️  Capture interval: {interval} seconds")
                
                # Show resolution
                resolution = camera.get_resolution()
                print(f"   📐 Resolution: {resolution[0]}x{resolution[1]}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")

def demo_configuration_examples():
    """Show configuration examples for all camera types"""
    print("\n" + "="*60)
    print("⚙️  CONFIGURATION EXAMPLES")
    print("="*60)
    
    examples = {
        'USB Camera': {
            'id': 'cam_usb_01',
            'type': 'usb',
            'device_path': '/dev/video0',  # or 'device_index': 0
            'resolution': [1280, 720],
            'fps': 30,
            'capture_interval': 300,
            'auto_exposure': True,
            'brightness': 50
        },
        'RTSP Camera': {
            'id': 'cam_rtsp_01',
            'type': 'rtsp',
            'rtsp_url': 'rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101',
            'resolution': [1920, 1080],
            'fps': 30,
            'capture_interval': 300,
            'buffer_size': 1
        },
        'ONVIF Camera': {
            'id': 'cam_onvif_01',
            'type': 'onvif',
            'address': '192.168.1.100',
            'port': 8000,
            'username': 'admin',
            'password': 'your_password_here',
            'capture_interval': 300,
            'timeout': 30
        }
    }
    
    for camera_type, config in examples.items():
        print(f"\n📝 {camera_type} Configuration:")
        print("   " + json.dumps(config, indent=6)[1:-1])

def main():
    """Main demonstration"""
    print("🏗️  SAI-CAM MULTI-CAMERA ARCHITECTURE DEMONSTRATION")
    print("=" * 70)
    
    print(f"\n📋 Supported Camera Types: {', '.join(get_supported_camera_types())}")
    
    # Demo configuration validation
    demo_config_validation()
    
    # Demo camera creation
    cameras = demo_camera_creation()
    
    # Demo unified interface
    demo_unified_interface(cameras)
    
    # Demo configuration examples
    demo_configuration_examples()
    
    print("\n" + "="*70)
    print("🎉 ARCHITECTURE DEMONSTRATION COMPLETE!")
    print("="*70)
    print("\n💡 Next steps:")
    print("   1. Install dependencies: pip3 install -r requirements.txt")
    print("   2. Configure your cameras in config.yaml")
    print("   3. Test with: python3 scripts/camera-test.py")
    print("   4. Deploy with the unified camera service")

if __name__ == '__main__':
    main()