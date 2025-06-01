# SAI-Cam Multi-Camera Testing Guide

## 🚀 Quick Setup and Testing

### 1. Create Virtual Environment
```bash
cd /home/fede/REPOS/sai-cam
python3 -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies
```bash
# Install all required packages
pip install -r requirements.txt

# Verify installation
python3 -c "import cv2, numpy, yaml, requests; from onvif import ONVIFCamera; print('✅ All dependencies installed')"
```

### 3. 🔐 Configure Credentials (Multiple Methods)

#### **Method A: Environment Variables (Recommended)**
```bash
# Copy template and edit with your values
cp .env.example .env
# Edit .env with your actual camera credentials

# Example .env content:
# CAMERA_IP=192.168.1.100
# CAMERA_USERNAME=admin
# CAMERA_PASSWORD=your_secure_password
```

#### **Method B: Environment Variables (Direct)**
```bash
# Set directly in shell
export CAMERA_IP="192.168.1.100"
export CAMERA_USERNAME="admin"
export CAMERA_PASSWORD="your_secure_password"
```

#### **Method C: Config File with Environment Variables**
```yaml
# camera-test-config.yaml
cameras:
  - id: 'test_onvif'
    type: 'onvif'
    address: '${CAMERA_IP}'           # Uses environment variable
    username: '${CAMERA_USERNAME}'   # Uses environment variable
    password: '${CAMERA_PASSWORD}'   # Uses environment variable
```

### 3. Test the Architecture
```bash
# Run architecture demonstration (no hardware needed)
python3 scripts/architecture-demo.py

# Generate test configuration
python3 scripts/camera-test.py --generate-config

# This creates: camera-test-config.yaml
```

### 4. Configure Your Cameras

Edit `camera-test-config.yaml` with your actual camera settings:

```yaml
cameras:
  # Test with your ONVIF camera (from onvif-test.py)
  - id: 'test_onvif'
    type: 'onvif'
    address: '${CAMERA_IP:-192.168.1.100}'  # Use environment variable or example
    port: 8000
    username: '${CAMERA_USERNAME:-admin}'
    password: '${CAMERA_PASSWORD:-your_password_here}'  # CHANGE THIS!
    capture_interval: 5

  # Add USB camera if available
  - id: 'test_usb'
    type: 'usb'
    device_path: '/dev/video0'
    resolution: [640, 480]
    fps: 30
    capture_interval: 5

  # Add RTSP camera if available
  - id: 'test_rtsp'
    type: 'rtsp'
    rtsp_url: 'rtsp://admin:password@192.168.x.x:554/stream'
    resolution: [1280, 720]
    capture_interval: 5
```

### 5. Run Tests

```bash
# Test all configured cameras
python3 scripts/camera-test.py --config camera-test-config.yaml --save-images --log-level DEBUG

# Test only ONVIF cameras
python3 scripts/camera-test.py --config camera-test-config.yaml --camera-type onvif --save-images

# Test only USB cameras
python3 scripts/camera-test.py --camera-type usb --save-images
```

### 6. Check Results

```bash
# Check test output
ls -la test_output/
cat test_output/test_results.json

# View captured images
ls -la test_output/*.jpg
```

## Expected Dependencies Status

| Module | Required | Status | Notes |
|--------|----------|--------|-------|
| PyYAML | ✅ | Available | Config file parsing |
| opencv-python | ✅ | **Need to install** | Camera operations |
| numpy | ✅ | Available | Image processing |
| requests | ✅ | Available | HTTP operations |
| onvif-zeep | ✅ | **Need to install** | ONVIF protocol |
| psutil | ✅ | Available | System monitoring |
| watchdog | ✅ | Available | File monitoring |
| systemd-python | ⚠️ | Available | Optional for testing |

## Troubleshooting

### OpenCV Issues
```bash
# If opencv-python fails to install
pip install opencv-python-headless>=4.8.0

# For Raspberry Pi
sudo apt-get install python3-opencv
```

### ONVIF Issues
```bash
# If onvif-zeep has conflicts
pip install onvif-zeep==0.2.12 --no-deps
pip install zeep lxml
```

### USB Camera Issues
```bash
# Check available USB cameras
ls /dev/video*

# Test USB camera access
python3 -c "import cv2; cap=cv2.VideoCapture(0); print('USB camera:', cap.isOpened()); cap.release()"
```

## Test Results Interpretation

- **creation: true** - Camera object created successfully
- **setup: true** - Camera connected and initialized
- **capture: true** - Successfully captured and validated frame
- **cleanup: true** - Resources cleaned up properly

All tests should show `true` for a fully working camera setup.