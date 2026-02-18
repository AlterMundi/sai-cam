"""
Tests for the read_config_value bash function in scripts/install.sh.

These regression tests guard against a class of bug where a new key is added
to the call sites of read_config_value without adding a corresponding case to
the function's case statement — causing it to silently return the hardcoded
default regardless of the actual config file content.

Root cause documented: when network.mode was not in the case statement,
wifi-client nodes were always treated as ethernet nodes, causing eth0 to be
configured with ipv4.method=auto (DHCP) on a subnet with no DHCP server,
resulting in the connection cycling every ~90 seconds.
"""

import os
import re
import subprocess
import textwrap
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTALL_SH = os.path.join(REPO_ROOT, "scripts", "install.sh")


# ---------------------------------------------------------------------------
# Bash helper
# ---------------------------------------------------------------------------

def _extract_read_config_value_fn(install_sh_path: str) -> str:
    """
    Extract the read_config_value bash function body from install.sh.
    Returns the raw bash source as a string.
    """
    with open(install_sh_path) as f:
        source = f.read()

    # Match the function from its definition through the closing '}'
    # The function header is: read_config_value() {
    match = re.search(
        r"(^read_config_value\s*\(\s*\)\s*\{.*?^})",
        source,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise RuntimeError(
            "Could not find read_config_value() in install.sh — "
            "was the function renamed or removed?"
        )
    return match.group(1)


def read_config_value(config_yaml: str, key: str, default: str = "") -> str:
    """
    Call the real bash read_config_value function from install.sh with a
    temporary config file and return whatever the function prints.
    """
    fn_source = _extract_read_config_value_fn(INSTALL_SH)

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = os.path.join(tmpdir, "config")
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "config.yaml")
        with open(config_path, "w") as f:
            f.write(textwrap.dedent(config_yaml))

        script = textwrap.dedent(f"""\
            #!/bin/bash
            PROJECT_ROOT={tmpdir!r}
            {fn_source}
            read_config_value {key!r} {default!r}
        """)

        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, (
            f"bash exited {result.returncode}: {result.stderr}"
        )
        return result.stdout.strip()


# ---------------------------------------------------------------------------
# Fixtures — representative config files
# ---------------------------------------------------------------------------

ETHERNET_CONFIG = """\
network:
  node_ip: '192.168.220.5/24'
  interface: 'eth0'
  connection_name: 'saicam'
  mode: 'ethernet'
  gateway: '192.168.220.254'

system:
  user: 'admin'
  group: 'sai-cam'

device:
  id: 'sai-cam-node-05'
  location: 'TestLab'

cameras:
  - id: 'cam1'
    type: 'onvif'
    address: '192.168.220.10'
    password: 'camera-password'

wifi_ap:
  enabled: auto
  country_code: 'AR'
"""

WIFI_CLIENT_CONFIG = """\
network:
  node_ip: '192.168.220.1/24'
  interface: 'eth0'
  connection_name: 'saicam'
  mode: 'wifi-client'
  wifi_client:
    ssid: 'VodafoneNet'
    password: 'wifi-secret-99'
    wifi_iface: 'wlan0'

system:
  user: 'admin'
  group: 'sai-cam'

device:
  id: 'sai-cam-node-06'
  location: 'Quintana'

cameras:
  - id: 'cam1'
    type: 'onvif'
    address: '192.168.220.10'
    password: 'camera-password'

wifi_ap:
  enabled: false
  country_code: 'ES'
"""

MINIMAL_CONFIG = """\
network:
  node_ip: '192.168.220.1/24'

device:
  id: 'sai-cam-node-01'
"""


# ---------------------------------------------------------------------------
# RED-phase verification helper
# ---------------------------------------------------------------------------
#
# To confirm these tests genuinely catch the bug, temporarily remove one of
# the new case entries from read_config_value in install.sh (e.g. "network.mode")
# and re-run — the corresponding test below must FAIL.
#
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Core network keys (existed before wifi-client feature)
# ---------------------------------------------------------------------------

class TestNetworkCoreKeys:
    @pytest.mark.smoke
    def test_network_node_ip(self):
        assert read_config_value(ETHERNET_CONFIG, "network.node_ip") == "192.168.220.5/24"

    @pytest.mark.smoke
    def test_network_interface(self):
        assert read_config_value(ETHERNET_CONFIG, "network.interface") == "eth0"

    @pytest.mark.smoke
    def test_network_connection_name(self):
        assert read_config_value(ETHERNET_CONFIG, "network.connection_name") == "saicam"

    def test_network_node_ip_default_when_missing(self):
        assert read_config_value(MINIMAL_CONFIG, "network.node_ip", "192.168.220.1/24") == "192.168.220.1/24"


# ---------------------------------------------------------------------------
# network.mode — THE key that triggered the bug
# ---------------------------------------------------------------------------

class TestNetworkMode:
    @pytest.mark.smoke
    def test_reads_ethernet_mode(self):
        """network.mode must return 'ethernet' when configured as such."""
        assert read_config_value(ETHERNET_CONFIG, "network.mode", "ethernet") == "ethernet"

    @pytest.mark.smoke
    def test_reads_wifi_client_mode(self):
        """network.mode must return 'wifi-client' — this is the regression test.

        Before the fix, read_config_value had no case for 'network.mode', so
        this always returned the default 'ethernet' regardless of the config.
        That caused wifi-client nodes to be configured with ipv4.method=auto
        (DHCP) on eth0, resulting in connection cycling every ~90 seconds.
        """
        assert read_config_value(WIFI_CLIENT_CONFIG, "network.mode", "ethernet") == "wifi-client"

    def test_returns_default_when_mode_missing(self):
        """Missing mode key must return the default, not empty string."""
        assert read_config_value(MINIMAL_CONFIG, "network.mode", "ethernet") == "ethernet"

    def test_mode_not_confused_by_other_sections(self):
        """network.mode must not pick up mode: keys from unrelated sections."""
        config = """\
            wifi_ap:
              mode: 'shared'
              enabled: true
            network:
              node_ip: '192.168.220.1/24'
              mode: 'ethernet'
        """
        # Should return 'ethernet', not 'shared' from wifi_ap
        assert read_config_value(config, "network.mode", "ethernet") == "ethernet"


# ---------------------------------------------------------------------------
# network.gateway
# ---------------------------------------------------------------------------

class TestNetworkGateway:
    @pytest.mark.smoke
    def test_reads_gateway(self):
        assert read_config_value(ETHERNET_CONFIG, "network.gateway", "") == "192.168.220.254"

    def test_returns_empty_default_when_gateway_missing(self):
        assert read_config_value(WIFI_CLIENT_CONFIG, "network.gateway", "") == ""


# ---------------------------------------------------------------------------
# wifi_client keys — all required for wifi-client nodes
# ---------------------------------------------------------------------------

class TestWifiClientKeys:
    @pytest.mark.smoke
    def test_reads_wifi_client_ssid(self):
        assert read_config_value(WIFI_CLIENT_CONFIG, "network.wifi_client.ssid", "") == "VodafoneNet"

    @pytest.mark.smoke
    def test_reads_wifi_client_password(self):
        """wifi_client.password must NOT return camera passwords from cameras section."""
        result = read_config_value(WIFI_CLIENT_CONFIG, "network.wifi_client.password", "")
        assert result == "wifi-secret-99", (
            f"Got {result!r}. Likely picking up a camera password instead of "
            "the wifi_client password."
        )

    @pytest.mark.smoke
    def test_reads_wifi_client_wifi_iface(self):
        assert read_config_value(WIFI_CLIENT_CONFIG, "network.wifi_client.wifi_iface", "wlan0") == "wlan0"

    def test_ssid_empty_when_no_wifi_client_section(self):
        assert read_config_value(ETHERNET_CONFIG, "network.wifi_client.ssid", "") == ""

    def test_password_empty_when_no_wifi_client_section(self):
        assert read_config_value(ETHERNET_CONFIG, "network.wifi_client.password", "") == ""

    def test_wifi_iface_default_when_missing(self):
        assert read_config_value(ETHERNET_CONFIG, "network.wifi_client.wifi_iface", "wlan0") == "wlan0"

    def test_wifi_client_password_not_confused_with_camera_password(self):
        """Regression: camera passwords must not bleed into wifi_client.password."""
        config = """\
            network:
              mode: 'wifi-client'
              wifi_client:
                ssid: 'MyNet'
                password: 'wifi-pw'
                wifi_iface: 'wlan0'
            cameras:
              - id: cam1
                password: 'camera-pw-should-not-appear'
        """
        assert read_config_value(config, "network.wifi_client.password", "") == "wifi-pw"


# ---------------------------------------------------------------------------
# wifi_ap keys
# ---------------------------------------------------------------------------

class TestWifiApKeys:
    @pytest.mark.smoke
    def test_reads_wifi_ap_enabled_false(self):
        """wifi_ap.enabled: false must be returned, not the default 'auto'.

        Before the fix this had no case entry, so 'false' in config was ignored
        and the WiFi AP was always set up (and NetworkManager always restarted).
        """
        assert read_config_value(WIFI_CLIENT_CONFIG, "wifi_ap.enabled", "auto") == "false"

    @pytest.mark.smoke
    def test_reads_wifi_ap_enabled_auto(self):
        assert read_config_value(ETHERNET_CONFIG, "wifi_ap.enabled", "auto") == "auto"

    @pytest.mark.smoke
    def test_reads_wifi_ap_country_code(self):
        assert read_config_value(WIFI_CLIENT_CONFIG, "wifi_ap.country_code", "AR") == "ES"

    def test_wifi_ap_country_code_default_when_missing(self):
        assert read_config_value(MINIMAL_CONFIG, "wifi_ap.country_code", "AR") == "AR"

    def test_wifi_ap_enabled_default_when_missing(self):
        assert read_config_value(MINIMAL_CONFIG, "wifi_ap.enabled", "auto") == "auto"


# ---------------------------------------------------------------------------
# System / device keys (pre-existing, sanity checks)
# ---------------------------------------------------------------------------

class TestSystemAndDeviceKeys:
    @pytest.mark.smoke
    def test_reads_system_user(self):
        assert read_config_value(ETHERNET_CONFIG, "system.user", "admin") == "admin"

    @pytest.mark.smoke
    def test_reads_system_group(self):
        assert read_config_value(ETHERNET_CONFIG, "system.group", "admin") == "sai-cam"

    @pytest.mark.smoke
    def test_reads_device_id(self):
        assert read_config_value(ETHERNET_CONFIG, "device.id", "unknown") == "sai-cam-node-05"


# ---------------------------------------------------------------------------
# Completeness guard — every key used in install.sh must have a case entry
# ---------------------------------------------------------------------------

# All keys that install.sh reads via read_config_value.
# If a new call site is added without a case entry, this test catches it.
EXPECTED_KEYS = {
    "network.node_ip",
    "network.interface",
    "network.connection_name",
    "network.mode",
    "network.gateway",
    "network.wifi_client.ssid",
    "network.wifi_client.password",
    "network.wifi_client.wifi_iface",
    "wifi_ap.country_code",
    "wifi_ap.enabled",
    "system.user",
    "system.group",
    "device.id",
}


class TestCompletenessGuard:
    @pytest.mark.smoke
    def test_all_call_site_keys_have_case_entries(self):
        """Every key passed to read_config_value in install.sh must have a
        corresponding case entry in the function.

        This guards against the original bug: adding a new call site without
        adding the case, causing silent fallback to the default value.
        """
        with open(INSTALL_SH) as f:
            source = f.read()

        fn_source = _extract_read_config_value_fn(INSTALL_SH)

        # Keys actually used at call sites (outside the function definition)
        fn_start = source.index(fn_source)
        fn_end = fn_start + len(fn_source)
        code_without_fn = source[:fn_start] + source[fn_end:]

        call_site_keys = set(
            re.findall(r'read_config_value\s+"([^"]+)"', code_without_fn)
        )

        # Keys that have a case entry inside the function
        case_keys = set(re.findall(r'"([a-z_.]+)"\)', fn_source))

        missing_from_case = call_site_keys - case_keys
        assert not missing_from_case, (
            f"Keys used in read_config_value calls but missing from the case "
            f"statement: {sorted(missing_from_case)}\n\n"
            f"Add a case entry for each missing key in read_config_value() "
            f"in scripts/install.sh."
        )

    @pytest.mark.smoke
    def test_expected_keys_are_all_present(self):
        """The known set of expected keys must all have case entries.

        Update EXPECTED_KEYS in this test when adding new call sites.
        """
        fn_source = _extract_read_config_value_fn(INSTALL_SH)
        case_keys = set(re.findall(r'"([a-z_.]+)"\)', fn_source))

        missing = EXPECTED_KEYS - case_keys
        assert not missing, (
            f"Expected case entries missing from read_config_value: {sorted(missing)}"
        )
