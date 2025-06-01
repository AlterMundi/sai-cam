#!/usr/bin/env python3
"""
SAI-Cam Multi-Camera Test Script

Tests all supported camera types with a unified interface.
Demonstrates transparent camera operations across USB, RTSP, and ONVIF cameras.
"""

import sys
import os
import argparse
import logging
import yaml
import json
import time
from pathlib import Path
from typing import Dict, Any, List

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from cameras import (
    create_camera_from_config, 
    validate_camera_config, 
    get_supported_camera_types,
    BaseCamera
)
from config_helper import ConfigHelper


def setup_logging(level: str = 'INFO') -> logging.Logger:
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, level),
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    return logging.getLogger('CameraTest')


def load_test_config(config_path: str) -> Dict[str, Any]:
    """Load camera test configuration"""
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load config from {config_path}: {e}")


def create_default_test_config() -> Dict[str, Any]:
    """Create default test configuration"""
    return {
        'device': {
            'id': 'test-node',
            'location': 'test-lab'
        },
        'cameras': [
            {
                'id': 'test_usb',
                'type': 'usb',
                'device_path': '/dev/video0',
                'resolution': [640, 480],
                'fps': 30,
                'capture_interval': 5
            },
            {
                'id': 'test_rtsp',
                'type': 'rtsp',
                'rtsp_url': '${RTSP_URL:-rtsp://admin:password@192.168.1.100:554/stream}',
                'resolution': [1280, 720],
                'fps': 30,
                'capture_interval': 5
            },
            {
                'id': 'test_onvif',
                'type': 'onvif',
                'address': '${CAMERA_IP:-192.168.1.100}',
                'port': 8000,
                'username': 'admin',
                'password': '${CAMERA_PASSWORD:-your_password_here}',
                'capture_interval': 5
            }
        ],
        'advanced': {
            'camera_init_wait': 2,
            'reconnect_attempts': 3,
            'reconnect_delay': 5
        }
    }


def validate_cameras_config(cameras_config: List[Dict[str, Any]], logger: logging.Logger) -> bool:
    """Validate all camera configurations"""
    all_valid = True
    
    for i, camera_config in enumerate(cameras_config):
        logger.info(f"Validating camera {i+1}: {camera_config.get('id', 'unknown')}")
        
        errors = validate_camera_config(camera_config)
        if errors:
            logger.error(f"Camera {i+1} validation errors:")
            for field, error in errors.items():
                logger.error(f"  {field}: {error}")
            all_valid = False
        else:
            logger.info(f"Camera {i+1} configuration is valid")
    
    return all_valid


def test_camera_creation(camera_config: Dict[str, Any], global_config: Dict[str, Any], 
                        logger: logging.Logger) -> BaseCamera:
    """Test camera creation"""
    camera_id = camera_config['id']
    camera_type = camera_config.get('type', 'unknown')
    
    logger.info(f"Creating {camera_type} camera: {camera_id}")
    
    try:
        camera = create_camera_from_config(camera_config, global_config, logger)
        logger.info(f"Successfully created camera {camera_id}")
        return camera
    except Exception as e:
        logger.error(f"Failed to create camera {camera_id}: {e}")
        raise


def test_camera_setup(camera: BaseCamera, logger: logging.Logger) -> bool:
    """Test camera setup/connection"""
    logger.info(f"Testing setup for camera {camera.camera_id}")
    
    try:
        success = camera.setup()
        if success:
            logger.info(f"Camera {camera.camera_id} setup successful")
            
            # Get camera info
            info = camera.get_camera_info()
            logger.info(f"Camera {camera.camera_id} info:")
            for key, value in info.items():
                logger.info(f"  {key}: {value}")
            
            return True
        else:
            logger.error(f"Camera {camera.camera_id} setup failed")
            return False
            
    except Exception as e:
        logger.error(f"Camera {camera.camera_id} setup error: {e}")
        return False


def test_camera_capture(camera: BaseCamera, logger: logging.Logger, 
                       save_path: Path = None) -> bool:
    """Test camera frame capture"""
    logger.info(f"Testing capture for camera {camera.camera_id}")
    
    try:
        frame = camera.capture_frame()
        
        if frame is not None:
            height, width = frame.shape[:2]
            logger.info(f"Camera {camera.camera_id} captured frame: {width}x{height}")
            
            # Validate frame
            if camera.validate_frame(frame):
                logger.info(f"Camera {camera.camera_id} frame validation passed")
                
                # Save frame if path provided
                if save_path:
                    import cv2
                    filename = save_path / f"{camera.camera_id}_test.jpg"
                    cv2.imwrite(str(filename), frame)
                    logger.info(f"Saved test image: {filename}")
                
                return True
            else:
                logger.warning(f"Camera {camera.camera_id} frame validation failed")
                return False
        else:
            logger.error(f"Camera {camera.camera_id} capture returned None")
            return False
            
    except Exception as e:
        logger.error(f"Camera {camera.camera_id} capture error: {e}")
        return False


def run_camera_test(camera_config: Dict[str, Any], global_config: Dict[str, Any], 
                   logger: logging.Logger, save_path: Path = None) -> Dict[str, Any]:
    """Run complete test for a single camera"""
    camera_id = camera_config['id']
    results = {
        'camera_id': camera_id,
        'type': camera_config.get('type'),
        'creation': False,
        'setup': False,
        'capture': False,
        'cleanup': False,
        'errors': []
    }
    
    camera = None
    
    try:
        # Test camera creation
        camera = test_camera_creation(camera_config, global_config, logger)
        results['creation'] = True
        
        # Test camera setup
        if test_camera_setup(camera, logger):
            results['setup'] = True
            
            # Test frame capture
            if test_camera_capture(camera, logger, save_path):
                results['capture'] = True
        
        # Test cleanup
        camera.cleanup()
        results['cleanup'] = True
        logger.info(f"Camera {camera_id} cleanup completed")
        
    except Exception as e:
        error_msg = f"Camera {camera_id} test failed: {e}"
        logger.error(error_msg)
        results['errors'].append(error_msg)
    
    finally:
        if camera:
            try:
                camera.cleanup()
            except Exception:
                pass
    
    return results


def main():
    """Main test function"""
    parser = argparse.ArgumentParser(description='SAI-Cam Multi-Camera Test')
    parser.add_argument('--config', type=str, 
                       help='Path to test configuration file')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO', help='Logging level')
    parser.add_argument('--save-images', action='store_true',
                       help='Save test images to output directory')
    parser.add_argument('--output-dir', type=str, default='./test_output',
                       help='Output directory for test images and results')
    parser.add_argument('--camera-type', choices=get_supported_camera_types(),
                       help='Test only specific camera type')
    parser.add_argument('--generate-config', action='store_true',
                       help='Generate example test configuration and exit')
    parser.add_argument('--env-file', type=str, default='.env',
                       help='Environment file to load (default: .env)')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.log_level)
    
    # Setup configuration helper and load environment variables
    config_helper = ConfigHelper(logger)
    config_helper.load_env_file(args.env_file)
    
    # Generate config if requested
    if args.generate_config:
        config = create_default_test_config()
        config_file = 'camera-test-config.yaml'
        with open(config_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Generated example configuration: {config_file}")
        return 0
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    save_path = output_dir if args.save_images else None
    
    # Load configuration
    if args.config:
        logger.info(f"Loading configuration from: {args.config}")
        config = load_test_config(args.config)
        # Expand environment variables in config
        config = config_helper.expand_config_variables(config)
    else:
        logger.info("Using default test configuration")
        config = create_default_test_config()
        # Expand environment variables in default config too
        config = config_helper.expand_config_variables(config)
    
    # Validate configuration
    cameras_config = config.get('cameras', [])
    if not cameras_config:
        logger.error("No cameras configured for testing")
        return 1
    
    # Filter by camera type if specified
    if args.camera_type:
        cameras_config = [c for c in cameras_config if c.get('type') == args.camera_type]
        logger.info(f"Testing only {args.camera_type} cameras")
    
    if not cameras_config:
        logger.error(f"No cameras found for type: {args.camera_type}")
        return 1
    
    logger.info(f"Found {len(cameras_config)} cameras to test")
    logger.info(f"Supported camera types: {', '.join(get_supported_camera_types())}")
    
    # Validate all configurations
    if not validate_cameras_config(cameras_config, logger):
        logger.error("Configuration validation failed")
        return 1
    
    # Run tests for each camera
    all_results = []
    successful_tests = 0
    
    for camera_config in cameras_config:
        logger.info(f"\n{'='*50}")
        logger.info(f"Testing camera: {camera_config['id']} ({camera_config.get('type')})")
        logger.info(f"{'='*50}")
        
        results = run_camera_test(camera_config, config, logger, save_path)
        all_results.append(results)
        
        # Check if test was successful
        if results['creation'] and results['setup'] and results['capture'] and results['cleanup']:
            successful_tests += 1
            logger.info(f"✅ Camera {results['camera_id']} - ALL TESTS PASSED")
        else:
            logger.error(f"❌ Camera {results['camera_id']} - TESTS FAILED")
    
    # Save results
    results_file = output_dir / 'test_results.json'
    with open(results_file, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    # Print summary
    logger.info(f"\n{'='*50}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*50}")
    logger.info(f"Total cameras tested: {len(all_results)}")
    logger.info(f"Successful tests: {successful_tests}")
    logger.info(f"Failed tests: {len(all_results) - successful_tests}")
    logger.info(f"Results saved to: {results_file}")
    
    if save_path:
        logger.info(f"Test images saved to: {output_dir}")
    
    return 0 if successful_tests == len(all_results) else 1


if __name__ == '__main__':
    sys.exit(main())