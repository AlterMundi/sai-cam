# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SAI-Cam is an edge node component of the SAI (Sistema de Alerta de Incendios) wildfire detection system. It's a Python-based camera service that captures images from multiple RTSP/ONVIF/USB cameras and uploads them to a central server for AI-powered fire detection analysis.

## Architecture

### Multi-Camera Threading Model

- Each camera runs in its own thread with independent capture intervals
- `CameraInstance` manages individual camera lifecycle (capture, reconnect, validation)
- `CameraService` orchestrates multiple camera threads and coordinates shutdown
- `StorageManager` handles local storage cleanup based on disk usage thresholds
- `HealthMonitor` tracks system resources (CPU, memory, disk) with configurable limits

### Camera Abstraction Layer

The codebase uses a factory pattern for camera instantiation:

- **[src/cameras/base_camera.py](src/cameras/base_camera.py)**: Abstract `BaseCamera` class defining common interface
- **[src/cameras/camera_factory.py](src/cameras/camera_factory.py)**: Factory functions `create_camera()` and `create_camera_from_config()`
- **Implementations**: `USBCamera`, `RTSPCamera`, `ONVIFCameraImpl` in [src/cameras/](src/cameras/)

All cameras implement: `setup()`, `capture_frame()`, `reconnect()`, `cleanup()`, `validate_frame()`

### Key Technical Details

- **RTSP streams**: Use FFMPEG backend with TCP transport and H.265 hardware acceleration (VAAPI)
- **Frame validation**: Accepts frames in low-light conditions but warns on brightness extremes (avg < 5 or > 250)
- **Reconnection**: Configurable retry attempts with exponential backoff
- **Systemd integration**: Full watchdog support for automatic restart on hangs

## Common Development Commands

### Installation and Setup

```bash
# Full installation (requires sudo, used for deployment)
sudo ./scripts/install.sh

# Configuration-only update (updates /etc/sai-cam/config.yaml)
sudo ./scripts/install.sh --config-only

# Install Python dependencies
pip3 install -r requirements.txt

# Or minimal dependencies (no ONVIF support)
pip3 install -r requirements-minimal.txt
```

### Testing and Development

```bash
# Run service locally without uploading to server
python3 src/camera_service.py --config config/config.yaml --local-save --log-level DEBUG

# Test camera initialization only (dry run)
python3 src/camera_service.py --config config/config.yaml --dry-run

# Run architecture demo (no hardware needed)
python3 scripts/architecture-demo.py

# Test ONVIF camera connectivity
python3 scripts/onvif-test.py

# Test specific camera types with generated config
python3 scripts/camera-test.py --generate-config
python3 scripts/camera-test.py --config camera-test-config.yaml --camera-type onvif --save-images
```

### Service Management (Deployed Systems)

```bash
# Check service status
sudo systemctl status sai-cam

# View live logs
sudo journalctl -u sai-cam -f

# Restart service (triggers config reload)
sudo systemctl restart sai-cam

# Stop service
sudo systemctl stop sai-cam
```

## Configuration

The service uses YAML configuration at `/etc/sai-cam/config.yaml` (or specified via `--config`). Key sections:

- **cameras**: Array of camera configs with `id`, `type` (usb/rtsp/onvif), connection details, `capture_interval`, and `position`
- **network**: Optional static IP configuration for edge deployment (NetworkManager integration)
- **storage**: Paths (`base_path`), retention policies, and cleanup thresholds (`max_size_gb`)
- **server**: Upload endpoint, SSL verification, authentication token
- **monitoring**: Resource limits (CPU %, memory %, disk %) and health check intervals
- **device**: Node identification (`id`, `location`, `description`)
- **advanced**: Polling intervals, reconnection attempts, FFMPEG options

See [config/config.yaml](config/config.yaml) for complete example with 6 cameras (ONVIF, RTSP, USB).

## File Locations (Deployed Systems)

- **Installation**: `/opt/sai-cam/` (service code copied here by install.sh)
- **Configuration**: `/etc/sai-cam/config.yaml`
- **Logs**: `/var/log/sai-cam/camera_service.log`
- **Local storage**: `/opt/sai-cam/storage/` (images before upload)
- **Service**: `/etc/systemd/system/sai-cam.service`

## Deployment Considerations

**CRITICAL**: The [scripts/install.sh](scripts/install.sh) script is the primary deployment mechanism. When proposing changes:

1. Test changes locally first with `--config` and `--local-save` flags
2. Changes to [src/](src/) are deployed by copying to `/opt/sai-cam/`
3. Config changes require `sudo ./scripts/install.sh --config-only` or full reinstall
4. Service restarts automatically pick up code changes if properly deployed

The install script handles:

- Network configuration (static IP via NetworkManager)
- System directory creation with proper permissions
- Python dependencies installation
- Systemd service registration with watchdog
- Automatic service restart on code updates

## Dependencies

- **Core**: PyYAML, opencv-python (or opencv-python-headless), requests, numpy
- **Camera protocols**: onvif-zeep (optional, for ONVIF cameras only)
- **System**: psutil, watchdog, systemd-python
- **Hardware**: Designed for Raspberry Pi 4, but works on any Linux system with Python 3.7+

## Environment Configuration

### System Information

- **OS**: Linux (Debian-based, tested on 6.1.0-34-amd64)
- **Shell**: /bin/bash
- **Working Directory**: /home/fede/REPOS/sai-cam

### Search Strategy

When searching for patterns in files:

1. **First choice**: Use the Grep tool with simple patterns
2. **Second choice**: Use the Read tool with line numbers for specific areas
3. **Last resort**: Use Task tool for complex searches
4. **Avoid**: Complex bash grep commands with regex patterns or `rg` (ripgrep not installed)

### Git Configuration

- **Commits**: Follow conventional commit format with emoji prefixes (see git log for examples)
- **SSH**: Some authentication issues with GitHub (use HTTPS if needed)
