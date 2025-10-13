#!/usr/bin/env python3
"""
SAI-Cam Local Diagnostic Test Suite
Comprehensive testing framework for SAI-Cam nodes

Usage:
    # Run all tests
    python3 scripts/diagnostic-suite.py

    # Run specific test
    python3 scripts/diagnostic-suite.py --test config

    # Verbose output
    python3 scripts/diagnostic-suite.py --verbose

    # Test with custom config
    python3 scripts/diagnostic-suite.py --config /path/to/config.yaml
"""

import argparse
import sys
import os
import yaml
import socket
import requests
import subprocess
from pathlib import Path
from datetime import datetime
import importlib.util

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

class TestResult:
    """Represents a test result"""
    def __init__(self, name, passed, message="", details=""):
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details
        self.timestamp = datetime.now()

    def __str__(self):
        status = f"{Colors.GREEN}✓ PASS{Colors.END}" if self.passed else f"{Colors.RED}✗ FAIL{Colors.END}"
        return f"{status} {self.name}: {self.message}"

class DiagnosticSuite:
    """Main diagnostic test suite"""

    def __init__(self, config_path=None, verbose=False):
        self.config_path = config_path or "/etc/sai-cam/config.yaml"
        self.verbose = verbose
        self.results = []
        self.config = None

        # Try to find project root
        self.project_root = Path(__file__).parent.parent

    def log(self, message, level="INFO"):
        """Log a message with color coding"""
        colors = {
            "INFO": Colors.BLUE,
            "SUCCESS": Colors.GREEN,
            "WARNING": Colors.YELLOW,
            "ERROR": Colors.RED,
            "HEADER": Colors.HEADER
        }
        color = colors.get(level, "")
        if self.verbose or level != "INFO":
            print(f"{color}{message}{Colors.END}")

    def add_result(self, result):
        """Add a test result"""
        self.results.append(result)
        print(result)
        if self.verbose and result.details:
            print(f"  {Colors.CYAN}Details: {result.details}{Colors.END}")

    def test_configuration(self):
        """Test configuration file validity"""
        self.log("\n=== Testing Configuration ===", "HEADER")

        # Check if config exists
        if not os.path.exists(self.config_path):
            self.add_result(TestResult(
                "Config File Exists",
                False,
                f"Config file not found at {self.config_path}"
            ))
            return False

        self.add_result(TestResult(
            "Config File Exists",
            True,
            f"Found at {self.config_path}"
        ))

        # Load and validate config
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)

            self.add_result(TestResult(
                "Config File Valid YAML",
                True,
                "Successfully parsed"
            ))
        except Exception as e:
            self.add_result(TestResult(
                "Config File Valid YAML",
                False,
                f"Parse error: {str(e)}"
            ))
            return False

        # Check required sections
        required_sections = ['cameras', 'storage', 'server', 'device']
        for section in required_sections:
            exists = section in self.config
            self.add_result(TestResult(
                f"Config Section '{section}'",
                exists,
                "Present" if exists else "Missing"
            ))

        # Validate cameras
        if 'cameras' in self.config:
            cam_count = len(self.config['cameras'])
            self.add_result(TestResult(
                "Camera Configuration",
                cam_count > 0,
                f"{cam_count} cameras configured",
                f"Camera IDs: {', '.join([c.get('id', 'unknown') for c in self.config['cameras']])}"
            ))

            # Check each camera config
            for cam in self.config['cameras']:
                cam_id = cam.get('id', 'unknown')
                required_fields = ['id', 'type', 'capture_interval']
                missing = [f for f in required_fields if f not in cam]

                if not missing:
                    self.add_result(TestResult(
                        f"Camera {cam_id} Config",
                        True,
                        f"All required fields present (type: {cam.get('type')})"
                    ))
                else:
                    self.add_result(TestResult(
                        f"Camera {cam_id} Config",
                        False,
                        f"Missing fields: {', '.join(missing)}"
                    ))

        return True

    def test_dependencies(self):
        """Test Python dependencies"""
        self.log("\n=== Testing Dependencies ===", "HEADER")

        required_modules = [
            ('yaml', 'PyYAML'),
            ('cv2', 'opencv-python'),
            ('requests', 'requests'),
            ('numpy', 'numpy'),
            ('psutil', 'psutil')
        ]

        optional_modules = [
            ('onvif', 'onvif-zeep'),
            ('systemd', 'systemd-python')
        ]

        for module_name, package_name in required_modules:
            try:
                importlib.import_module(module_name)
                self.add_result(TestResult(
                    f"Required Module '{package_name}'",
                    True,
                    "Installed"
                ))
            except ImportError:
                self.add_result(TestResult(
                    f"Required Module '{package_name}'",
                    False,
                    "Not installed"
                ))

        for module_name, package_name in optional_modules:
            try:
                importlib.import_module(module_name)
                self.add_result(TestResult(
                    f"Optional Module '{package_name}'",
                    True,
                    "Installed"
                ))
            except ImportError:
                self.add_result(TestResult(
                    f"Optional Module '{package_name}'",
                    True,
                    "Not installed (optional)",
                    "ONVIF cameras will not work without this"
                ))

    def test_network_connectivity(self):
        """Test network connectivity to cameras and server"""
        self.log("\n=== Testing Network Connectivity ===", "HEADER")

        if not self.config:
            self.log("Config not loaded, skipping network tests", "WARNING")
            return

        # Test camera connectivity
        if 'cameras' in self.config:
            for cam in self.config['cameras']:
                cam_id = cam.get('id', 'unknown')
                cam_type = cam.get('type', 'unknown')

                if cam_type in ['onvif', 'rtsp']:
                    address = cam.get('address')
                    port = cam.get('port', 554)

                    if address:
                        # Test ping
                        try:
                            result = subprocess.run(
                                ['ping', '-c', '1', '-W', '2', address],
                                capture_output=True,
                                timeout=3
                            )
                            ping_ok = result.returncode == 0
                        except:
                            ping_ok = False

                        self.add_result(TestResult(
                            f"Camera {cam_id} Ping",
                            ping_ok,
                            f"{address} {'reachable' if ping_ok else 'unreachable'}"
                        ))

                        # Test port
                        try:
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(2)
                            port_open = sock.connect_ex((address, port)) == 0
                            sock.close()
                        except:
                            port_open = False

                        self.add_result(TestResult(
                            f"Camera {cam_id} Port {port}",
                            port_open,
                            "Open" if port_open else "Closed/Filtered"
                        ))

        # Test server connectivity
        if 'server' in self.config:
            server_url = self.config['server'].get('url')
            if server_url:
                try:
                    response = requests.head(
                        server_url,
                        timeout=5,
                        verify=self.config['server'].get('ssl_verify', True)
                    )
                    server_ok = response.status_code < 500
                    self.add_result(TestResult(
                        "Server Connectivity",
                        server_ok,
                        f"{server_url} - Status: {response.status_code}",
                        f"Response time: {response.elapsed.total_seconds():.2f}s"
                    ))
                except requests.exceptions.RequestException as e:
                    self.add_result(TestResult(
                        "Server Connectivity",
                        False,
                        f"{server_url} - {type(e).__name__}",
                        str(e)
                    ))

    def test_storage(self):
        """Test storage paths and permissions"""
        self.log("\n=== Testing Storage ===", "HEADER")

        if not self.config:
            self.log("Config not loaded, skipping storage tests", "WARNING")
            return

        if 'storage' in self.config:
            base_path = self.config['storage'].get('base_path', '/opt/sai-cam/storage')

            # Check if path exists
            path_exists = os.path.exists(base_path)
            self.add_result(TestResult(
                "Storage Path Exists",
                path_exists,
                f"{base_path} {'exists' if path_exists else 'does not exist'}"
            ))

            if path_exists:
                # Check if writable
                writable = os.access(base_path, os.W_OK)
                self.add_result(TestResult(
                    "Storage Path Writable",
                    writable,
                    "Has write permissions" if writable else "No write permissions"
                ))

                # Check disk usage
                try:
                    stat = os.statvfs(base_path)
                    free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                    total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
                    used_percent = ((total_gb - free_gb) / total_gb) * 100

                    max_size_gb = self.config['storage'].get('max_size_gb', 5)

                    self.add_result(TestResult(
                        "Disk Space",
                        free_gb > 1,
                        f"{free_gb:.1f}GB free / {total_gb:.1f}GB total ({used_percent:.0f}% used)",
                        f"Configured max storage: {max_size_gb}GB"
                    ))

                    # Check actual storage usage
                    try:
                        result = subprocess.run(
                            ['du', '-sb', base_path],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        if result.returncode == 0:
                            bytes_used = int(result.stdout.split()[0])
                            gb_used = bytes_used / (1024**3)

                            # Count images
                            result = subprocess.run(
                                ['find', base_path, '-name', '*.jpg', '-type', 'f'],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )
                            image_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0

                            within_limit = gb_used <= max_size_gb
                            self.add_result(TestResult(
                                "Storage Usage",
                                within_limit,
                                f"{gb_used:.1f}GB used, {image_count} images",
                                f"Limit: {max_size_gb}GB - {'Within' if within_limit else 'EXCEEDS'} limit"
                            ))
                    except Exception as e:
                        self.log(f"Could not check storage usage: {e}", "WARNING")

                except Exception as e:
                    self.add_result(TestResult(
                        "Disk Space Check",
                        False,
                        f"Error: {str(e)}"
                    ))

        # Check log directory
        if 'logging' in self.config:
            log_dir = self.config['logging'].get('log_dir', '/var/log/sai-cam')

            log_exists = os.path.exists(log_dir)
            self.add_result(TestResult(
                "Log Directory Exists",
                log_exists,
                f"{log_dir} {'exists' if log_exists else 'does not exist'}"
            ))

            if log_exists:
                log_writable = os.access(log_dir, os.W_OK)
                self.add_result(TestResult(
                    "Log Directory Writable",
                    log_writable,
                    "Has write permissions" if log_writable else "No write permissions"
                ))

    def test_source_code(self):
        """Test source code availability and syntax"""
        self.log("\n=== Testing Source Code ===", "HEADER")

        required_files = [
            'src/camera_service.py',
            'src/cameras/base_camera.py',
            'src/cameras/camera_factory.py',
            'src/cameras/usb_camera.py',
            'src/cameras/rtsp_camera.py',
            'src/cameras/onvif_camera.py'
        ]

        for file_path in required_files:
            full_path = self.project_root / file_path
            exists = full_path.exists()

            self.add_result(TestResult(
                f"Source File {file_path}",
                exists,
                "Found" if exists else "Missing"
            ))

            # Check Python syntax
            if exists and file_path.endswith('.py'):
                try:
                    with open(full_path, 'r') as f:
                        compile(f.read(), file_path, 'exec')
                    self.add_result(TestResult(
                        f"Syntax {file_path}",
                        True,
                        "Valid Python syntax"
                    ))
                except SyntaxError as e:
                    self.add_result(TestResult(
                        f"Syntax {file_path}",
                        False,
                        f"Syntax error at line {e.lineno}"
                    ))

    def test_system_service(self):
        """Test systemd service configuration"""
        self.log("\n=== Testing System Service ===", "HEADER")

        service_file = '/etc/systemd/system/sai-cam.service'

        exists = os.path.exists(service_file)
        self.add_result(TestResult(
            "Service File Exists",
            exists,
            f"{service_file} {'found' if exists else 'not found'}"
        ))

        if exists:
            # Check if service is enabled
            try:
                result = subprocess.run(
                    ['systemctl', 'is-enabled', 'sai-cam'],
                    capture_output=True,
                    text=True
                )
                enabled = result.stdout.strip() == 'enabled'
                self.add_result(TestResult(
                    "Service Enabled",
                    enabled,
                    "Enabled" if enabled else "Not enabled"
                ))
            except:
                self.log("Could not check service status (requires systemd)", "WARNING")

            # Check if service is active
            try:
                result = subprocess.run(
                    ['systemctl', 'is-active', 'sai-cam'],
                    capture_output=True,
                    text=True
                )
                active = result.stdout.strip() == 'active'
                self.add_result(TestResult(
                    "Service Running",
                    active,
                    "Active" if active else "Not active"
                ))
            except:
                self.log("Could not check service status (requires systemd)", "WARNING")

    def run_all_tests(self):
        """Run all diagnostic tests"""
        self.log(f"\n{Colors.BOLD}=== SAI-Cam Diagnostic Suite ==={Colors.END}", "HEADER")
        self.log(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "INFO")

        # Run test suites
        self.test_configuration()
        self.test_dependencies()
        self.test_source_code()
        self.test_storage()
        self.test_network_connectivity()
        self.test_system_service()

        # Print summary
        self.print_summary()

    def run_specific_test(self, test_name):
        """Run a specific test"""
        test_map = {
            'config': self.test_configuration,
            'deps': self.test_dependencies,
            'network': self.test_network_connectivity,
            'storage': self.test_storage,
            'source': self.test_source_code,
            'service': self.test_system_service
        }

        if test_name in test_map:
            self.log(f"\n{Colors.BOLD}=== Running Test: {test_name} ==={Colors.END}", "HEADER")
            test_map[test_name]()
            self.print_summary()
        else:
            self.log(f"Unknown test: {test_name}", "ERROR")
            self.log(f"Available tests: {', '.join(test_map.keys())}", "INFO")

    def print_summary(self):
        """Print test summary"""
        self.log(f"\n{Colors.BOLD}=== Test Summary ==={Colors.END}", "HEADER")

        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        self.log(f"Total tests: {total}", "INFO")
        self.log(f"Passed: {passed}", "SUCCESS" if failed == 0 else "INFO")
        if failed > 0:
            self.log(f"Failed: {failed}", "ERROR")

        # List failed tests
        if failed > 0:
            self.log(f"\n{Colors.RED}Failed Tests:{Colors.END}", "ERROR")
            for result in self.results:
                if not result.passed:
                    self.log(f"  - {result.name}: {result.message}", "ERROR")

        # Overall status
        if failed == 0:
            self.log(f"\n{Colors.GREEN}{Colors.BOLD}✓ All tests passed!{Colors.END}", "SUCCESS")
            return 0
        else:
            self.log(f"\n{Colors.RED}{Colors.BOLD}✗ Some tests failed{Colors.END}", "ERROR")
            return 1

def main():
    parser = argparse.ArgumentParser(description='SAI-Cam Diagnostic Test Suite')
    parser.add_argument('--config', help='Path to config file')
    parser.add_argument('--test', help='Run specific test (config, deps, network, storage, source, service)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--version', action='version', version='SAI-Cam Diagnostics v1.0.0')

    args = parser.parse_args()

    suite = DiagnosticSuite(config_path=args.config, verbose=args.verbose)

    if args.test:
        suite.run_specific_test(args.test)
    else:
        suite.run_all_tests()

    sys.exit(suite.print_summary())

if __name__ == '__main__':
    main()
