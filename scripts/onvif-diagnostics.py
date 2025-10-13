#!/usr/bin/env python3
"""
SAI-Cam ONVIF Camera Diagnostic Tool
Tests ONVIF camera connectivity and capabilities

Usage:
    python3 scripts/onvif-diagnostics.py --host 192.168.220.10 --user admin --password Saicam1!
    python3 scripts/onvif-diagnostics.py --config /etc/sai-cam/config.yaml
"""

import argparse
import sys
import yaml
import socket
import requests
from datetime import datetime

try:
    from onvif import ONVIFCamera
    ONVIF_AVAILABLE = True
except ImportError:
    ONVIF_AVAILABLE = False

# Color codes
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

def log(message, level="INFO"):
    """Log with color"""
    colors = {
        "INFO": Colors.BLUE,
        "SUCCESS": Colors.GREEN,
        "WARNING": Colors.YELLOW,
        "ERROR": Colors.RED
    }
    color = colors.get(level, "")
    print(f"{color}{message}{Colors.END}")

def test_basic_connectivity(host, port=80):
    """Test basic network connectivity"""
    log(f"\n=== Testing Basic Connectivity to {host}:{port} ===", "INFO")

    # Ping test
    log(f"Testing ping to {host}...", "INFO")
    import subprocess
    try:
        result = subprocess.run(
            ['ping', '-c', '3', '-W', '2', host],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            log(f"✓ Host is reachable via ping", "SUCCESS")
        else:
            log(f"✗ Host is NOT reachable via ping", "ERROR")
            return False
    except Exception as e:
        log(f"✗ Ping test failed: {e}", "ERROR")
        return False

    # Port test
    log(f"Testing TCP connection to port {port}...", "INFO")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            log(f"✓ Port {port} is open", "SUCCESS")
        else:
            log(f"✗ Port {port} is closed or filtered", "ERROR")
            return False
    except Exception as e:
        log(f"✗ Port test failed: {e}", "ERROR")
        return False

    # HTTP test
    log(f"Testing HTTP connection...", "INFO")
    try:
        response = requests.get(f"http://{host}:{port}", timeout=5)
        log(f"✓ HTTP connection successful (Status: {response.status_code})", "SUCCESS")
    except requests.exceptions.Timeout:
        log(f"⚠ HTTP connection timed out", "WARNING")
    except requests.exceptions.ConnectionError as e:
        log(f"✗ HTTP connection failed: {e}", "ERROR")
        return False
    except Exception as e:
        log(f"⚠ HTTP test error: {e}", "WARNING")

    return True

def test_onvif_connection(host, port, user, password):
    """Test ONVIF connection and capabilities"""
    if not ONVIF_AVAILABLE:
        log("✗ onvif-zeep module not installed. Install with: pip3 install onvif-zeep", "ERROR")
        return False

    log(f"\n=== Testing ONVIF Connection ===", "INFO")
    log(f"Camera: {user}@{host}:{port}", "INFO")

    try:
        # Create ONVIF camera object
        log("Creating ONVIF camera object...", "INFO")
        cam = ONVIFCamera(host, port, user, password, wsdl_dir='/opt/sai-cam/wsdl')

        # Get device information
        log("\nGetting device information...", "INFO")
        try:
            device_mgmt = cam.create_devicemgmt_service()
            device_info = device_mgmt.GetDeviceInformation()

            log("✓ Device Information Retrieved:", "SUCCESS")
            log(f"  Manufacturer: {device_info.Manufacturer}", "INFO")
            log(f"  Model: {device_info.Model}", "INFO")
            log(f"  Firmware: {device_info.FirmwareVersion}", "INFO")
            log(f"  Serial: {device_info.SerialNumber}", "INFO")
            log(f"  Hardware: {device_info.HardwareId}", "INFO")
        except Exception as e:
            log(f"✗ Failed to get device information: {e}", "ERROR")
            return False

        # Get system date/time
        log("\nGetting system date/time...", "INFO")
        try:
            system_date = device_mgmt.GetSystemDateAndTime()
            log(f"✓ Camera time: {system_date.UTCDateTime.Date.Year}-{system_date.UTCDateTime.Date.Month:02d}-{system_date.UTCDateTime.Date.Day:02d} "
                f"{system_date.UTCDateTime.Time.Hour:02d}:{system_date.UTCDateTime.Time.Minute:02d}:{system_date.UTCDateTime.Time.Second:02d}", "SUCCESS")
        except Exception as e:
            log(f"⚠ Could not get system time: {e}", "WARNING")

        # Get network interfaces
        log("\nGetting network interfaces...", "INFO")
        try:
            network_interfaces = device_mgmt.GetNetworkInterfaces()
            for interface in network_interfaces:
                log(f"✓ Interface: {interface.Info.Name if hasattr(interface, 'Info') else 'Unknown'}", "SUCCESS")
                if hasattr(interface, 'IPv4'):
                    log(f"  IPv4: {interface.IPv4.Config.Manual[0].Address if interface.IPv4.Config.Manual else 'DHCP'}", "INFO")
        except Exception as e:
            log(f"⚠ Could not get network interfaces: {e}", "WARNING")

        # Get capabilities
        log("\nGetting capabilities...", "INFO")
        try:
            capabilities = device_mgmt.GetCapabilities()
            log("✓ Camera Capabilities:", "SUCCESS")

            if hasattr(capabilities, 'Media'):
                log(f"  Media Service: {capabilities.Media.XAddr}", "INFO")

            if hasattr(capabilities, 'Imaging'):
                log(f"  Imaging Service: Available", "INFO")

            if hasattr(capabilities, 'PTZ'):
                log(f"  PTZ Service: Available", "INFO")
            else:
                log(f"  PTZ Service: Not available", "INFO")
        except Exception as e:
            log(f"⚠ Could not get capabilities: {e}", "WARNING")

        # Get media profiles
        log("\nGetting media profiles...", "INFO")
        try:
            media_service = cam.create_media_service()
            profiles = media_service.GetProfiles()

            log(f"✓ Found {len(profiles)} media profile(s):", "SUCCESS")
            for i, profile in enumerate(profiles):
                log(f"\n  Profile {i+1}: {profile.Name}", "INFO")
                if hasattr(profile, 'VideoEncoderConfiguration'):
                    config = profile.VideoEncoderConfiguration
                    log(f"    Encoding: {config.Encoding}", "INFO")
                    log(f"    Resolution: {config.Resolution.Width}x{config.Resolution.Height}", "INFO")
                    log(f"    Framerate: {config.RateControl.FrameRateLimit}", "INFO")
                    log(f"    Bitrate: {config.RateControl.BitrateLimit}", "INFO")

                # Try to get snapshot URI
                try:
                    token = profile.token
                    snapshot_uri = media_service.GetSnapshotUri({'ProfileToken': token})
                    log(f"    Snapshot URI: {snapshot_uri.Uri}", "INFO")

                    # Test snapshot download
                    log(f"    Testing snapshot download...", "INFO")
                    response = requests.get(
                        snapshot_uri.Uri,
                        auth=requests.auth.HTTPDigestAuth(user, password),
                        timeout=10
                    )
                    if response.status_code == 200:
                        size_kb = len(response.content) / 1024
                        log(f"    ✓ Snapshot downloaded successfully ({size_kb:.1f} KB)", "SUCCESS")
                    else:
                        log(f"    ✗ Snapshot download failed (HTTP {response.status_code})", "ERROR")
                except Exception as e:
                    log(f"    ⚠ Could not test snapshot: {e}", "WARNING")

        except Exception as e:
            log(f"✗ Failed to get media profiles: {e}", "ERROR")
            return False

        # Get stream URIs
        log("\nGetting stream URIs...", "INFO")
        try:
            for profile in profiles[:1]:  # Just test first profile
                token = profile.token

                # Get RTSP URI
                try:
                    stream_setup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
                    stream_uri = media_service.GetStreamUri({'StreamSetup': stream_setup, 'ProfileToken': token})
                    log(f"✓ RTSP Stream URI: {stream_uri.Uri}", "SUCCESS")
                except Exception as e:
                    log(f"⚠ Could not get stream URI: {e}", "WARNING")

        except Exception as e:
            log(f"⚠ Error getting stream URIs: {e}", "WARNING")

        log("\n✓ ONVIF connection test PASSED", "SUCCESS")
        return True

    except Exception as e:
        log(f"\n✗ ONVIF connection test FAILED: {e}", "ERROR")
        import traceback
        if '--verbose' in sys.argv:
            log(traceback.format_exc(), "ERROR")
        return False

def test_cameras_from_config(config_path):
    """Test all ONVIF cameras from config file"""
    log(f"\n=== Testing Cameras from Config: {config_path} ===", "INFO")

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        log(f"✗ Failed to load config: {e}", "ERROR")
        return False

    if 'cameras' not in config:
        log("✗ No cameras found in config", "ERROR")
        return False

    onvif_cameras = [c for c in config['cameras'] if c.get('type') == 'onvif']

    if not onvif_cameras:
        log("✗ No ONVIF cameras found in config", "ERROR")
        return False

    log(f"Found {len(onvif_cameras)} ONVIF camera(s) in config", "INFO")

    all_passed = True
    for cam in onvif_cameras:
        cam_id = cam.get('id', 'unknown')
        log(f"\n{'='*60}", "INFO")
        log(f"Testing Camera: {cam_id}", "INFO")
        log(f"{'='*60}", "INFO")

        host = cam.get('address')
        port = cam.get('port', 80)
        user = cam.get('username')
        password = cam.get('password')

        if not all([host, user, password]):
            log(f"✗ Missing credentials for camera {cam_id}", "ERROR")
            all_passed = False
            continue

        # Test basic connectivity
        if not test_basic_connectivity(host, port):
            log(f"✗ Basic connectivity failed for {cam_id}", "ERROR")
            all_passed = False
            continue

        # Test ONVIF
        if not test_onvif_connection(host, port, user, password):
            log(f"✗ ONVIF test failed for {cam_id}", "ERROR")
            all_passed = False
        else:
            log(f"✓ Camera {cam_id} test PASSED", "SUCCESS")

    return all_passed

def main():
    parser = argparse.ArgumentParser(description='SAI-Cam ONVIF Camera Diagnostic Tool')
    parser.add_argument('--host', help='Camera IP address')
    parser.add_argument('--port', type=int, default=80, help='Camera port (default: 80)')
    parser.add_argument('--user', help='Camera username')
    parser.add_argument('--password', help='Camera password')
    parser.add_argument('--config', help='Test all cameras from config file')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    log(f"{Colors.BOLD}=== SAI-Cam ONVIF Diagnostics ==={Colors.END}", "INFO")
    log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "INFO")

    if args.config:
        # Test cameras from config
        success = test_cameras_from_config(args.config)
    elif args.host and args.user and args.password:
        # Test single camera
        if test_basic_connectivity(args.host, args.port):
            success = test_onvif_connection(args.host, args.port, args.user, args.password)
        else:
            success = False
    else:
        log("✗ Must provide either --config or (--host, --user, --password)", "ERROR")
        parser.print_help()
        sys.exit(1)

    log(f"\n{'='*60}", "INFO")
    if success:
        log(f"{Colors.GREEN}{Colors.BOLD}✓ All diagnostics PASSED{Colors.END}", "SUCCESS")
        sys.exit(0)
    else:
        log(f"{Colors.RED}{Colors.BOLD}✗ Some diagnostics FAILED{Colors.END}", "ERROR")
        sys.exit(1)

if __name__ == '__main__':
    main()
