#!/usr/bin/env python3
"""
SAI-Cam Status Portal
Lightweight Flask API providing node health and status information
"""

import os
import sys
import json
import yaml
import psutil
import subprocess
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, Response, request
from threading import Thread
import time
import logging

# Add parent directory to path for imports
current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

VERSION = "0.1.0"

app = Flask(__name__, static_folder='portal', static_url_path='')

# Global state
config = {}
logger = None
start_time = time.time()

def load_config(config_path='/etc/sai-cam/config.yaml'):
    """Load configuration from YAML file"""
    global config
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Warning: Could not load config: {e}")
        config = {'device': {'id': 'unknown', 'location': 'unknown'}}
    return config

def setup_logging():
    """Setup logging"""
    global logger
    logger = logging.getLogger('SAICamPortal')
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(name)s] [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def detect_features():
    """Auto-detect available features on this node"""
    features = {
        'wifi_ap': is_wifi_ap_active(),
        'cameras': len(config.get('cameras', [])) > 0,
        'storage': os.path.exists('/opt/sai-cam/storage'),
        'monitoring': 'monitoring' in config,
        'onvif': any(c.get('type') == 'onvif' for c in config.get('cameras', [])),
        'rtsp': any(c.get('type') == 'rtsp' for c in config.get('cameras', [])),
        'usb_camera': any(c.get('type') == 'usb' for c in config.get('cameras', [])),
    }
    return features

def is_wifi_ap_active():
    """Check if wlan0 is in AP mode"""
    try:
        result = subprocess.run(['iw', 'dev', 'wlan0', 'info'],
                              capture_output=True, text=True, timeout=2)
        return 'type AP' in result.stdout
    except:
        return False

def get_wifi_ap_info():
    """Get WiFi AP information if active"""
    if not is_wifi_ap_active():
        return None

    try:
        # Get SSID from hostapd config or generate from device ID
        ssid = f"SAI-Node-{config.get('device', {}).get('id', 'unknown')}"

        # Get connected clients count
        try:
            result = subprocess.run(['iw', 'dev', 'wlan0', 'station', 'dump'],
                                  capture_output=True, text=True, timeout=2)
            client_count = result.stdout.count('Station ')
        except:
            client_count = 0

        # Get channel
        try:
            result = subprocess.run(['iw', 'dev', 'wlan0', 'info'],
                                  capture_output=True, text=True, timeout=2)
            for line in result.stdout.split('\n'):
                if 'channel' in line:
                    channel = line.split('channel')[-1].strip().split()[0]
                    break
            else:
                channel = 'N/A'
        except:
            channel = 'N/A'

        return {
            'ssid': ssid,
            'connected_clients': client_count,
            'channel': channel,
            'interface': 'wlan0'
        }
    except Exception as e:
        logger.error(f"Error getting WiFi AP info: {e}")
        return None

def get_system_info():
    """Get system resource information"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # Try to get temperature (Raspberry Pi specific)
        temperature = None
        try:
            if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temperature = int(f.read().strip()) / 1000.0
        except:
            pass

        return {
            'cpu_percent': round(cpu_percent, 1),
            'memory_percent': round(memory.percent, 1),
            'memory_used_mb': round(memory.used / 1024 / 1024, 1),
            'memory_total_mb': round(memory.total / 1024 / 1024, 1),
            'disk_percent': round(disk.percent, 1),
            'disk_used_gb': round(disk.used / 1024 / 1024 / 1024, 2),
            'disk_total_gb': round(disk.total / 1024 / 1024 / 1024, 2),
            'temperature': round(temperature, 1) if temperature else None,
            'uptime': int(time.time() - start_time)
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {}

def get_camera_status():
    """Get status of all configured cameras"""
    cameras = []
    log_path = Path('/var/log/sai-cam/camera_service.log')

    # Parse recent logs to get camera status
    recent_logs = []
    if log_path.exists():
        try:
            with open(log_path, 'r') as f:
                recent_logs = f.readlines()[-200:]  # Last 200 lines
        except:
            pass

    for cam_config in config.get('cameras', []):
        cam_id = cam_config['id']
        cam_type = cam_config.get('type', 'unknown')

        # Check if camera appears online in recent logs
        online = False
        error = None
        last_capture = None

        for line in reversed(recent_logs):
            if cam_id in line:
                if 'Captured image' in line:
                    online = True
                    # Extract timestamp from log line
                    try:
                        timestamp_str = line.split('[')[0].strip()
                        last_capture = timestamp_str
                    except:
                        last_capture = 'Recently'
                    break
                elif 'ERROR' in line and 'Failed to initialize' in line:
                    error = 'Initialization failed'
                    break
                elif 'No route to host' in line:
                    error = 'No route to host'
                    break

        # Get storage location for thumbnails
        latest_image = None
        storage_path = Path('/opt/sai-cam/storage')
        if storage_path.exists():
            cam_images = list(storage_path.glob(f'{cam_id}_*.jpg'))
            if cam_images:
                latest = max(cam_images, key=lambda p: p.stat().st_mtime)
                latest_image = latest.name

        cameras.append({
            'id': cam_id,
            'type': cam_type,
            'address': cam_config.get('address', 'N/A'),
            'position': cam_config.get('position', ''),
            'online': online,
            'error': error,
            'last_capture': last_capture,
            'latest_image': latest_image,
            'capture_interval': cam_config.get('capture_interval', 300)
        })

    return cameras

def get_storage_info():
    """Get storage usage information"""
    storage_path = Path('/opt/sai-cam/storage')
    if not storage_path.exists():
        return None

    try:
        # Count images
        images = list(storage_path.glob('*.jpg'))
        uploaded_path = storage_path / 'uploaded'
        uploaded_images = list(uploaded_path.glob('*.jpg')) if uploaded_path.exists() else []

        # Calculate sizes
        total_size = sum(f.stat().st_size for f in images) / 1024 / 1024  # MB
        uploaded_size = sum(f.stat().st_size for f in uploaded_images) / 1024 / 1024

        return {
            'total_images': len(images),
            'uploaded_images': len(uploaded_images),
            'pending_images': len(images) - len(uploaded_images),
            'total_size_mb': round(total_size, 2),
            'uploaded_size_mb': round(uploaded_size, 2),
            'max_size_gb': config.get('storage', {}).get('max_size_gb', 0)
        }
    except Exception as e:
        logger.error(f"Error getting storage info: {e}")
        return None

def get_network_info():
    """Get network interface information"""
    try:
        interfaces = {}

        # Get all network interfaces
        for iface_name, iface_addrs in psutil.net_if_addrs().items():
            if iface_name in ['lo', 'docker0']:
                continue
            # Skip docker bridge networks
            if iface_name.startswith('br-') or iface_name.startswith('veth'):
                continue

            ipv4 = None
            for addr in iface_addrs:
                if addr.family == 2:  # AF_INET (IPv4)
                    ipv4 = addr.address
                    break

            if ipv4:
                interfaces[iface_name] = {
                    'ip': ipv4,
                    'type': 'wireless' if iface_name.startswith('wl') else 'ethernet'
                }

        # Check upstream connectivity
        upstream_online = False
        try:
            result = subprocess.run(['ping', '-c', '1', '-W', '2', '8.8.8.8'],
                                  capture_output=True, timeout=3)
            upstream_online = result.returncode == 0
        except:
            pass

        # Get network mode from config
        network_mode = config.get('network', {}).get('mode', 'ethernet')

        # Determine WAN interface based on mode
        if network_mode == 'wifi-client':
            wan_interface = config.get('network', {}).get('wifi_client', {}).get('wifi_iface', 'wlan0')
        else:
            wan_interface = config.get('network', {}).get('interface', 'eth0')

        return {
            'interfaces': interfaces,
            'upstream_online': upstream_online,
            'mode': network_mode,
            'wan_interface': wan_interface
        }
    except Exception as e:
        logger.error(f"Error getting network info: {e}")
        return {}

def get_recent_logs(lines=50):
    """Get recent log entries"""
    log_path = Path('/var/log/sai-cam/camera_service.log')
    if not log_path.exists():
        return []

    try:
        with open(log_path, 'r') as f:
            all_lines = f.readlines()
            recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return [line.strip() for line in recent]
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        return []

# Routes

@app.route('/')
def index():
    """Serve the main dashboard page"""
    return send_from_directory('portal', 'index.html')

@app.route('/api/status')
def api_status():
    """Get full status of the node"""
    features = detect_features()

    data = {
        'node': {
            'id': config.get('device', {}).get('id', 'unknown'),
            'location': config.get('device', {}).get('location', 'unknown'),
            'description': config.get('device', {}).get('description', ''),
            'version': VERSION
        },
        'features': features,
        'data': {
            'system': get_system_info(),
            'cameras': get_camera_status() if features['cameras'] else [],
            'storage': get_storage_info() if features['storage'] else None,
            'network': get_network_info(),
            'wifi_ap': get_wifi_ap_info() if features['wifi_ap'] else None
        },
        'timestamp': datetime.now().isoformat()
    }

    return jsonify(data)

@app.route('/api/status/cameras')
def api_cameras():
    """Get camera-specific status"""
    return jsonify(get_camera_status())

@app.route('/api/status/system')
def api_system():
    """Get system metrics"""
    return jsonify(get_system_info())

@app.route('/api/status/network')
def api_network():
    """Get network information"""
    return jsonify(get_network_info())

@app.route('/api/logs')
def api_logs():
    """Get recent log entries"""
    lines = int(request.args.get('lines', 50))
    return jsonify({'logs': get_recent_logs(lines)})

@app.route('/api/logs/stream')
def api_logs_stream():
    """Stream logs using Server-Sent Events"""
    def generate():
        log_path = Path('/var/log/sai-cam/camera_service.log')
        last_size = log_path.stat().st_size if log_path.exists() else 0

        while True:
            try:
                if log_path.exists():
                    current_size = log_path.stat().st_size
                    if current_size > last_size:
                        with open(log_path, 'r') as f:
                            f.seek(last_size)
                            new_lines = f.readlines()
                            for line in new_lines:
                                yield f"data: {json.dumps({'log': line.strip()})}\n\n"
                        last_size = current_size
                time.sleep(1)
            except Exception as e:
                logger.error(f"Log streaming error: {e}")
                time.sleep(5)

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/images/<camera_id>/latest')
def api_latest_image(camera_id):
    """Get latest image from a specific camera"""
    storage_path = Path('/opt/sai-cam/storage')
    if not storage_path.exists():
        return jsonify({'error': 'Storage not found'}), 404

    # Find latest image for this camera
    cam_images = list(storage_path.glob(f'{camera_id}_*.jpg'))
    if not cam_images:
        return jsonify({'error': 'No images found'}), 404

    latest = max(cam_images, key=lambda p: p.stat().st_mtime)
    return send_from_directory(storage_path, latest.name)

@app.route('/api/config')
def api_config():
    """Get sanitized configuration"""
    sanitized = config.copy()

    # Remove sensitive information
    if 'cameras' in sanitized:
        for cam in sanitized['cameras']:
            if 'password' in cam:
                cam['password'] = '***'

    if 'server' in sanitized:
        if 'auth_token' in sanitized['server']:
            sanitized['server']['auth_token'] = '***'

    return jsonify(sanitized)

@app.route('/api/wifi_ap/enable', methods=['POST'])
def api_wifi_enable():
    """Enable WiFi Access Point"""
    try:
        logger.info("Attempting to enable WiFi AP (sai-cam-ap)")
        result = subprocess.run(
            ['sudo', 'nmcli', 'con', 'up', 'sai-cam-ap'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            logger.info("WiFi AP enabled successfully")
            return jsonify({'success': True, 'message': 'WiFi AP enabled successfully'})
        else:
            error_msg = result.stderr.strip() or result.stdout.strip()
            logger.error(f"Failed to enable WiFi AP: {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), 500

    except subprocess.TimeoutExpired:
        logger.error("Timeout while enabling WiFi AP")
        return jsonify({'success': False, 'error': 'Operation timed out'}), 500
    except Exception as e:
        logger.error(f"Error enabling WiFi AP: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/wifi_ap/disable', methods=['POST'])
def api_wifi_disable():
    """Disable WiFi Access Point"""
    try:
        logger.info("Attempting to disable WiFi AP (sai-cam-ap)")
        result = subprocess.run(
            ['sudo', 'nmcli', 'con', 'down', 'sai-cam-ap'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            logger.info("WiFi AP disabled successfully")
            return jsonify({'success': True, 'message': 'WiFi AP disabled successfully'})
        else:
            error_msg = result.stderr.strip() or result.stdout.strip()
            logger.error(f"Failed to disable WiFi AP: {error_msg}")
            return jsonify({'success': False, 'error': error_msg}), 500

    except subprocess.TimeoutExpired:
        logger.error("Timeout while disabling WiFi AP")
        return jsonify({'success': False, 'error': 'Operation timed out'}), 500
    except Exception as e:
        logger.error(f"Error disabling WiFi AP: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description='SAI-Cam Status Portal')
    parser.add_argument('--config', type=str, default='/etc/sai-cam/config.yaml',
                       help='Path to config file')
    parser.add_argument('--port', type=int, default=80,
                       help='Port to listen on (default: 80)')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')

    args = parser.parse_args()

    setup_logging()
    load_config(args.config)

    logger.info(f"Starting SAI-Cam Status Portal v{VERSION}")
    logger.info(f"Node: {config.get('device', {}).get('id', 'unknown')}")
    logger.info(f"Listening on {args.host}:{args.port}")

    # Run Flask app
    app.run(host=args.host, port=args.port, debug=False, threaded=True)

if __name__ == '__main__':
    main()
