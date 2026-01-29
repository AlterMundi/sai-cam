#!/usr/bin/env python3
"""
SAI-Cam Status Portal
Lightweight Flask API providing node health and status information
"""

import copy
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

import psutil
import yaml
from flask import Flask, jsonify, send_from_directory, Response, request, stream_with_context

# Add parent directory to path for imports
current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import version from camera_service to keep in sync
try:
    from camera_service import VERSION
except ImportError:
    VERSION = "0.2.4"  # Fallback if import fails

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

    # Initialize CPU percent measurement (first call returns 0, primes the counter)
    psutil.cpu_percent(interval=None)

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
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
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
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
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
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
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
        # Use non-blocking cpu_percent (returns value since last call)
        # First call returns 0.0, subsequent calls return meaningful values
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # Try to get temperature (Raspberry Pi specific)
        temperature = None
        try:
            if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temperature = int(f.read().strip()) / 1000.0
        except (IOError, ValueError, OSError):
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
            'system_uptime': int(time.time() - psutil.boot_time()),
            'service_uptime': int(time.time() - start_time)
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {}

def get_camera_status():
    """Get status of all configured cameras using health socket"""
    cameras = []

    # Get real-time status from health socket
    health_data = query_health_socket()
    health_cameras = health_data.get('cameras', {}) if health_data else {}
    failed_cameras = health_data.get('failed_cameras', {}) if health_data else {}

    for cam_config in config.get('cameras', []):
        cam_id = cam_config['id']
        cam_type = cam_config.get('type', 'unknown')

        # Check camera status from health socket
        cam_health = health_cameras.get(cam_id, {})
        is_failed = cam_id in failed_cameras

        # Camera is online if state is healthy and thread is alive
        online = (cam_health.get('state') == 'healthy' and
                  cam_health.get('thread_alive', False))

        # Determine error message
        error = None
        if is_failed:
            attempts = failed_cameras[cam_id].get('attempts', 0)
            error = f'Failed to initialize (attempt {attempts})'
        elif cam_health.get('state') == 'failing':
            failures = cam_health.get('consecutive_failures', 0)
            error = f'Failing ({failures} consecutive errors)'
        elif cam_health.get('state') == 'offline':
            error = 'Offline'

        # Get last capture time from health data
        last_capture = None
        if cam_health.get('last_success_age') is not None:
            age = cam_health['last_success_age']
            if age < 60:
                last_capture = f'{int(age)}s ago'
            elif age < 3600:
                last_capture = f'{int(age/60)}m ago'
            else:
                last_capture = f'{int(age/3600)}h ago'

        # Get storage location for thumbnails (check both pending and uploaded)
        latest_image = None
        storage_path = Path('/opt/sai-cam/storage')
        if storage_path.exists():
            cam_images = list(storage_path.glob(f'{cam_id}_*.jpg'))
            uploaded_path = storage_path / 'uploaded'
            if uploaded_path.exists():
                cam_images.extend(uploaded_path.glob(f'{cam_id}_*.jpg'))
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
            'max_size_gb': config.get('storage', {}).get('max_size_gb', 0),
            'cleanup_threshold_gb': config.get('storage', {}).get('cleanup_threshold_gb', 0)
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

            ipv4_addrs = []
            for addr in iface_addrs:
                if addr.family == 2:  # AF_INET (IPv4)
                    ipv4_addrs.append(addr.address)

            if ipv4_addrs:
                interfaces[iface_name] = {
                    'ip': ipv4_addrs[0],
                    'ips': ipv4_addrs,
                    'type': 'wireless' if iface_name.startswith('wl') else 'ethernet'
                }

        # Check upstream connectivity
        upstream_online = False
        try:
            result = subprocess.run(['ping', '-c', '1', '-W', '2', '8.8.8.8'],
                                  capture_output=True, timeout=3)
            upstream_online = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # Detect WAN interface from default route (actual internet connection)
        wan_interface = None
        try:
            result = subprocess.run(['ip', 'route', 'show', 'default'],
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout:
                # Parse: "default via 192.168.0.1 dev wlan0 ..."
                parts = result.stdout.split()
                if 'dev' in parts:
                    wan_interface = parts[parts.index('dev') + 1]
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
            pass

        # Fallback to config if route detection fails
        if not wan_interface:
            wan_interface = config.get('network', {}).get('interface', 'eth0')

        # Determine mode from actual WAN interface type
        if wan_interface and wan_interface.startswith('wl'):
            network_mode = 'wifi'
        else:
            network_mode = 'ethernet'

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
    """Get recent log entries using efficient tail-like reading"""
    log_path = Path('/var/log/sai-cam/camera_service.log')
    if not log_path.exists():
        return []

    try:
        # Efficient tail: read from end of file
        with open(log_path, 'rb') as f:
            # Seek to end
            f.seek(0, 2)
            file_size = f.tell()

            if file_size == 0:
                return []

            # Read chunks from end until we have enough lines
            chunk_size = 8192
            found_lines = []
            position = file_size

            while position > 0 and len(found_lines) < lines + 1:
                read_size = min(chunk_size, position)
                position -= read_size
                f.seek(position)
                chunk = f.read(read_size).decode('utf-8', errors='replace')

                # Split and prepend to found lines
                chunk_lines = chunk.split('\n')
                if found_lines:
                    # Merge partial line from previous chunk
                    chunk_lines[-1] += found_lines[0]
                    found_lines = chunk_lines + found_lines[1:]
                else:
                    found_lines = chunk_lines

            # Return last N non-empty lines
            result = [line.strip() for line in found_lines if line.strip()]
            return result[-lines:]

    except (IOError, OSError, UnicodeDecodeError) as e:
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
    try:
        lines = int(request.args.get('lines', 50))
        # Bounds check to prevent memory exhaustion
        lines = max(1, min(lines, 1000))
    except (ValueError, TypeError):
        lines = 50
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


@app.route('/api/events')
def api_events():
    """Unified SSE endpoint for dashboard real-time updates.

    Events emitted:
    - health: Camera/system status (every 5s or on change)
    - log: New log lines (real-time)
    - status: Network/storage updates (every 30s)
    """
    def generate():
        log_path = Path('/var/log/sai-cam/camera_service.log')
        last_log_size = log_path.stat().st_size if log_path.exists() else 0
        last_health_hash = None
        last_status_hash = None
        last_health_time = 0
        last_status_time = 0

        # Send initial health immediately
        try:
            health = query_health_socket() or {}
            # Add system metrics from psutil
            health['system'] = get_system_info()
            yield f"event: health\ndata: {json.dumps(health)}\n\n"
            last_health_hash = hash(json.dumps(health, sort_keys=True))
            last_health_time = time.time()
        except Exception as e:
            logger.debug(f"Initial health fetch failed: {e}")

        while True:
            try:
                now = time.time()

                # Health updates (every 5s, only if changed)
                if now - last_health_time >= 5:
                    health = query_health_socket() or {}
                    # Add system metrics from psutil
                    health['system'] = get_system_info()
                    health_hash = hash(json.dumps(health, sort_keys=True))
                    if health_hash != last_health_hash:
                        yield f"event: health\ndata: {json.dumps(health)}\n\n"
                        last_health_hash = health_hash
                    last_health_time = now

                # Status updates - network/storage (every 30s)
                if now - last_status_time >= 30:
                    try:
                        status_data = {
                            'network': get_network_info(),
                            'storage': get_storage_info(),
                        }
                        status_hash = hash(json.dumps(status_data, sort_keys=True))
                        if status_hash != last_status_hash:
                            yield f"event: status\ndata: {json.dumps(status_data)}\n\n"
                            last_status_hash = status_hash
                    except Exception as e:
                        logger.debug(f"Status fetch failed: {e}")
                    last_status_time = now

                # Log updates (real-time)
                if log_path.exists():
                    current_size = log_path.stat().st_size
                    if current_size > last_log_size:
                        # New log content
                        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                            f.seek(last_log_size)
                            for line in f:
                                line = line.strip()
                                if line:
                                    yield f"event: log\ndata: {json.dumps({'line': line})}\n\n"
                        last_log_size = current_size
                    elif current_size < last_log_size:
                        # Log rotated - reset position
                        last_log_size = 0

                time.sleep(1)

            except GeneratorExit:
                # Client disconnected
                break
            except Exception as e:
                logger.error(f"SSE event stream error: {e}")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(5)

    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
    response.headers['Connection'] = 'keep-alive'
    return response


@app.route('/api/images/<camera_id>/latest')
def api_latest_image(camera_id):
    """Get latest image from a specific camera"""
    storage_path = Path('/opt/sai-cam/storage')
    if not storage_path.exists():
        return jsonify({'error': 'Storage not found'}), 404

    # Find latest image for this camera (check both pending and uploaded)
    cam_images = list(storage_path.glob(f'{camera_id}_*.jpg'))
    uploaded_path = storage_path / 'uploaded'
    if uploaded_path.exists():
        cam_images.extend(uploaded_path.glob(f'{camera_id}_*.jpg'))
    if not cam_images:
        return jsonify({'error': 'No images found'}), 404

    latest = max(cam_images, key=lambda p: p.stat().st_mtime)
    return send_from_directory(latest.parent, latest.name)

@app.route('/api/config')
def api_config():
    """Get sanitized configuration"""
    sanitized = copy.deepcopy(config)

    # Remove sensitive information
    if 'cameras' in sanitized:
        for cam in sanitized['cameras']:
            if 'password' in cam:
                cam['password'] = '***'
            # Also redact passwords in RTSP URLs
            if 'rtsp_url' in cam:
                cam['rtsp_url'] = re.sub(r'(://[^:]+:)[^@]+(@)', r'\1***\2', cam['rtsp_url'])

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


# Health API via Unix socket (direct access to camera_service state)

def query_health_socket():
    """Query camera service health via Unix domain socket"""
    socket_path = '/run/sai-cam/health.sock'

    if not os.path.exists(socket_path):
        return None

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.connect(socket_path)

        data = b''
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk

        client.close()
        return json.loads(data.decode('utf-8'))
    except Exception as e:
        logger.error(f"Health socket query failed: {e}")
        return None


def send_camera_command(action, camera_id=None):
    """Send command to camera service via health socket"""
    socket_path = '/run/sai-cam/health.sock'
    if not os.path.exists(socket_path):
        return None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(10.0)  # longer timeout for restart ops
        client.connect(socket_path)
        cmd = json.dumps({'action': action, 'camera_id': camera_id})
        client.sendall(cmd.encode('utf-8'))
        data = b''
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
        client.close()
        return json.loads(data.decode('utf-8'))
    except Exception as e:
        return {'error': str(e)}


@app.route('/api/cameras/<camera_id>/capture', methods=['POST'])
def api_force_capture(camera_id):
    """Trigger immediate capture on a specific camera"""
    result = send_camera_command('force_capture', camera_id)
    if result is None:
        return jsonify({'error': 'Camera service not available'}), 503
    return jsonify(result)


@app.route('/api/cameras/<camera_id>/restart', methods=['POST'])
def api_restart_camera(camera_id):
    """Restart a specific camera"""
    result = send_camera_command('restart_camera', camera_id)
    if result is None:
        return jsonify({'error': 'Camera service not available'}), 503
    return jsonify(result)


@app.route('/api/cameras/<camera_id>/position', methods=['POST'])
def api_update_position(camera_id):
    """Update camera position in config file"""
    position = request.json.get('position', '')
    config_path = app.config.get('CONFIG_PATH', '/etc/sai-cam/config.yaml')
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        found = False
        for cam in cfg.get('cameras', []):
            if cam['id'] == camera_id:
                cam['position'] = position
                found = True
                break
        if not found:
            return jsonify({'error': 'Camera not found in config'}), 404
        with open(config_path, 'w') as f:
            yaml.dump(cfg, f, default_flow_style=False)
        # Update in-memory config too
        for cam in config.get('cameras', []):
            if cam['id'] == camera_id:
                cam['position'] = position
        return jsonify({'ok': True})
    except PermissionError:
        return jsonify({'error': 'Permission denied writing config'}), 403
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/health')
def api_health():
    """Get direct health metrics from camera service (not log-based)"""
    health = query_health_socket()

    if health is None:
        return jsonify({
            'error': 'Camera service not available',
            'message': 'Camera service may not be running or socket not accessible',
            'socket_path': '/run/sai-cam/health.sock'
        }), 503

    return jsonify(health)


@app.route('/api/service/status')
def api_service_status():
    """Get sai-cam service status from systemd"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', 'sai-cam'],
            capture_output=True, text=True, timeout=5
        )
        is_active = result.stdout.strip() == 'active'

        # Get more details if active
        uptime = None
        if is_active:
            result2 = subprocess.run(
                ['systemctl', 'show', 'sai-cam', '--property=ActiveEnterTimestamp'],
                capture_output=True, text=True, timeout=5
            )
            if result2.returncode == 0:
                # Parse: ActiveEnterTimestamp=Wed 2026-01-14 21:51:30 -03
                timestamp_str = result2.stdout.strip().split('=', 1)[-1]
                if timestamp_str:
                    try:
                        from datetime import datetime
                        # Parse the timestamp
                        start_time = datetime.strptime(timestamp_str.rsplit(' ', 1)[0], '%a %Y-%m-%d %H:%M:%S')
                        uptime = int((datetime.now() - start_time).total_seconds())
                    except (ValueError, IndexError):
                        pass

        return jsonify({
            'service': 'sai-cam',
            'active': is_active,
            'status': result.stdout.strip(),
            'uptime_seconds': uptime
        })
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return jsonify({
            'service': 'sai-cam',
            'active': False,
            'status': 'unknown',
            'error': str(e)
        })


@app.route('/api/health/cameras')
def api_health_cameras():
    """Get camera-specific health from direct service state"""
    health = query_health_socket()

    if health is None or 'cameras' not in health:
        return jsonify({'error': 'Camera health not available'}), 503

    return jsonify({
        'cameras': health['cameras'],
        'failed_cameras': health.get('failed_cameras', {}),
        'timestamp': health.get('timestamp')
    })


@app.route('/api/health/threads')
def api_health_threads():
    """Get thread health information from camera service"""
    health = query_health_socket()

    if health is None or 'threads' not in health:
        return jsonify({'error': 'Thread health not available'}), 503

    return jsonify({
        'threads': health['threads'],
        'timestamp': health.get('timestamp')
    })


@app.route('/api/health/system')
def api_health_system():
    """Get system health from camera service perspective"""
    health = query_health_socket()

    if health is None:
        return jsonify({'error': 'System health not available'}), 503

    return jsonify({
        'system': health.get('system', {}),
        'health_monitor': health.get('health_monitor', {}),
        'uptime_seconds': health.get('uptime_seconds'),
        'version': health.get('version'),
        'timestamp': health.get('timestamp')
    })


@app.route('/api/log_level')
def api_get_log_level():
    """Get current log level from config"""
    try:
        current_level = config.get('logging', {}).get('level', 'WARNING')
        return jsonify({'level': current_level})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/log_level', methods=['POST'])
def api_set_log_level():
    """Set log level and send SIGHUP to camera service"""
    data = request.get_json() or {}
    new_level = data.get('level', '').upper()

    if new_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
        return jsonify({'error': 'Invalid level. Use DEBUG, INFO, WARNING, or ERROR'}), 400

    try:
        # Update config file
        config_path = Path('/etc/sai-cam/config.yaml')
        if not config_path.exists():
            return jsonify({'error': 'Config file not found'}), 500

        # Read current config
        with open(config_path, 'r') as f:
            config_content = f.read()

        # Replace log level using sed-like pattern
        new_content = re.sub(
            r"(logging:\s*\n\s*level:\s*)['\"]?\w+['\"]?",
            f"\\1'{new_level}'",
            config_content
        )

        # Write updated config
        with open(config_path, 'w') as f:
            f.write(new_content)

        # Reload our local config
        load_config(str(config_path))

        # Send SIGHUP to camera service
        result = subprocess.run(
            ['pgrep', '-f', 'camera_service.py'],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = int(result.stdout.strip().split()[0])
            os.kill(pid, signal.SIGHUP)
            logger.info(f"Sent SIGHUP to camera_service (PID {pid}) for log level change to {new_level}")

        return jsonify({'success': True, 'level': new_level})

    except PermissionError:
        return jsonify({'error': 'Permission denied. Config file not writable.'}), 403
    except Exception as e:
        logger.error(f"Failed to set log level: {e}")
        return jsonify({'error': str(e)}), 500


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
    app.config['CONFIG_PATH'] = args.config

    logger.info(f"Starting SAI-Cam Status Portal v{VERSION}")
    logger.info(f"Node: {config.get('device', {}).get('id', 'unknown')}")
    logger.info(f"Listening on {args.host}:{args.port}")

    # Run Flask app
    app.run(host=args.host, port=args.port, debug=False, threaded=True)

if __name__ == '__main__':
    main()
