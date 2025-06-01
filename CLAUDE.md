# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Configuration

### System Information
- **OS**: Linux 6.1.0-34-amd64 (Debian-based)
- **Shell**: /bin/bash
- **Working Directory**: /home/fede/REPOS/sai-cam

### Available Tools
- **grep**: GNU grep 3.8 (available at /usr/bin/grep)
- **ripgrep (rg)**: NOT AVAILABLE - avoid using `rg` commands
- **git**: Available and configured
- **Basic Unix tools**: ls, cat, head, tail, find available

### Command Restrictions & Preferences
- **AVOID**: Direct `grep` with complex regex patterns (use Grep tool instead)
- **AVOID**: `rg` commands (ripgrep not installed)
- **PREFER**: Use Claude's Grep, Read, and Task tools over bash commands for searching
- **SAFE**: Basic bash commands like `ls`, `git status`, `git diff`, `git commit`

### Search Strategy
When searching for patterns in files:
1. **First choice**: Use the Grep tool with simple patterns
2. **Second choice**: Use the Read tool with line numbers for specific areas
3. **Last resort**: Use Task tool for complex searches
4. **Avoid**: Complex bash grep commands with regex patterns

### Git Configuration
- **Repository**: Clean git repo with proper branch structure
- **SSH**: Some authentication issues with GitHub (use HTTPS if needed)
- **Commits**: Follow conventional commit format with emoji prefixes

### Known Issues to Avoid
- Complex grep patterns with `|` (OR) operators often fail
- Ripgrep commands will always fail
- Some regex escaping issues with special characters in bash
- File permission issues are rare but possible

This environment information helps Claude Code work more efficiently and avoid repetitive command errors.

## Project Overview

SAI-Cam is an edge node component of the SAI (Sistema de Alerta de Incendios) wildfire detection system. It's a Python-based camera service that captures images from multiple RTSP/ONVIF cameras and uploads them to a central server for AI-powered fire detection analysis.

## Architecture

- **Multi-camera support**: Handles up to 4 cameras simultaneously using threading
- **Camera types**: Supports RTSP streams, ONVIF cameras, and USB cameras
- **Edge deployment**: Designed for Raspberry Pi 4 with outdoor industrial housing
- **Storage management**: Local image storage with automatic cleanup and retention policies
- **Health monitoring**: System resource monitoring with automatic restart capabilities
- **Systemd integration**: Full systemd service with watchdog support

## Key Components

- `src/camera_service.py`: Main service with CameraInstance, CameraService, StorageManager, and HealthMonitor classes
- `config/config.yaml.example`: Complete configuration template for network, cameras, storage, and monitoring
- `scripts/install.sh`: Comprehensive installation script with network configuration and service setup
- `systemd/sai-cam.service`: Systemd service definition with watchdog and logging

## Common Development Commands

### Installation and Setup
```bash
# Full installation (requires sudo)
sudo ./scripts/install.sh

# Configuration-only update
sudo ./scripts/install.sh --config-only

# Install Python dependencies
pip3 install -r requirements.txt
```

### Service Management
```bash
# Check service status
sudo systemctl status sai-cam

# View service logs
sudo journalctl -u sai-cam -f

# Restart service
sudo systemctl restart sai-cam

# Stop service
sudo systemctl stop sai-cam
```

### Testing and Development
```bash
# Run service locally without uploading
python3 src/camera_service.py --local-save

# Test camera initialization only
python3 src/camera_service.py --dry-run

# Run with debug logging
python3 src/camera_service.py --log-level DEBUG

# Test ONVIF camera connectivity
python3 scripts/onvif-test.py
```

## Configuration

The service uses `/etc/sai-cam/config.yaml` for configuration. Key sections:

- **cameras**: Array of camera configurations (RTSP, ONVIF, USB)
- **network**: Optional static IP and NetworkManager settings
- **storage**: Local storage paths, retention, and cleanup thresholds
- **server**: Upload endpoint, SSL verification, and authentication
- **monitoring**: Resource limits and health check intervals
- **device**: Node identification and location metadata

## Dependencies

- **Core**: PyYAML, opencv-python, requests, numpy
- **Camera protocols**: onvif library for ONVIF camera support
- **System**: psutil, watchdog, systemd-python
- **Hardware requirements**: Raspberry Pi 4, IP cameras, PoE switch

## File Locations

- **Installation**: `/opt/sai-cam/`
- **Configuration**: `/etc/sai-cam/config.yaml`
- **Logs**: `/var/log/sai-cam/`
- **Local storage**: `/opt/sai-cam/storage/`
- **Service**: `/etc/systemd/system/sai-cam.service`

## Development Notes

- Each camera runs in its own thread with independent capture intervals
- FFMPEG backend used for RTSP streams with TCP transport
- Hardware acceleration enabled for H.265 decoding on supported systems
- Automatic camera reconnection with configurable retry attempts
- Image validation prevents storing corrupted or invalid frames
- Storage manager handles cleanup based on disk usage and retention policies

## Deployment Considerations

- **Installation Script**: Always take into account that `install.sh` is used to deploy changes when proposing solutions or making modifications to the project