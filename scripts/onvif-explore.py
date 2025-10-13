#!/usr/bin/env python3
"""
SAI-Cam ONVIF Capability Explorer
Explores all available ONVIF commands and capabilities for a camera

Usage:
    python3 scripts/onvif-explore.py --host 192.168.220.10 --user admin --password Saicam1!
    python3 scripts/onvif-explore.py --config /etc/sai-cam/config.yaml --camera cam1
"""

import argparse
import sys
import yaml
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
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    END = '\033[0m'
    BOLD = '\033[1m'

def log(message, level="INFO"):
    """Log with color"""
    colors = {
        "INFO": Colors.BLUE,
        "SUCCESS": Colors.GREEN,
        "WARNING": Colors.YELLOW,
        "ERROR": Colors.RED,
        "SECTION": Colors.CYAN,
        "DATA": Colors.MAGENTA
    }
    color = colors.get(level, "")
    print(f"{color}{message}{Colors.END}")

def find_wsdl_dir():
    """Find WSDL directory for onvif-zeep"""
    import os
    import onvif

    onvif_dir = os.path.dirname(onvif.__file__)
    venv_lib = os.path.dirname(os.path.dirname(os.path.dirname(onvif_dir)))

    wsdl_candidates = [
        os.path.join(os.path.dirname(onvif_dir), 'wsdl'),
        os.path.join(venv_lib, 'python3.4', 'site-packages', 'wsdl'),
        os.path.join(venv_lib, 'wsdl'),
    ]

    for candidate in wsdl_candidates:
        if os.path.exists(os.path.join(candidate, 'devicemgmt.wsdl')):
            return candidate
    return None

def explore_device_management(cam):
    """Explore Device Management service"""
    log("\n" + "="*60, "SECTION")
    log("DEVICE MANAGEMENT SERVICE", "SECTION")
    log("="*60, "SECTION")

    try:
        device_mgmt = cam.create_devicemgmt_service()

        # Device Information
        log("\n[Device Information]", "INFO")
        device_info = device_mgmt.GetDeviceInformation()
        log(f"  Manufacturer: {device_info.Manufacturer}", "DATA")
        log(f"  Model: {device_info.Model}", "DATA")
        log(f"  Firmware: {device_info.FirmwareVersion}", "DATA")
        log(f"  Serial: {device_info.SerialNumber}", "DATA")
        log(f"  Hardware: {device_info.HardwareId}", "DATA")

        # System Date and Time
        log("\n[System Date/Time]", "INFO")
        try:
            system_date = device_mgmt.GetSystemDateAndTime()
            log(f"  UTC: {system_date.UTCDateTime.Date.Year}-{system_date.UTCDateTime.Date.Month:02d}-{system_date.UTCDateTime.Date.Day:02d} "
                f"{system_date.UTCDateTime.Time.Hour:02d}:{system_date.UTCDateTime.Time.Minute:02d}:{system_date.UTCDateTime.Time.Second:02d}", "DATA")
            log(f"  Timezone: {system_date.TimeZone.TZ if hasattr(system_date, 'TimeZone') else 'N/A'}", "DATA")
            log(f"  DST: {system_date.DaylightSavings if hasattr(system_date, 'DaylightSavings') else 'N/A'}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Network Interfaces
        log("\n[Network Interfaces]", "INFO")
        try:
            interfaces = device_mgmt.GetNetworkInterfaces()
            for interface in interfaces:
                name = interface.Info.Name if hasattr(interface, 'Info') else 'Unknown'
                log(f"  Interface: {name}", "DATA")
                if hasattr(interface, 'Enabled'):
                    log(f"    Enabled: {interface.Enabled}", "DATA")
                if hasattr(interface, 'IPv4'):
                    if interface.IPv4.Config.DHCP:
                        log(f"    IPv4: DHCP", "DATA")
                    if interface.IPv4.Config.Manual:
                        for manual in interface.IPv4.Config.Manual:
                            log(f"    IPv4: {manual.Address}/{manual.PrefixLength}", "DATA")
                if hasattr(interface, 'IPv6'):
                    log(f"    IPv6: Enabled={interface.IPv6.Enabled if hasattr(interface.IPv6, 'Enabled') else 'N/A'}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Network Protocols
        log("\n[Network Protocols]", "INFO")
        try:
            protocols = device_mgmt.GetNetworkProtocols()
            for protocol in protocols:
                log(f"  {protocol.Name}: Enabled={protocol.Enabled}, Port={protocol.Port if hasattr(protocol, 'Port') else 'N/A'}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Hostname
        log("\n[Hostname]", "INFO")
        try:
            hostname = device_mgmt.GetHostname()
            log(f"  Name: {hostname.Name}", "DATA")
            log(f"  From DHCP: {hostname.FromDHCP}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # DNS
        log("\n[DNS Configuration]", "INFO")
        try:
            dns = device_mgmt.GetDNS()
            log(f"  From DHCP: {dns.FromDHCP}", "DATA")
            if hasattr(dns, 'DNSManual'):
                for server in dns.DNSManual:
                    log(f"  DNS Server: {server.IPv4Address if hasattr(server, 'IPv4Address') else server}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # NTP
        log("\n[NTP Configuration]", "INFO")
        try:
            ntp = device_mgmt.GetNTP()
            log(f"  From DHCP: {ntp.FromDHCP}", "DATA")
            if hasattr(ntp, 'NTPManual'):
                for server in ntp.NTPManual:
                    log(f"  NTP Server: {server.IPv4Address if hasattr(server, 'IPv4Address') else server}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Services
        log("\n[Available Services]", "INFO")
        try:
            services = device_mgmt.GetServices(False)
            for service in services:
                log(f"  {service.Namespace}: {service.XAddr}", "DATA")
                if hasattr(service, 'Version'):
                    log(f"    Version: {service.Version.Major}.{service.Version.Minor}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Capabilities
        log("\n[Device Capabilities]", "INFO")
        try:
            capabilities = device_mgmt.GetCapabilities()
            if hasattr(capabilities, 'Analytics'):
                log(f"  Analytics: {capabilities.Analytics.XAddr if capabilities.Analytics else 'Not supported'}", "DATA")
            if hasattr(capabilities, 'Device'):
                log(f"  Device: {capabilities.Device.XAddr}", "DATA")
            if hasattr(capabilities, 'Events'):
                log(f"  Events: {capabilities.Events.XAddr if capabilities.Events else 'Not supported'}", "DATA")
            if hasattr(capabilities, 'Imaging'):
                log(f"  Imaging: Available", "DATA")
            if hasattr(capabilities, 'Media'):
                log(f"  Media: {capabilities.Media.XAddr}", "DATA")
            if hasattr(capabilities, 'PTZ'):
                log(f"  PTZ: {capabilities.PTZ.XAddr if capabilities.PTZ else 'Not supported'}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Scopes
        log("\n[Device Scopes]", "INFO")
        try:
            scopes = device_mgmt.GetScopes()
            for scope in scopes:
                log(f"  {scope.ScopeItem}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        return True

    except Exception as e:
        log(f"Failed to explore device management: {e}", "ERROR")
        return False

def explore_media_service(cam):
    """Explore Media service"""
    log("\n" + "="*60, "SECTION")
    log("MEDIA SERVICE", "SECTION")
    log("="*60, "SECTION")

    try:
        media = cam.create_media_service()

        # Media Profiles
        log("\n[Media Profiles]", "INFO")
        profiles = media.GetProfiles()

        for i, profile in enumerate(profiles):
            log(f"\n  Profile {i+1}: {profile.Name} (Token: {profile.token})", "DATA")
            log(f"    Fixed: {profile.fixed if hasattr(profile, 'fixed') else 'N/A'}", "DATA")

            # Video Source Configuration
            if hasattr(profile, 'VideoSourceConfiguration'):
                vsc = profile.VideoSourceConfiguration
                log(f"    Video Source: {vsc.Name}", "DATA")
                log(f"      Source Token: {vsc.SourceToken}", "DATA")
                log(f"      Bounds: {vsc.Bounds.width}x{vsc.Bounds.height} at ({vsc.Bounds.x},{vsc.Bounds.y})", "DATA")

            # Video Encoder Configuration
            if hasattr(profile, 'VideoEncoderConfiguration'):
                vec = profile.VideoEncoderConfiguration
                log(f"    Video Encoder: {vec.Name}", "DATA")
                log(f"      Encoding: {vec.Encoding}", "DATA")
                log(f"      Resolution: {vec.Resolution.Width}x{vec.Resolution.Height}", "DATA")
                log(f"      Quality: {vec.Quality}", "DATA")
                log(f"      Framerate Limit: {vec.RateControl.FrameRateLimit}", "DATA")
                log(f"      Bitrate Limit: {vec.RateControl.BitrateLimit}", "DATA")
                log(f"      Encoding Interval: {vec.RateControl.EncodingInterval}", "DATA")
                if hasattr(vec, 'H264'):
                    log(f"      H264 Profile: {vec.H264.H264Profile}", "DATA")
                    log(f"      GOP Length: {vec.H264.GovLength}", "DATA")

            # Audio Source Configuration
            if hasattr(profile, 'AudioSourceConfiguration'):
                asc = profile.AudioSourceConfiguration
                log(f"    Audio Source: {asc.Name}", "DATA")
                log(f"      Source Token: {asc.SourceToken}", "DATA")

            # Audio Encoder Configuration
            if hasattr(profile, 'AudioEncoderConfiguration'):
                aec = profile.AudioEncoderConfiguration
                log(f"    Audio Encoder: {aec.Name}", "DATA")
                log(f"      Encoding: {aec.Encoding}", "DATA")
                log(f"      Bitrate: {aec.Bitrate}", "DATA")
                log(f"      Sample Rate: {aec.SampleRate}", "DATA")

            # PTZ Configuration
            if hasattr(profile, 'PTZConfiguration'):
                ptz = profile.PTZConfiguration
                log(f"    PTZ: {ptz.Name}", "DATA")
                log(f"      Node Token: {ptz.NodeToken}", "DATA")

        # Video Sources
        log("\n[Video Sources]", "INFO")
        try:
            sources = media.GetVideoSources()
            for source in sources:
                log(f"  Source: {source.token}", "DATA")
                log(f"    Framerate: {source.Framerate}", "DATA")
                log(f"    Resolution: {source.Resolution.Width}x{source.Resolution.Height}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Video Encoder Configurations
        log("\n[Video Encoder Configurations]", "INFO")
        try:
            configs = media.GetVideoEncoderConfigurations()
            for config in configs:
                log(f"  Config: {config.Name} (Token: {config.token})", "DATA")
                log(f"    Encoding: {config.Encoding}", "DATA")
                log(f"    Resolution: {config.Resolution.Width}x{config.Resolution.Height}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Stream URIs
        log("\n[Stream URIs]", "INFO")
        for profile in profiles:
            if not hasattr(profile, 'Name'):
                continue
            log(f"\n  Profile: {profile.Name}", "DATA")

            # RTSP Stream
            try:
                stream_setup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
                stream_uri = media.GetStreamUri({'StreamSetup': stream_setup, 'ProfileToken': profile.token})
                log(f"    RTSP: {stream_uri.Uri}", "DATA")
            except Exception as e:
                log(f"    RTSP Error: {e}", "WARNING")

            # Snapshot URI
            try:
                snapshot_uri = media.GetSnapshotUri({'ProfileToken': profile.token})
                log(f"    Snapshot: {snapshot_uri.Uri}", "DATA")
            except Exception as e:
                log(f"    Snapshot Error: {e}", "WARNING")

        return True

    except Exception as e:
        log(f"Failed to explore media service: {e}", "ERROR")
        return False

def explore_imaging_service(cam):
    """Explore Imaging service"""
    log("\n" + "="*60, "SECTION")
    log("IMAGING SERVICE", "SECTION")
    log("="*60, "SECTION")

    try:
        media = cam.create_media_service()
        imaging = cam.create_imaging_service()

        # Get video sources
        sources = media.GetVideoSources()

        for source in sources[:1]:  # Just first source
            log(f"\n[Video Source: {source.token}]", "INFO")

            # Current Settings
            log("\n  Current Imaging Settings:", "INFO")
            try:
                settings = imaging.GetImagingSettings({'VideoSourceToken': source.token})

                if hasattr(settings, 'Brightness'):
                    log(f"    Brightness: {settings.Brightness}", "DATA")
                if hasattr(settings, 'ColorSaturation'):
                    log(f"    Saturation: {settings.ColorSaturation}", "DATA")
                if hasattr(settings, 'Contrast'):
                    log(f"    Contrast: {settings.Contrast}", "DATA")
                if hasattr(settings, 'Sharpness'):
                    log(f"    Sharpness: {settings.Sharpness}", "DATA")

                if hasattr(settings, 'BacklightCompensation'):
                    blc = settings.BacklightCompensation
                    log(f"    Backlight Compensation: Mode={blc.Mode}, Level={blc.Level if hasattr(blc, 'Level') else 'N/A'}", "DATA")

                if hasattr(settings, 'Exposure'):
                    exp = settings.Exposure
                    log(f"    Exposure: Mode={exp.Mode}", "DATA")
                    if hasattr(exp, 'ExposureTime'):
                        log(f"      Time: {exp.ExposureTime}", "DATA")
                    if hasattr(exp, 'Gain'):
                        log(f"      Gain: {exp.Gain}", "DATA")
                    if hasattr(exp, 'Iris'):
                        log(f"      Iris: {exp.Iris}", "DATA")

                if hasattr(settings, 'Focus'):
                    focus = settings.Focus
                    log(f"    Focus: Mode={focus.AutoFocusMode if hasattr(focus, 'AutoFocusMode') else 'N/A'}", "DATA")

                if hasattr(settings, 'IrCutFilter'):
                    log(f"    IR Cut Filter: {settings.IrCutFilter}", "DATA")

                if hasattr(settings, 'WhiteBalance'):
                    wb = settings.WhiteBalance
                    log(f"    White Balance: Mode={wb.Mode}", "DATA")

                if hasattr(settings, 'WideDynamicRange'):
                    wdr = settings.WideDynamicRange
                    log(f"    WDR: Mode={wdr.Mode}, Level={wdr.Level if hasattr(wdr, 'Level') else 'N/A'}", "DATA")

            except Exception as e:
                log(f"    Error: {e}", "WARNING")

            # Available Options
            log("\n  Available Imaging Options:", "INFO")
            try:
                options = imaging.GetOptions({'VideoSourceToken': source.token})

                if hasattr(options, 'Brightness'):
                    log(f"    Brightness: {options.Brightness.Min} - {options.Brightness.Max}", "DATA")
                if hasattr(options, 'ColorSaturation'):
                    log(f"    Saturation: {options.ColorSaturation.Min} - {options.ColorSaturation.Max}", "DATA")
                if hasattr(options, 'Contrast'):
                    log(f"    Contrast: {options.Contrast.Min} - {options.Contrast.Max}", "DATA")
                if hasattr(options, 'Sharpness'):
                    log(f"    Sharpness: {options.Sharpness.Min} - {options.Sharpness.Max}", "DATA")

                if hasattr(options, 'BacklightCompensation'):
                    blc_opts = options.BacklightCompensation
                    log(f"    Backlight Compensation Modes: {blc_opts.Mode if hasattr(blc_opts, 'Mode') else 'N/A'}", "DATA")

                if hasattr(options, 'Exposure'):
                    exp_opts = options.Exposure
                    log(f"    Exposure Modes: {exp_opts.Mode if hasattr(exp_opts, 'Mode') else 'N/A'}", "DATA")

                if hasattr(options, 'Focus'):
                    focus_opts = options.Focus
                    log(f"    Focus Modes: {focus_opts.AutoFocusModes if hasattr(focus_opts, 'AutoFocusModes') else 'N/A'}", "DATA")

                if hasattr(options, 'IrCutFilterModes'):
                    log(f"    IR Cut Filter Modes: {options.IrCutFilterModes}", "DATA")

                if hasattr(options, 'WhiteBalance'):
                    wb_opts = options.WhiteBalance
                    log(f"    White Balance Modes: {wb_opts.Mode if hasattr(wb_opts, 'Mode') else 'N/A'}", "DATA")

            except Exception as e:
                log(f"    Error: {e}", "WARNING")

        return True

    except Exception as e:
        log(f"Failed to explore imaging service: {e}", "ERROR")
        return False

def explore_ptz_service(cam):
    """Explore PTZ service"""
    log("\n" + "="*60, "SECTION")
    log("PTZ SERVICE", "SECTION")
    log("="*60, "SECTION")

    try:
        ptz = cam.create_ptz_service()

        # PTZ Nodes
        log("\n[PTZ Nodes]", "INFO")
        try:
            nodes = ptz.GetNodes()
            for node in nodes:
                log(f"\n  Node: {node.Name} (Token: {node.token})", "DATA")
                log(f"    Fixed Home Position: {node.FixedHomePosition if hasattr(node, 'FixedHomePosition') else 'N/A'}", "DATA")

                if hasattr(node, 'SupportedPTZSpaces'):
                    spaces = node.SupportedPTZSpaces
                    if hasattr(spaces, 'AbsolutePanTiltPositionSpace'):
                        log(f"    Absolute Pan/Tilt: Supported", "DATA")
                    if hasattr(spaces, 'RelativePanTiltTranslationSpace'):
                        log(f"    Relative Pan/Tilt: Supported", "DATA")
                    if hasattr(spaces, 'ContinuousPanTiltVelocitySpace'):
                        log(f"    Continuous Pan/Tilt: Supported", "DATA")

                if hasattr(node, 'MaximumNumberOfPresets'):
                    log(f"    Max Presets: {node.MaximumNumberOfPresets}", "DATA")

                if hasattr(node, 'HomeSupported'):
                    log(f"    Home Position: {node.HomeSupported}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # PTZ Configurations
        log("\n[PTZ Configurations]", "INFO")
        try:
            configs = ptz.GetConfigurations()
            for config in configs:
                log(f"\n  Config: {config.Name} (Token: {config.token})", "DATA")
                log(f"    Node Token: {config.NodeToken}", "DATA")

                if hasattr(config, 'DefaultAbsolutePantTiltPositionSpace'):
                    log(f"    Default Absolute Space: {config.DefaultAbsolutePantTiltPositionSpace}", "DATA")
                if hasattr(config, 'DefaultRelativePanTiltTranslationSpace'):
                    log(f"    Default Relative Space: {config.DefaultRelativePanTiltTranslationSpace}", "DATA")
                if hasattr(config, 'DefaultContinuousPanTiltVelocitySpace'):
                    log(f"    Default Continuous Space: {config.DefaultContinuousPanTiltVelocitySpace}", "DATA")

                if hasattr(config, 'DefaultPTZSpeed'):
                    speed = config.DefaultPTZSpeed
                    if hasattr(speed, 'PanTilt'):
                        log(f"    Default Pan/Tilt Speed: x={speed.PanTilt.x}, y={speed.PanTilt.y}", "DATA")
                    if hasattr(speed, 'Zoom'):
                        log(f"    Default Zoom Speed: {speed.Zoom.x}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        # Get media profiles to check PTZ status
        media = cam.create_media_service()
        profiles = media.GetProfiles()

        for profile in profiles[:1]:  # Just first profile
            if hasattr(profile, 'PTZConfiguration'):
                log(f"\n[PTZ Status for Profile: {profile.Name}]", "INFO")
                try:
                    status = ptz.GetStatus({'ProfileToken': profile.token})

                    if hasattr(status, 'Position'):
                        pos = status.Position
                        if hasattr(pos, 'PanTilt'):
                            log(f"  Current Pan/Tilt: x={pos.PanTilt.x}, y={pos.PanTilt.y}", "DATA")
                        if hasattr(pos, 'Zoom'):
                            log(f"  Current Zoom: {pos.Zoom.x}", "DATA")

                    if hasattr(status, 'MoveStatus'):
                        ms = status.MoveStatus
                        if hasattr(ms, 'PanTilt'):
                            log(f"  Pan/Tilt Status: {ms.PanTilt}", "DATA")
                        if hasattr(ms, 'Zoom'):
                            log(f"  Zoom Status: {ms.Zoom}", "DATA")

                except Exception as e:
                    log(f"  Error: {e}", "WARNING")

                # Presets
                log("\n[PTZ Presets]", "INFO")
                try:
                    presets = ptz.GetPresets({'ProfileToken': profile.token})
                    if presets:
                        for preset in presets:
                            log(f"  Preset {preset.token}: {preset.Name if hasattr(preset, 'Name') else 'N/A'}", "DATA")
                    else:
                        log(f"  No presets configured", "DATA")
                except Exception as e:
                    log(f"  Error: {e}", "WARNING")

        return True

    except Exception as e:
        log(f"Failed to explore PTZ service: {e}", "ERROR")
        return False

def explore_analytics_service(cam):
    """Explore Analytics service if available"""
    log("\n" + "="*60, "SECTION")
    log("ANALYTICS SERVICE", "SECTION")
    log("="*60, "SECTION")

    try:
        analytics = cam.create_analytics_service()

        # Supported Analytics Modules
        log("\n[Supported Analytics Modules]", "INFO")
        try:
            modules = analytics.GetSupportedAnalyticsModules()
            for module in modules:
                log(f"  Module: {module.Name if hasattr(module, 'Name') else 'N/A'}", "DATA")
                log(f"    Type: {module.Type if hasattr(module, 'Type') else 'N/A'}", "DATA")
        except Exception as e:
            log(f"  Error or not supported: {e}", "WARNING")

        return True

    except Exception as e:
        log(f"Analytics service not available: {e}", "WARNING")
        return False

def explore_events_service(cam):
    """Explore Events service if available"""
    log("\n" + "="*60, "SECTION")
    log("EVENTS SERVICE", "SECTION")
    log("="*60, "SECTION")

    try:
        events = cam.create_events_service()

        # Event Properties
        log("\n[Event Properties]", "INFO")
        try:
            properties = events.GetEventProperties()

            if hasattr(properties, 'TopicSet'):
                log(f"  Available Topics:", "DATA")
                # Topics are complex, just show count
                log(f"    {len(properties.TopicSet) if properties.TopicSet else 0} topics available", "DATA")

            if hasattr(properties, 'TopicNamespaceLocation'):
                log(f"  Topic Namespace: {properties.TopicNamespaceLocation}", "DATA")
        except Exception as e:
            log(f"  Error: {e}", "WARNING")

        return True

    except Exception as e:
        log(f"Events service not available: {e}", "WARNING")
        return False

def main():
    parser = argparse.ArgumentParser(description='SAI-Cam ONVIF Capability Explorer')
    parser.add_argument('--host', help='Camera IP address')
    parser.add_argument('--port', type=int, default=8000, help='Camera port (default: 8000)')
    parser.add_argument('--user', help='Camera username')
    parser.add_argument('--password', help='Camera password')
    parser.add_argument('--config', help='Use camera from config file')
    parser.add_argument('--camera', help='Camera ID in config file')

    args = parser.parse_args()

    if not ONVIF_AVAILABLE:
        log("✗ onvif-zeep module not installed. Install with: pip3 install onvif-zeep", "ERROR")
        sys.exit(1)

    log(f"{Colors.BOLD}=== SAI-Cam ONVIF Capability Explorer ==={Colors.END}", "INFO")
    log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "INFO")

    # Determine camera credentials
    if args.config:
        try:
            with open(args.config, 'r') as f:
                config = yaml.safe_load(f)

            if not args.camera:
                log("✗ Must specify --camera when using --config", "ERROR")
                sys.exit(1)

            camera = next((c for c in config['cameras'] if c['id'] == args.camera), None)
            if not camera:
                log(f"✗ Camera {args.camera} not found in config", "ERROR")
                sys.exit(1)

            host = camera.get('address')
            port = camera.get('port', 8000)
            user = camera.get('username')
            password = camera.get('password')

        except Exception as e:
            log(f"✗ Failed to load config: {e}", "ERROR")
            sys.exit(1)
    elif args.host and args.user and args.password:
        host = args.host
        port = args.port
        user = args.user
        password = args.password
    else:
        log("✗ Must provide either --config or (--host, --user, --password)", "ERROR")
        parser.print_help()
        sys.exit(1)

    log(f"Connecting to {user}@{host}:{port}\n", "INFO")

    # Create ONVIF camera
    try:
        wsdl_dir = find_wsdl_dir()
        if wsdl_dir:
            cam = ONVIFCamera(host, port, user, password, wsdl_dir=wsdl_dir)
        else:
            cam = ONVIFCamera(host, port, user, password)

        # Explore all services
        explore_device_management(cam)
        explore_media_service(cam)
        explore_imaging_service(cam)
        explore_ptz_service(cam)
        explore_analytics_service(cam)
        explore_events_service(cam)

        log("\n" + "="*60, "SUCCESS")
        log(f"{Colors.GREEN}{Colors.BOLD}✓ Exploration Complete{Colors.END}", "SUCCESS")
        log("="*60, "SUCCESS")

    except Exception as e:
        log(f"\n✗ Exploration failed: {e}", "ERROR")
        import traceback
        log(traceback.format_exc(), "ERROR")
        sys.exit(1)

if __name__ == '__main__':
    main()
