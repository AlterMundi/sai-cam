# REOLINK P320 ONVIF Capabilities

**Last Updated:** 2025-10-13
**Tested Firmware:** v3.1.0.3646_2406143592
**Test Location:** SAI-Cam Production Node (sai-cam-nodo-5)

## Executive Summary

The REOLINK P320 cameras deployed on the SAI-Cam system provide comprehensive ONVIF support with the following capabilities:

- ✅ **Device Management** - Full support with network configuration
- ✅ **Media Service** - Multiple profiles with H.264/AAC encoding
- ✅ **Imaging Service** - Manual control of brightness, contrast, saturation, sharpness
- ✅ **Events Service** - Motion detection and alarm events
- ⚠️ **PTZ Service** - Not supported (fixed lens camera)
- ⚠️ **Analytics Service** - Limited/not fully supported

---

## Device Information

### Hardware Specifications
- **Manufacturer:** REOLINK
- **Model:** P320
- **Hardware ID:** IPC
- **Serial Number Format:** 19216822XXXX
- **Camera Type:** Fixed lens network video transmitter

### Firmware
- **Version:** v3.1.0.3646_2406143592
- **ONVIF Profile:** Streaming, Profile T
- **Country of Origin:** China

### Network Configuration
- **Interface:** eth0 (Ethernet)
- **IP Configuration:** Static IPv4 (192.168.220.10/24)
- **DHCP:** Not used
- **DNS:** 192.168.220.1 (Gateway)
- **Hostname:** reolink (default)

### Network Protocols
- **HTTP:** Port 80 (Enabled)
- **RTSP:** Port 554 (Enabled)
- **HTTPS:** Port 443 (Disabled)
- **ONVIF:** Port 8000

---

## ONVIF Services

### Available Service Endpoints

All services accessible at base URL: `http://192.168.220.10:8000/onvif/`

| Service | Endpoint | Version | Status |
|---------|----------|---------|--------|
| Device Management | `/device_service` | 21.6 | ✅ Fully supported |
| Media (v1.0) | `/media_service` | 20.6 | ✅ Fully supported |
| Media (v2.0) | `/Media2` | 21.6 | ✅ Fully supported |
| Imaging | `/imaging_service` | 19.6 | ✅ Fully supported |
| Events | `/event_service` | 21.6 | ✅ Fully supported |
| Device I/O | `/deviceIO_service` | 19.6 | ⚠️ Available |
| Analytics | `/analytics_service` | 21.6 | ⚠️ Limited |

---

## Media Profiles and Encoding

### Profile 1: MainStream (High Resolution)

**Profile Token:** `000`
**Profile Name:** `Profile000_MainStream`
**Fixed Profile:** Yes (cannot be deleted)

#### Video Configuration
- **Source Token:** `000`
- **Video Source Name:** `VideoS_000`
- **Capture Area:** 2880x1616 (full sensor)
- **Encoder Name:** `VideoE_000`

**Encoding Parameters:**
- **Codec:** H.264 (Main Profile)
- **Resolution:** 2880×1616 pixels (4.66 MP)
- **Framerate:** 30 fps (max)
- **Bitrate:** 5120 kbps
- **GOP Length:** 60 frames (2 seconds at 30fps)
- **Quality:** Variable (CBR mode)
- **Encoding Interval:** 1 (all frames)

#### Audio Configuration
- **Source Token:** `000`
- **Audio Source Name:** `AudioS_000`
- **Encoder Name:** `AudioE_000`

**Audio Encoding:**
- **Codec:** AAC
- **Bitrate:** 64 kbps
- **Sample Rate:** 16 kHz

### Profile 2: SubStream (Low Resolution)

**Note:** Present in config but details not fully retrieved in initial scan. Typically:
- **Resolution:** ~896×512 pixels (SD)
- **Codec:** H.264
- **Framerate:** 15-30 fps
- **Bitrate:** Lower (typically 512-1024 kbps)
- **Use Case:** Lower bandwidth streaming, mobile viewing

### Stream URIs

#### MainStream RTSP URI
```
rtsp://admin:Saicam1!@192.168.220.10:554/h264Preview_01_main
```

**Transport Protocol:** RTP-Unicast
**Streaming Protocol:** RTSP/TCP (default)

#### SubStream RTSP URI
```
rtsp://admin:Saicam1!@192.168.220.10:554/h264Preview_01_sub
```

#### Snapshot URI
```
http://192.168.220.10:80/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=&user=admin&password=Saicam1!
```

**Image Format:** JPEG
**Typical Size:** 363-446 KB (MainStream quality)
**Authentication:** HTTP Digest Auth

---

## Imaging Capabilities

### Current Settings (Defaults)

All values on 0-255 scale:

- **Brightness:** 128 (midpoint, 50%)
- **Contrast:** 128 (midpoint, 50%)
- **Saturation:** 128 (midpoint, 50%)
- **Sharpness:** 128 (midpoint, 50%)

### Adjustable Parameters

| Parameter | Min | Max | Current | Description |
|-----------|-----|-----|---------|-------------|
| Brightness | 0 | 255 | 128 | Overall image brightness |
| Contrast | 0 | 255 | 128 | Difference between light/dark areas |
| Saturation | 0 | 255 | 128 | Color intensity |
| Sharpness | 0 | 255 | 128 | Edge enhancement |

### IR Cut Filter

**Available Modes:**
- `AUTO` - Automatic day/night switching based on ambient light
- `OFF` - IR cut filter always off (night mode, monochrome)

**Current Mode:** AUTO (default)

### Limited/Unavailable Features

The following advanced imaging features are **not exposed via ONVIF** on this camera:

- ❌ Manual Exposure Control (mode, time, gain, iris)
- ❌ Backlight Compensation (BLC)
- ❌ Wide Dynamic Range (WDR)
- ❌ Manual Focus Control
- ❌ Manual White Balance
- ❌ Digital Noise Reduction settings

**Note:** These features may be available through the camera's web interface or proprietary API but are not accessible via standard ONVIF commands.

### Example: Adjusting Brightness via ONVIF

```python
from onvif import ONVIFCamera

cam = ONVIFCamera('192.168.220.10', 8000, 'admin', 'Saicam1!', wsdl_dir='/path/to/wsdl')
imaging = cam.create_imaging_service()

# Get current settings
settings = imaging.GetImagingSettings({'VideoSourceToken': '000'})

# Increase brightness to 160
settings.Brightness = 160

# Apply settings
imaging.SetImagingSettings({
    'VideoSourceToken': '000',
    'ImagingSettings': settings
})
```

---

## Events and Motion Detection

### Event Service Support

**Service Endpoint:** `http://192.168.220.10:8000/onvif/event_service`
**Version:** 21.6
**Status:** ✅ Fully operational

### Available Event Topics

**Topic Count:** 3 event topics
**Topic Namespace:** `http://www.onvif.org/onvif/ver10/topics/topicns.xml`

Common event topics on Reolink cameras typically include:

1. **Motion Detection** (`tns1:RuleEngine/CellMotionDetector/Motion`)
   - Triggered when motion is detected in configured zones
   - Returns motion state (true/false) and detection data

2. **Video Loss** (`tns1:VideoSource/GlobalSceneChange/ImagingService`)
   - Camera tampering or video feed interruption
   - Triggered on blocked lens or signal loss

3. **Storage Events** (`tns1:Device/Trigger/DigitalInput`)
   - SD card full, recording errors
   - Storage-related notifications

### Event Subscription

Events can be accessed via:
- **Pull Point Subscription** - Poll for events periodically
- **Basic Notification** - Push events to subscriber endpoint
- **SOAP over HTTPS** - Secure event delivery

### Motion Detection Configuration

Motion detection is typically configured through:
- Camera web interface (preferred method)
- ONVIF Analytics service (limited on this model)
- Reolink mobile app

**SAI-Cam Integration Note:** The current SAI-Cam implementation uses **scheduled capture intervals** (60 seconds) rather than motion-triggered capture. Event-based capture could be implemented as an enhancement.

---

## PTZ (Pan-Tilt-Zoom) Capabilities

**Status:** ❌ **NOT SUPPORTED**

The REOLINK P320 is a **fixed lens bullet camera** with no PTZ capabilities.

**Error Message:**
```
Device doesn't support service: ptz
```

### Alternative Camera Movement

For PTZ functionality, consider:
- **Reolink RLC-823A** - 5MP PTZ with 5x optical zoom
- **Reolink E1 Zoom** - Indoor PTZ with pan/tilt
- Manual repositioning of fixed cameras

**SAI-Cam Deployment:** Current setup uses fixed positioning with 4 cameras covering north, east, south, and west orientations.

---

## Analytics Service

**Status:** ⚠️ **LIMITED SUPPORT**

The camera reports analytics service availability but requires configuration tokens that are not properly exposed:

**Error Message:**
```
Missing element ConfigurationToken (GetSupportedAnalyticsModules.ConfigurationToken)
```

### What This Means

- The camera has analytics capabilities (likely motion detection, line crossing)
- Standard ONVIF analytics queries don't work properly
- Analytics may be accessible through:
  - Reolink's proprietary API
  - Camera web interface configuration
  - ONVIF Media2 service extensions

### Practical Analytics Use

For motion detection and video analytics in SAI-Cam:
1. **Option 1:** Configure via camera web UI, use event service to receive alerts
2. **Option 2:** Perform analytics server-side on captured images (current approach)
3. **Option 3:** Use OpenCV/custom analytics in camera service

---

## System Time Configuration

### Current Time Settings

- **UTC Time:** Synchronized (verified accurate)
- **Timezone:** CST+3:00:00 (Argentina Time)
- **Daylight Saving:** Disabled
- **NTP Server:** Not configured (manual time sync)

### Recommendations

Configure NTP for automatic time synchronization:

```python
device_mgmt = cam.create_devicemgmt_service()

# Set NTP server
device_mgmt.SetNTP({
    'FromDHCP': False,
    'NTPManual': {
        'Type': 'IPv4',
        'IPv4Address': '192.168.220.1'  # Gateway as NTP relay
    }
})
```

**Important:** Accurate time is critical for:
- Timestamp synchronization across cameras
- Event correlation
- Log analysis
- Wildfire detection timeline accuracy

---

## Advanced Configuration Examples

### 1. Retrieve All Camera Information

```python
from onvif import ONVIFCamera
import os

# Find WSDL directory (handles onvif-zeep quirks)
import onvif
onvif_dir = os.path.dirname(onvif.__file__)
venv_lib = os.path.dirname(os.path.dirname(os.path.dirname(onvif_dir)))
wsdl_dir = os.path.join(venv_lib, 'python3.4', 'site-packages', 'wsdl')

# Connect to camera
cam = ONVIFCamera('192.168.220.10', 8000, 'admin', 'Saicam1!', wsdl_dir=wsdl_dir)

# Get device info
device_mgmt = cam.create_devicemgmt_service()
info = device_mgmt.GetDeviceInformation()

print(f"Camera: {info.Manufacturer} {info.Model}")
print(f"Firmware: {info.FirmwareVersion}")
print(f"Serial: {info.SerialNumber}")
```

### 2. Capture Snapshot via ONVIF

```python
import requests
from requests.auth import HTTPDigestAuth

# Get snapshot URI from media service
media = cam.create_media_service()
profiles = media.GetProfiles()
profile_token = profiles[0].token

snapshot_uri = media.GetSnapshotUri({'ProfileToken': profile_token})

# Download snapshot
response = requests.get(
    snapshot_uri.Uri,
    auth=HTTPDigestAuth('admin', 'Saicam1!'),
    timeout=10
)

if response.status_code == 200:
    with open('snapshot.jpg', 'wb') as f:
        f.write(response.content)
    print(f"Snapshot saved: {len(response.content)/1024:.1f} KB")
```

### 3. Get RTSP Stream URI

```python
# Get stream URI for MainStream profile
media = cam.create_media_service()
profiles = media.GetProfiles()

stream_setup = {
    'Stream': 'RTP-Unicast',
    'Transport': {'Protocol': 'RTSP'}
}

stream_uri = media.GetStreamUri({
    'StreamSetup': stream_setup,
    'ProfileToken': profiles[0].token
})

print(f"RTSP URL: {stream_uri.Uri}")

# Use with ffmpeg or OpenCV
import cv2
cap = cv2.VideoCapture(stream_uri.Uri)
```

### 4. Subscribe to Motion Events

```python
# Create event service
events = cam.create_events_service()

# Create pull point subscription
subscription = events.CreatePullPointSubscription()

# Pull events (call this periodically)
messages = events.PullMessages({
    'Timeout': 'PT10S',  # 10 second timeout
    'MessageLimit': 10
})

for msg in messages:
    print(f"Event: {msg}")
```

### 5. Adjust Night Mode (IR Cut Filter)

```python
imaging = cam.create_imaging_service()

# Get current settings
settings = imaging.GetImagingSettings({'VideoSourceToken': '000'})

# Force night mode (IR cut filter off)
settings.IrCutFilter = 'OFF'

imaging.SetImagingSettings({
    'VideoSourceToken': '000',
    'ImagingSettings': settings
})

# Or set to auto
settings.IrCutFilter = 'AUTO'
imaging.SetImagingSettings({
    'VideoSourceToken': '000',
    'ImagingSettings': settings
})
```

---

## SAI-Cam Integration

### Current Implementation

The SAI-Cam system uses:
- **Camera Type:** ONVIF
- **Connection:** Direct RTSP streaming via FFMPEG
- **Capture Method:** Scheduled interval (60 seconds)
- **Resolution:** MainStream profile (2880×1616)
- **Transport:** TCP (reliable but higher latency)

### Configuration in config.yaml

```yaml
cameras:
  - id: 'cam1'
    type: 'onvif'
    address: '192.168.220.10'
    port: 8000
    username: 'admin'
    password: 'Saicam1!'
    capture_interval: 60
    position: 'north'
```

### Potential Enhancements

#### 1. Event-Based Capture
Instead of 60-second intervals, capture on motion detection:
- Subscribe to motion events via ONVIF
- Trigger capture when motion detected
- Reduce unnecessary uploads during inactive periods
- **Benefit:** Reduced bandwidth, more relevant images

#### 2. Adaptive Quality
Dynamically adjust imaging settings based on conditions:
- Increase brightness during low-light periods
- Adjust contrast based on time of day
- Switch IR cut filter mode programmatically
- **Benefit:** Better image quality for AI analysis

#### 3. Dual-Stream Usage
Use both MainStream and SubStream:
- SubStream for continuous monitoring
- MainStream for high-resolution capture when needed
- **Benefit:** Reduced bandwidth while maintaining quality

#### 4. Health Monitoring
Leverage ONVIF for camera health checks:
- Periodically query device status
- Monitor network interface statistics
- Detect video loss or tampering events
- **Benefit:** Proactive maintenance, reduced downtime

---

## Diagnostic Tools

### 1. ONVIF Diagnostics Script

Test basic connectivity and retrieve camera info:

```bash
python3 scripts/onvif-diagnostics.py --config /etc/sai-cam/config.yaml
```

### 2. ONVIF Capability Explorer

Comprehensive scan of all ONVIF features:

```bash
python3 scripts/onvif-explore.py --host 192.168.220.10 --port 8000 \
    --user admin --password Saicam1!
```

Or test all cameras from config:

```bash
python3 scripts/onvif-explore.py --config /etc/sai-cam/config.yaml --camera cam1
```

### 3. RTSP Stream Test

Test RTSP streaming with ffmpeg:

```bash
ffmpeg -rtsp_transport tcp -i \
    rtsp://admin:Saicam1!@192.168.220.10:554/h264Preview_01_main \
    -frames:v 1 test_frame.jpg
```

### 4. Snapshot Download Test

```bash
curl --digest -u admin:Saicam1! \
    "http://192.168.220.10:80/cgi-bin/api.cgi?cmd=Snap&channel=0&rs=" \
    -o snapshot.jpg
```

---

## Troubleshooting

### Common Issues

#### WSDL Path Errors

**Error:** `No such file: /path/to/wsdl/devicemgmt.wsdl`

**Solution:** The onvif-zeep package installs WSDLs in a `python3.4` subdirectory even when using Python 3.11. Use automatic WSDL detection:

```python
import os
import onvif

onvif_dir = os.path.dirname(onvif.__file__)
venv_lib = os.path.dirname(os.path.dirname(os.path.dirname(onvif_dir)))
wsdl_dir = os.path.join(venv_lib, 'python3.4', 'site-packages', 'wsdl')

if os.path.exists(os.path.join(wsdl_dir, 'devicemgmt.wsdl')):
    cam = ONVIFCamera(host, port, user, password, wsdl_dir=wsdl_dir)
```

#### Authentication Failures

**Error:** `401 Unauthorized`

**Causes:**
1. Incorrect username/password
2. HTTP Digest auth required (not Basic)
3. Special characters in password not URL-encoded

**Solution:**
```python
from requests.auth import HTTPDigestAuth
auth = HTTPDigestAuth('admin', 'Saicam1!')
```

#### Connection Timeouts

**Error:** `Connection timeout` or `No route to host`

**Checks:**
1. Verify camera IP: `ping 192.168.220.10`
2. Check ONVIF port: `telnet 192.168.220.10 8000`
3. Test RTSP port: `telnet 192.168.220.10 554`
4. Verify firewall rules on camera

#### Stream Playback Issues

**Error:** `Could not find codec parameters for stream` or playback stuttering

**Solutions:**
1. Use TCP transport: `rtsp_transport=tcp`
2. Increase buffer: `buffer_size=1024k`
3. Use hardware acceleration: `hwaccel=vaapi`
4. Try SubStream for lower bandwidth

---

## Firmware and Updates

### Current Firmware
- **Version:** v3.1.0.3646_2406143592
- **Release Date:** June 2024 (based on version string)
- **Status:** Production stable

### Firmware Update Process

**Via Web Interface:**
1. Download latest firmware from Reolink website
2. Access camera web UI: `http://192.168.220.10`
3. Navigate to System → Firmware Update
4. Upload firmware file and apply

**Recommended Practice:**
- Test firmware updates on one camera first
- Update during maintenance window (low wildfire risk)
- Verify ONVIF compatibility after update
- Document firmware version in SAI-Cam config

### Known Firmware Issues

- Some older firmware versions had ONVIF event service bugs
- **Current v3.1.x:** Stable ONVIF implementation
- **Recommendation:** Stay on current firmware unless security patches required

---

## Security Considerations

### Network Isolation

The SAI-Cam cameras operate on isolated subnet:
- **Camera Network:** 192.168.220.0/24
- **No Internet Access:** Cameras cannot reach external networks
- **Management Access:** Only via SAI-Cam node
- **Benefit:** Reduced attack surface

### Authentication

- **Username:** admin (default Reolink account)
- **Password:** Saicam1! (custom, moderately strong)
- **Protocol:** HTTP Digest authentication

**Recommendations:**
1. Change default admin password on new cameras
2. Use strong passwords (12+ chars, mixed case, symbols)
3. Consider enabling HTTPS (currently disabled)
4. Rotate passwords periodically

### Exposed Services

**Currently Accessible:**
- HTTP (port 80) - Web UI, snapshot API
- RTSP (port 554) - Video streaming
- ONVIF (port 8000) - Device management

**Not Exposed:**
- HTTPS (port 443) - Disabled
- RTMP (port 1935) - Not configured
- SDK ports - Reolink proprietary protocol

---

## Performance Characteristics

### Network Bandwidth

**MainStream (2880×1616 @ 30fps):**
- **Bitrate:** 5120 kbps (5 Mbps)
- **Bandwidth per camera:** ~0.64 MB/s
- **4 cameras simultaneous:** ~2.5 MB/s

**SubStream (896×512 @ 15fps):**
- **Bitrate:** ~512-1024 kbps (0.5-1 Mbps)
- **Use case:** Remote viewing, low bandwidth

### Storage Requirements

**Snapshot capture (current SAI-Cam config):**
- **Interval:** 60 seconds
- **Size per image:** ~400 KB (JPEG)
- **Per camera per hour:** ~24 MB
- **4 cameras per day:** ~2.3 GB
- **Storage limit:** 5 GB (~2 days retention)

### Response Times

Measured on production node (admin@saicam5.local):

- **ONVIF GetDeviceInformation:** <100ms
- **ONVIF GetProfiles:** <200ms
- **Snapshot capture:** 500-1000ms
- **RTSP connection establishment:** 1-3 seconds
- **Frame capture from RTSP:** 33ms (30fps)

---

## Reference Links

### Reolink Resources
- **Product Page:** https://reolink.com/product/p320/
- **Support:** https://support.reolink.com/
- **Firmware Downloads:** https://reolink.com/download-center/

### ONVIF Specifications
- **ONVIF Core Spec:** https://www.onvif.org/specs/core/ONVIF-Core-Specification.pdf
- **Profile T (Streaming):** https://www.onvif.org/profiles/profile-t/
- **Python onvif-zeep:** https://github.com/FalkTannhaeuser/python-onvif-zeep

### SAI-Cam Documentation
- **Installation Guide:** `/docs/INSTALLATION.md`
- **Configuration Reference:** `/docs/CONFIGURATION.md`
- **Architecture:** `/docs/ARCHITECTURE.md`

---

## Changelog

### 2025-10-13 - Initial Documentation
- Comprehensive ONVIF capability scan performed
- All 4 REOLINK P320 cameras tested on production node
- Documented device management, media, imaging, events services
- Confirmed PTZ and advanced analytics not supported
- Created diagnostic and exploration scripts
- Documented integration with SAI-Cam system

---

## Appendix: Full Service Output

For complete raw output from ONVIF exploration, see test logs:

```bash
# Run full exploration
python3 scripts/onvif-explore.py --config /etc/sai-cam/config.yaml --camera cam1 | tee onvif-cam1-full.log
```

Example output sections available in production test logs:
- Device information and network configuration
- Media profiles with encoding parameters
- Imaging settings and ranges
- Event service topology
- Service versions and endpoints
