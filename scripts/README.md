# SAI-Cam Diagnostic Tools

Comprehensive diagnostic and testing tools for SAI-Cam edge nodes.

## Overview

This directory contains diagnostic scripts and tools for troubleshooting SAI-Cam deployments. Use these tools to:

- Test camera connectivity and ONVIF capabilities
- Diagnose network and storage issues
- Validate configuration files
- Monitor system health on remote nodes
- Clean up storage when full

## Tools

### 1. diagnostic-suite.py

**Comprehensive local diagnostic test suite**

Tests all aspects of a SAI-Cam installation including configuration, dependencies, storage, network connectivity, and source code validity.

#### Usage

```bash
# Run all tests
python3 scripts/diagnostic-suite.py

# Run specific test
python3 scripts/diagnostic-suite.py --test config
python3 scripts/diagnostic-suite.py --test network
python3 scripts/diagnostic-suite.py --test storage

# Use custom config file
python3 scripts/diagnostic-suite.py --config /path/to/config.yaml

# Verbose output
python3 scripts/diagnostic-suite.py --verbose
```

#### Available Tests

- **config**: Validates YAML configuration file structure and camera definitions
- **deps**: Checks Python dependencies (required and optional modules)
- **network**: Tests network connectivity to cameras and upload server
- **storage**: Validates storage paths, permissions, and disk usage
- **source**: Checks source code files exist and have valid Python syntax
- **service**: Tests systemd service configuration (if applicable)

#### Example Output

```
=== Testing Configuration ===
✓ PASS Config File Exists: Found at /etc/sai-cam/config.yaml
✓ PASS Config File Valid YAML: Successfully parsed
✓ PASS Camera Configuration: 4 cameras configured

=== Test Summary ===
Total tests: 24
Passed: 24
✓ All tests passed!
```

---

### 2. onvif-diagnostics.py

**ONVIF camera connectivity and capability testing**

Tests ONVIF camera connections, retrieves device information, media profiles, and validates snapshot capture.

#### Usage

```bash
# Test single camera
python3 scripts/onvif-diagnostics.py \
  --host 192.168.220.10 \
  --port 80 \
  --user admin \
  --password "Saicam1!"

# Test all cameras from config
python3 scripts/onvif-diagnostics.py --config /etc/sai-cam/config.yaml

# On deployed node with venv
/opt/sai-cam/venv/bin/python3 scripts/onvif-diagnostics.py --config /etc/sai-cam/config.yaml
```

#### What It Tests

1. **Basic Connectivity**
   - Ping test
   - TCP port connectivity
   - HTTP response

2. **ONVIF Connection**
   - Device information retrieval
   - System date/time
   - Network interfaces
   - Camera capabilities
   - Media profiles
   - Snapshot URI and download

#### Example Output

```
=== Testing ONVIF Connection ===
Camera: admin@192.168.220.10:80
✓ Device Information Retrieved:
  Manufacturer: REOLINK
  Model: P320
  Firmware: v3.1.0.3646_2406143592
✓ Found 2 media profile(s):
  Profile 1: Profile000_MainStream
    Resolution: 2304x1296
    ✓ Snapshot downloaded successfully (1.2 MB)
```

---

### 3. remote-diagnostics.sh

**Remote node health check and diagnostics**

Connects to a remote SAI-Cam node via SSH and performs comprehensive health checks.

#### Usage

```bash
# Test default node
./scripts/remote-diagnostics.sh

# Test specific node
./scripts/remote-diagnostics.sh admin@saicam5.local
./scripts/remote-diagnostics.sh admin@saicam7.local
```

#### What It Checks

1. **Network**: SSH connectivity, ping
2. **System**: Hostname, uptime, kernel version
3. **Service**: Status, PID, memory, CPU usage
4. **Resources**: Memory usage, disk space
5. **Storage**: Image count, size, oldest/newest images
6. **Cameras**: Ping test to each camera IP
7. **Server**: Connectivity to upload server
8. **Logs**: Recent errors and warnings

#### Example Output

```
=== SAI-Cam Remote Node Diagnostics ===
Target: admin@saicam5.local

=== System Information ===
  Hostname: saicam5
  Uptime: up 6 hours, 56 minutes
  Kernel: 6.12.20+rpt-rpi-v8

=== SAI-Cam Service Status ===
✓ Service is running
  PID: 1716
  Memory: 303.5 MB
  CPU: 127%

=== Image Storage ===
  Storage size: 7.1G
  Image count: 6928
✗ Storage exceeds configured limit (5GB)

✓ Node appears healthy
```

---

### 4. storage-cleanup.sh

**Manual storage cleanup utility**

Removes oldest images when storage exceeds configured limit.

#### Usage

```bash
# Use default paths
./scripts/storage-cleanup.sh

# Specify custom paths
./scripts/storage-cleanup.sh /opt/sai-cam/storage 5

# Run on remote node
ssh admin@saicam5.local 'bash -s' < scripts/storage-cleanup.sh
```

#### Features

- Calculates current storage usage
- Compares against configured limit
- Deletes oldest images first
- Targets 80% of max size to prevent immediate refill
- Shows progress during cleanup
- Provides before/after statistics

#### Example Output

```
=== SAI-Cam Storage Cleanup Utility ===
Storage path: /opt/sai-cam/storage
Max size: 5GB

Current size: 7.11GB
Image count: 6928
⚠ Storage exceeds limit by 2.11GB

Target size: 4.00GB (80% of max)
Need to delete: 3.11GB

Continue with cleanup? [y/N]: y
  Deleted 100 files (0.15GB)
  Deleted 200 files (0.31GB)
  ...

✓ Cleanup complete!
Files deleted: 3241
New size: 3.98GB
Remaining images: 3687
```

---

### 5. camera-test.py

**Individual camera type testing**

Tests USB, RTSP, and ONVIF cameras with configurable parameters.

#### Usage

```bash
# Generate test configuration
python3 scripts/camera-test.py --generate-config

# Test with generated config
python3 scripts/camera-test.py --config camera-test-config.yaml

# Test specific camera type
python3 scripts/camera-test.py \
  --config camera-test-config.yaml \
  --camera-type onvif \
  --save-images

# Test in local mode (no server upload)
python3 scripts/camera-test.py \
  --config camera-test-config.yaml \
  --local-save
```

---

### 6. onvif-test.py

**Legacy ONVIF connection test**

Simple script for testing ONVIF camera connections. Superseded by `onvif-diagnostics.py` but kept for compatibility.

#### Usage

```bash
python3 scripts/onvif-test.py
```

---

## Common Diagnostic Workflows

### Troubleshooting a Non-Working Node

1. **Check basic connectivity**
   ```bash
   ./scripts/remote-diagnostics.sh admin@saicam5.local
   ```

2. **Run local diagnostic suite on the node**
   ```bash
   ssh admin@saicam5.local
   cd /opt/sai-cam
   /opt/sai-cam/venv/bin/python3 scripts/diagnostic-suite.py --verbose
   ```

3. **Test ONVIF cameras specifically**
   ```bash
   ssh admin@saicam5.local
   /opt/sai-cam/venv/bin/python3 scripts/onvif-diagnostics.py --config /etc/sai-cam/config.yaml
   ```

4. **Check service logs**
   ```bash
   ssh admin@saicam5.local
   sudo journalctl -u sai-cam -f
   tail -f /var/log/sai-cam/camera_service.log
   ```

### Diagnosing Camera Connection Issues

1. **Verify network connectivity**
   ```bash
   ping 192.168.220.10  # Camera IP
   ```

2. **Test ONVIF capabilities**
   ```bash
   python3 scripts/onvif-diagnostics.py --host 192.168.220.10 --user admin --password "Saicam1!"
   ```

3. **Check camera configuration**
   ```bash
   python3 scripts/diagnostic-suite.py --test config
   ```

### Fixing Storage Issues

1. **Check current storage usage**
   ```bash
   ./scripts/remote-diagnostics.sh admin@saicam5.local | grep -A5 "Storage"
   ```

2. **Manual cleanup if needed**
   ```bash
   ssh admin@saicam5.local
   cd /opt/sai-cam
   ./scripts/storage-cleanup.sh
   ```

3. **Adjust configuration if persistent**
   ```bash
   # Edit /etc/sai-cam/config.yaml
   # Increase max_size_gb or decrease cleanup_threshold_gb
   sudo nano /etc/sai-cam/config.yaml
   sudo systemctl restart sai-cam
   ```

## Integration with CI/CD

These scripts can be integrated into deployment workflows:

```bash
# Pre-deployment validation
python3 scripts/diagnostic-suite.py --config config/config.yaml

# Post-deployment verification
./scripts/remote-diagnostics.sh admin@saicam5.local

# Automated testing
python3 scripts/onvif-diagnostics.py --config /etc/sai-cam/config.yaml
```

## Exit Codes

All diagnostic scripts follow standard exit code conventions:

- **0**: All tests passed
- **1**: One or more tests failed
- **2**: Invalid arguments or configuration

Use in scripts:
```bash
if python3 scripts/diagnostic-suite.py; then
    echo "Diagnostics passed"
else
    echo "Diagnostics failed"
    exit 1
fi
```

## Requirements

- Python 3.7+
- SSH access to remote nodes (for remote-diagnostics.sh)
- onvif-zeep for ONVIF testing (optional)

Install dependencies:
```bash
pip3 install -r requirements.txt
```

## Tips and Best Practices

1. **Regular Health Checks**: Run `remote-diagnostics.sh` daily on all nodes
2. **Pre-Deployment Testing**: Always run `diagnostic-suite.py` before deploying
3. **Storage Monitoring**: Set up alerts when storage exceeds 80%
4. **Camera Testing**: Use `onvif-diagnostics.py` when adding new cameras
5. **Logging**: Use `--verbose` flag when investigating issues

## Troubleshooting Common Issues

### "ONVIF module not found"

```bash
pip3 install onvif-zeep
```

### "Permission denied" when accessing logs

```bash
# Add user to admin group or use sudo
sudo tail -f /var/log/sai-cam/camera_service.log
```

### "No module named 'cameras'"

```bash
# Ensure PYTHONPATH is set correctly
export PYTHONPATH=/opt/sai-cam
```

### "WSDL files not found"

The ONVIF library needs WSDL files. They're typically in:
```bash
/opt/sai-cam/venv/lib/python3.*/site-packages/wsdl/
```

Check with:
```bash
find /opt/sai-cam/venv -name "devicemgmt.wsdl"
```

## Contributing

When adding new diagnostic tools:

1. Follow the naming convention: `<function>-<type>.py` or `<function>-<type>.sh`
2. Include comprehensive help text (`--help` flag)
3. Support both verbose and quiet modes
4. Use standard exit codes
5. Add color-coded output for readability
6. Document in this README

## Support

For issues or questions:
- Check the main [project README](../README.md)
- Review service logs: `/var/log/sai-cam/camera_service.log`
- Open an issue in the project repository
