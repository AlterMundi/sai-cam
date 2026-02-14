#!/bin/bash
set -e

# Default values
PRESERVE_CONFIG=false
PORTAL_ONLY=false
INSTALL_MONITORING=false

# Function to display help information
show_help() {
    cat << 'EOF'
SAI-CAM Installation Script
===========================

DESCRIPTION:
    This script installs and configures the SAI-CAM (Smart AI Camera) system
    on Linux systems.

USAGE:
    sudo ./install.sh [OPTIONS]

OPTIONS:
    -p, --preserve-config     Update ALL code files, preserve existing configuration.
                              Runs full installation pipeline (network, packages,
                              venv, services) but keeps /etc/sai-cam/config.yaml.
    --portal                  Update ONLY the web portal (status_portal.py and
                              portal/ web assets). Does NOT touch network, packages,
                              venv, camera service, config, nginx, or cron.
                              Requires SAI-CAM to be already fully installed.
                              Only restarts the sai-cam-portal service.
    --monitoring              Install vmagent metrics shipper alongside the main
                              service. Downloads vmagent binary, creates scrape
                              config, and registers a systemd service that pushes
                              Prometheus metrics to a remote VictoriaMetrics instance.
    -h, --help               Show this help message and exit

EXAMPLES:
    # Full installation (first time, requires sudo)
    sudo ./install.sh

    # Update ALL code and preserve production configuration
    sudo ./install.sh --preserve-config

    # Update ONLY the web portal (fast, safe for remote SSH)
    sudo ./install.sh --portal

    # Show help
    ./install.sh --help

REQUIREMENTS:
    - Ubuntu/Debian-based Linux distribution
    - Root privileges (sudo)
    - Network connectivity for package installation
    - Properly configured config/config.yaml file

WHAT THIS SCRIPT DOES:

Full Installation:
    1. Network Configuration:
       - Configures static IP and network interface (if specified in config.yaml)
       - Creates NetworkManager connection profile
       - Falls back to DHCP if network config is not provided

    2. System Setup:
       - Creates installation directories (/opt/sai-cam, /etc/sai-cam, /var/log/sai-cam)
       - Installs system packages (Python3, OpenCV, Nginx, etc.)
       - Sets up Python virtual environment with required packages

    3. Service Installation:
       - Copies camera service and configuration files
       - Installs systemd service (sai-cam)
       - Configures Nginx proxy for camera access
       - Sets up log rotation

    4. Service Activation:
       - Enables and starts systemd services
       - Configures automatic startup on boot

    NOTE: If a production config exists at /etc/sai-cam/config.yaml and differs
    from the repository config, you will be prompted to choose which to keep.

Code-Only Update (--preserve-config):
    1. Backs up existing files
    2. Updates all code files (camera_service.py, camera modules, etc.)
    3. Updates systemd service, nginx proxy, and logrotate configs
    4. Preserves existing /etc/sai-cam/config.yaml
    5. Restarts ALL services to apply code changes
    NOTE: This still runs the full pipeline (network, packages, venv, services).
    It only preserves the config file — everything else is updated.

Portal-Only Update (--portal):
    1. Verifies SAI-CAM is already fully installed
    2. Copies status_portal.py and portal/ web assets to /opt/sai-cam/
    3. Sets correct ownership and file permissions
    4. Restarts ONLY the sai-cam-portal service
    5. Does NOT touch: network, packages, venv, camera service, config,
       nginx, systemd templates, logrotate, WiFi AP, cron, or watchdog
    NOTE: This is the safest and fastest update mode. It will not drop
    SSH connections or disrupt camera capture. Use this when you have
    only changed the web portal code.

CONFIGURATION:
    Edit config/config.yaml before running this script. Key sections:

    network:           # Optional - for static IP configuration
      node_ip: '192.168.220.1/24'
      interface: 'eth0'
      connection_name: 'saicam'

    cameras:           # Required - define your cameras (up to 20 supported)
      - id: 'cam1'
        type: 'rtsp'   # or 'onvif'
        ...

    device:            # Required - node identification
      id: 'node-01'
      location: 'site-name'

    See config/config.yaml.example for complete configuration reference.

FILES CREATED/MODIFIED:
    /opt/sai-cam/              # Main installation directory
    /etc/sai-cam/config.yaml   # Service configuration
    /var/log/sai-cam/          # Log files
    /etc/systemd/system/sai-cam.service
    /etc/systemd/system/sai-cam-portal.service
    /etc/nginx/sites-available/portal-nginx.conf
    /etc/nginx/sites-available/camera-proxy
    /etc/logrotate.d/sai-cam

BACKUP LOCATION:
    Existing configurations are backed up to:
    /var/backups/sai-cam/YYYYMMDD_HHMMSS/

TROUBLESHOOTING:
    - Ensure you have sudo privileges
    - Check that all required files exist in the project directory
    - Verify network connectivity for package downloads
    - Review /var/log/sai-cam/camera_service.log for service issues

POST-INSTALLATION:
    Check service status:    sudo systemctl status sai-cam
    View logs:              sudo journalctl -u sai-cam -f
    Restart service:        sudo systemctl restart sai-cam
    Stop service:           sudo systemctl stop sai-cam

For more information, see the documentation in the docs/ directory.

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--preserve-config)
            PRESERVE_CONFIG=true
            shift
            ;;
        --portal)
            PORTAL_ONLY=true
            shift
            ;;
        --monitoring)
            INSTALL_MONITORING=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "❌ ERROR: Unknown option: $1"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo "Try '$0 --help' for more information."
            exit 1
            ;;
    esac
done

# Internal variables for system maintenance (not user-configurable)
INSTALL_DIR="/opt/sai-cam"
CONFIG_DIR="/etc/sai-cam"
LOG_DIR="/var/log/sai-cam"
BACKUP_DIR="/var/backups/sai-cam"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# System packages required for installation
SYSTEM_PACKAGES="python3-pip python3-opencv python3-venv libsystemd-dev nginx gettext-base"

# Default system user (can be overridden by config.yaml)
DEFAULT_USER="admin"
DEFAULT_GROUP="admin"

# Shared system group for all SAI-Cam components (portal, camera, updater)
# Enables the portal (admin) and self-update (root) to share state files and logs.
SAICAM_GROUP="sai-cam"

# Network configuration defaults (can be overridden by config.yaml)
DEFAULT_NODE_IP="192.168.220.1/24"
DEFAULT_INTERFACE="eth0"
DEFAULT_CONNECTION_NAME="saicam"

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Function to read YAML configuration values
read_config_value() {
    local key="$1"
    local config_file="$PROJECT_ROOT/config/config.yaml"
    local default_value="$2"
    
    if [ -f "$config_file" ]; then
        # Simple YAML parser for specific keys - handles quotes and comments
        case $key in
            "network.node_ip")
                grep -E "^\s*node_ip:" "$config_file" | sed 's/.*node_ip:\s*['\''\"]*\([^'\''\"#]*\)['\''\"#]*.*/\1/' | sed 's/[[:space:]]*$//'
                ;;
            "network.interface")
                grep -E "^\s*interface:" "$config_file" | head -1 | sed 's/.*interface:\s*['\''\"]*\([^'\''\"#]*\)['\''\"#]*.*/\1/' | sed 's/[[:space:]]*$//'
                ;;
            "network.connection_name")
                grep -E "^\s*connection_name:" "$config_file" | sed 's/.*connection_name:\s*['\''\"]*\([^'\''\"#]*\)['\''\"#]*.*/\1/' | sed 's/[[:space:]]*$//'
                ;;
            "system.user")
                grep -E "^\s*user:" "$config_file" | sed 's/.*user:\s*['\''\"]*\([^'\''\"#]*\)['\''\"#]*.*/\1/' | sed 's/[[:space:]]*$//'
                ;;
            "system.group")
                grep -E "^\s*group:" "$config_file" | sed 's/.*group:\s*['\''\"]*\([^'\''\"#]*\)['\''\"#]*.*/\1/' | sed 's/[[:space:]]*$//'
                ;;
            "device.id")
                grep -A 3 "^device:" "$config_file" | grep -E "^\s*id:" | sed 's/.*id:\s*['\''\"]*\([^'\''\"#]*\)['\''\"#]*.*/\1/' | sed 's/[[:space:]]*$//'
                ;;
            *)
                echo "$default_value"
                ;;
        esac
    else
        echo "$default_value"
    fi
}

# Function to merge missing config sections into production config.
# Ensures fleet, updates, portal, wifi_ap sections exist in production config.
# Auto-generates fleet.token if missing or empty.
# Uses config.yaml.example as the source of default section text (with comments).
# Idempotent: only appends sections that are missing.
merge_missing_config_sections() {
    local prod_config="$CONFIG_DIR/config.yaml"
    local example_config="$PROJECT_ROOT/config/config.yaml.example"
    local venv_python="$INSTALL_DIR/venv/bin/python3"

    if [ ! -f "$prod_config" ]; then
        echo "⚠️  No production config to merge into — skipping config merge"
        return 0
    fi

    if [ ! -f "$example_config" ]; then
        echo "⚠️  Example config not found at $example_config — skipping config merge"
        return 0
    fi

    # Use venv python (has PyYAML guaranteed) if available, else system python
    local PYTHON="$venv_python"
    if [ ! -x "$PYTHON" ]; then
        PYTHON="python3"
    fi

    echo "🔧 Checking production config for missing sections..."

    PROD_CONFIG="$prod_config" EXAMPLE_CONFIG="$example_config" \
    $PYTHON - << 'PYEOF'
import sys
import os

try:
    import yaml
except ImportError:
    print("   ⚠️  PyYAML not available — skipping config merge")
    sys.exit(0)

prod_path = os.environ.get("PROD_CONFIG", "")
example_path = os.environ.get("EXAMPLE_CONFIG", "")

if not prod_path or not example_path:
    print("   ⚠️  Config paths not set — skipping config merge")
    sys.exit(0)

# Parse production config
try:
    with open(prod_path, 'r') as f:
        prod_text = f.read()
    prod_config = yaml.safe_load(prod_text)
    if prod_config is None:
        prod_config = {}
except Exception as e:
    print(f"   ⚠️  Failed to parse production config: {e}")
    print("      Skipping config merge (config may have syntax issues)")
    sys.exit(0)

# Parse example config
try:
    with open(example_path, 'r') as f:
        example_text = f.read()
    example_config = yaml.safe_load(example_text)
    if example_config is None:
        example_config = {}
except Exception as e:
    print(f"   ⚠️  Failed to parse example config: {e}")
    sys.exit(0)

# Sections to check (in order they appear in example)
sections_to_check = ['portal', 'updates', 'fleet', 'wifi_ap']
missing_sections = [s for s in sections_to_check if s not in prod_config]

if not missing_sections:
    print("   ✅ All config sections present")
else:
    print(f"   Adding missing sections: {', '.join(missing_sections)}")

    # Ensure file ends with newline before appending
    if prod_text and not prod_text.endswith('\n'):
        prod_text += '\n'

    # Extract raw text blocks from example config for each missing section
    example_lines = example_text.split('\n')

    for section in missing_sections:
        block_lines = []
        in_section = False
        found_header = False  # True once we've seen the "section:" line
        section_pattern = f"{section}:"

        for i, line in enumerate(example_lines):
            if not in_section:
                # Capture comment lines that precede the section header
                if line.startswith('#') and i + 1 < len(example_lines):
                    for j in range(i + 1, min(i + 5, len(example_lines))):
                        if example_lines[j].strip() == '' or example_lines[j].startswith('#'):
                            continue
                        if example_lines[j].startswith(section_pattern):
                            in_section = True
                            block_lines.append(line)
                            break
                        break
                elif line.startswith(section_pattern):
                    in_section = True
                    found_header = True
                    block_lines.append(line)
            elif in_section:
                # The section key line itself (e.g. "portal:") comes right after comment
                if not found_header and line.startswith(section_pattern):
                    found_header = True
                    block_lines.append(line)
                    continue
                # End of section: next top-level key (non-indented, non-comment, non-empty)
                if line and not line[0].isspace() and not line.startswith('#'):
                    break
                block_lines.append(line)

        if block_lines:
            # Remove trailing empty lines and stray comments (belong to next section)
            while block_lines and (block_lines[-1].strip() == '' or block_lines[-1].startswith('#')):
                block_lines.pop()
            prod_text += '\n' + '\n'.join(block_lines) + '\n'
            print(f"   ✅ Appended '{section}' section from example config")
        else:
            print(f"   ⚠️  Could not extract '{section}' block from example config")

    # Write updated config
    try:
        with open(prod_path, 'w') as f:
            f.write(prod_text)
    except Exception as e:
        print(f"   ❌ Failed to write config: {e}")
        sys.exit(0)

# Check fleet.token — generate if missing or empty
try:
    with open(prod_path, 'r') as f:
        final_text = f.read()
    final_config = yaml.safe_load(final_text)
    if final_config is None:
        final_config = {}

    fleet = final_config.get('fleet') or {}
    token = fleet.get('token', '')
    if not token:
        import secrets, re
        new_token = secrets.token_urlsafe(32)
        # Replace empty token value — matches token: '' or token: "" or token:
        final_text = re.sub(
            r"^(\s*token:\s*)['\"]?['\"]?\s*(#.*)?$",
            rf"\g<1>'{new_token}'  \g<2>",
            final_text,
            count=1,
            flags=re.MULTILINE
        )
        with open(prod_path, 'w') as f:
            f.write(final_text)
        print(f"   🔑 Generated fleet token: {new_token[:8]}...")
    else:
        print(f"   🔑 Fleet token exists: {token[:8]}...")
except Exception as e:
    print(f"   ⚠️  Fleet token check failed: {e}")

PYEOF
}

# Function to generate camera proxy configuration
generate_camera_proxy_config() {
    local config_file="$PROJECT_ROOT/config/config.yaml"
    local proxy_file="/tmp/camera-proxy-generated"
    local port=8080
    
    echo "🔧 Generating camera proxy configuration from config.yaml..."
    
    # Start with empty config
    > "$proxy_file"
    
    if [ -f "$config_file" ]; then
        # Extract camera IPs from config.yaml
        # Look for cameras section and extract IP addresses
        local in_cameras=false
        local camera_count=0
        
        while IFS= read -r line; do
            # Check if we're entering cameras section
            if [[ "$line" =~ ^cameras: ]]; then
                in_cameras=true
                continue
            fi
            
            # Check if we're leaving cameras section (new top-level key)
            if [[ "$in_cameras" == true && "$line" =~ ^[a-zA-Z] ]]; then
                in_cameras=false
                break
            fi
            
            # Extract IP addresses from camera entries (using 'address:' field)
            if [[ "$in_cameras" == true && "$line" =~ address:.*[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+ ]]; then
                local camera_ip=$(echo "$line" | sed 's/.*address:\s*['\''\"]*\([0-9.]*\)['\''\"#]*.*/\1/' | sed 's/[[:space:]]*$//')
                
                if [[ -n "$camera_ip" && "$camera_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                    echo "📹 Found camera IP: $camera_ip -> proxy port $port"
                    
                    # Generate nginx server block for this camera
                    cat >> "$proxy_file" << EOF
server {
    listen $port;
    location / {
        proxy_pass http://$camera_ip:80;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}

EOF
                    
                    port=$((port + 1))
                    camera_count=$((camera_count + 1))
                fi
            fi
        done < "$config_file"
        
        if [ $camera_count -gt 0 ]; then
            echo "✅ Generated proxy configuration for $camera_count cameras (ports 8080-$((port-1)))"
            # Copy generated config to destination
            sudo cp "$proxy_file" "/etc/nginx/sites-available/camera-proxy"
            rm -f "$proxy_file"
        else
            echo "⚠️  No camera IPs found in config.yaml, using static proxy configuration"
            sudo cp "$PROJECT_ROOT/config/camera-proxy" "/etc/nginx/sites-available/camera-proxy"
        fi
    else
        echo "⚠️  Config file not found, using static proxy configuration"
        sudo cp "$PROJECT_ROOT/config/camera-proxy" "/etc/nginx/sites-available/camera-proxy"
    fi
}

# Load configuration values
NODE_IP=$(read_config_value "network.node_ip" "$DEFAULT_NODE_IP")
INTERFACE=$(read_config_value "network.interface" "$DEFAULT_INTERFACE")
CONNECTION_NAME=$(read_config_value "network.connection_name" "$DEFAULT_CONNECTION_NAME")
NETWORK_MODE=$(read_config_value "network.mode" "ethernet")
NETWORK_GATEWAY=$(read_config_value "network.gateway" "")
WIFI_CLIENT_SSID=$(read_config_value "network.wifi_client.ssid" "")
WIFI_CLIENT_PASSWORD=$(read_config_value "network.wifi_client.password" "")
WIFI_CLIENT_INTERFACE=$(read_config_value "network.wifi_client.wifi_iface" "wlan0")
WIFI_COUNTRY_CODE=$(read_config_value "wifi_ap.country_code" "AR")
SYSTEM_USER=$(read_config_value "system.user" "$DEFAULT_USER")
SYSTEM_GROUP=$(read_config_value "system.group" "$DEFAULT_GROUP")

# Load AP network settings from .env (with defaults)
if [ -f "$PROJECT_ROOT/.env" ]; then
    AP_IP=$(grep "^AP_IP=" "$PROJECT_ROOT/.env" | cut -d'=' -f2)
    AP_NETMASK=$(grep "^AP_NETMASK=" "$PROJECT_ROOT/.env" | cut -d'=' -f2)
    DHCP_RANGE_START=$(grep "^DHCP_RANGE_START=" "$PROJECT_ROOT/.env" | cut -d'=' -f2)
    DHCP_RANGE_END=$(grep "^DHCP_RANGE_END=" "$PROJECT_ROOT/.env" | cut -d'=' -f2)
fi
AP_IP=${AP_IP:-192.168.230.1}
AP_NETMASK=${AP_NETMASK:-24}
DHCP_RANGE_START=${DHCP_RANGE_START:-192.168.230.100}
DHCP_RANGE_END=${DHCP_RANGE_END:-192.168.230.125}

# Function to check if required files exist
check_required_files() {
    local required_files=()

    if [ "$PRESERVE_CONFIG" = true ]; then
        # For preserve-config mode, we need code files but not config
        required_files=(
            "$PROJECT_ROOT/src/camera_service.py"
            "$PROJECT_ROOT/config/camera-proxy"
            "$PROJECT_ROOT/systemd/sai-cam.service.template"
            "$PROJECT_ROOT/systemd/sai-cam-portal.service.template"
            "$PROJECT_ROOT/systemd/logrotate.conf"
            "$PROJECT_ROOT/requirements.txt"
        )
    else
        # Full installation requires everything
        required_files=(
            "$PROJECT_ROOT/src/camera_service.py"
            "$PROJECT_ROOT/config/config.yaml"
            "$PROJECT_ROOT/config/camera-proxy"
            "$PROJECT_ROOT/systemd/sai-cam.service.template"
            "$PROJECT_ROOT/systemd/sai-cam-portal.service.template"
            "$PROJECT_ROOT/systemd/logrotate.conf"
            "$PROJECT_ROOT/requirements.txt"
        )
    fi

    local missing_files=0
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            echo "❌ ERROR: Required file not found: $file"
            missing_files=1
        else
            echo "✅ Found: $(basename "$file")"
        fi
    done

    if [ $missing_files -eq 1 ]; then
        echo ""
        echo "❌ Installation aborted due to missing files"
        echo "   Please ensure you're running this script from the SAI-CAM project directory"
        echo "   and that all required files are present."
        exit 1
    fi

    echo "✅ All required files found"
}

# Function to validate config.yaml structure and required fields
validate_config() {
    local config_file="$PROJECT_ROOT/config/config.yaml"

    # Skip validation in preserve-config mode (we're not using repo config)
    if [ "$PRESERVE_CONFIG" = true ]; then
        echo "ℹ️  Config validation skipped (--preserve-config mode)"
        return 0
    fi

    echo "🔍 Validating configuration..."

    # Use Python to validate YAML syntax and required fields
    python3 << EOF
import sys
import yaml

config_file = "$config_file"
errors = []

try:
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
except yaml.YAMLError as e:
    print(f"❌ YAML syntax error: {e}")
    sys.exit(1)
except FileNotFoundError:
    print(f"❌ Config file not found: {config_file}")
    sys.exit(1)

# Check required fields
if not config:
    errors.append("Config file is empty")
else:
    # Check device.id
    if 'device' not in config or not config.get('device', {}).get('id'):
        errors.append("Missing required field: device.id")

    # Check cameras array
    cameras = config.get('cameras', [])
    if not cameras:
        errors.append("No cameras defined (cameras array is empty)")
    else:
        print(f"   ✓ Found {len(cameras)} camera(s) configured")

    # Check server.url
    if 'server' not in config or not config.get('server', {}).get('url'):
        errors.append("Missing required field: server.url")

    # Print device info if available
    device_id = config.get('device', {}).get('id', 'unknown')
    location = config.get('device', {}).get('location', 'unknown')
    print(f"   ✓ Device: {device_id} @ {location}")

if errors:
    print("")
    for error in errors:
        print(f"❌ {error}")
    print("")
    print("Please fix config/config.yaml before running install.")
    sys.exit(1)
else:
    print("✅ Configuration is valid")
    sys.exit(0)
EOF

    if [ $? -ne 0 ]; then
        echo ""
        echo "❌ Installation aborted due to configuration errors"
        exit 1
    fi
}

# Function to backup existing config
backup_existing_config() {
    if [ -d "$CONFIG_DIR" ] || [ -f "/etc/systemd/system/sai-cam.service" ] || [ -f "/etc/logrotate.d/sai-cam" ]; then
        echo "📦 Creating backup of existing installation..."
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/config"
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/systemd"
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/logrotate"

        # Backup configs if they exist
        if [ -d "$CONFIG_DIR" ] && [ "$(ls -A $CONFIG_DIR 2>/dev/null)" ]; then
            sudo cp -r "$CONFIG_DIR"/* "$BACKUP_DIR/$TIMESTAMP/config/" 2>/dev/null || true
            echo "✅ Configuration backup created at: $BACKUP_DIR/$TIMESTAMP/config/"
        fi

        # Backup systemd service file if it exists
        if [ -f "/etc/systemd/system/sai-cam.service" ]; then
            sudo cp "/etc/systemd/system/sai-cam.service" "$BACKUP_DIR/$TIMESTAMP/systemd/"
            echo "✅ Service file backup created: sai-cam.service"
        fi

        # Backup logrotate config if it exists
        if [ -f "/etc/logrotate.d/sai-cam" ]; then
            sudo cp "/etc/logrotate.d/sai-cam" "$BACKUP_DIR/$TIMESTAMP/logrotate/"
            echo "✅ Logrotate config backup created: sai-cam"
        fi

        # Backup existing code if preserve-config mode
        if [ "$PRESERVE_CONFIG" = true ] && [ -d "$INSTALL_DIR/bin" ]; then
            sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/code"
            sudo cp -r "$INSTALL_DIR/bin" "$BACKUP_DIR/$TIMESTAMP/code/" 2>/dev/null || true
            sudo cp -r "$INSTALL_DIR/cameras" "$BACKUP_DIR/$TIMESTAMP/code/" 2>/dev/null || true
            echo "✅ Code backup created at: $BACKUP_DIR/$TIMESTAMP/code/"
        fi
        
        echo "💾 Complete backup location: $BACKUP_DIR/$TIMESTAMP/"
    else
        echo "ℹ️  No existing configuration found - fresh installation"
    fi
}
# Verify we're running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "❌ ERROR: This script must be run with sudo privileges"
    echo "Usage: sudo $0 [OPTIONS]"
    echo "Try '$0 --help' for more information."
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
# Fast path: portal-only update (--portal)
#
# This mode ONLY updates the status portal web interface files and restarts
# the sai-cam-portal systemd service. It is designed for rapid iteration on
# the portal UI/backend without touching any other part of the system.
#
# What this mode DOES:
#   - Copies src/status_portal.py → /opt/sai-cam/status_portal.py
#   - Copies src/portal/* → /opt/sai-cam/portal/
#   - Sets correct ownership and permissions on copied files
#   - Restarts ONLY the sai-cam-portal service
#   - Verifies the portal service is running after restart
#
# What this mode does NOT do:
#   - Does NOT reconfigure the network (no NetworkManager changes)
#   - Does NOT install or update system packages (no apt-get)
#   - Does NOT create or modify the Python virtual environment
#   - Does NOT touch the camera service (sai-cam.service is left as-is)
#   - Does NOT copy camera_service.py, cameras/, config_helper.py, logging_utils.py
#   - Does NOT update or overwrite /etc/sai-cam/config.yaml
#   - Does NOT modify systemd service templates or logrotate configs
#   - Does NOT configure Nginx, WiFi AP, sudoers, cron jobs, or watchdog
#   - Does NOT create backups (no files outside portal scope are touched)
#
# Prerequisites:
#   - SAI-CAM must already be fully installed (run install.sh first)
#   - The sai-cam-portal systemd service must already be registered
#   - /opt/sai-cam/ directory must exist with correct structure
# ══════════════════════════════════════════════════════════════════════════════
if [ "$PORTAL_ONLY" = true ]; then
    echo ""
    echo "🌐 SAI-CAM Portal-Only Update"
    echo "════════════════════════════════════════════════════════"
    echo "  Mode:   --portal (fast path — portal files only)"
    echo "  Scope:  status_portal.py + portal/ web assets"
    echo "  Target: $INSTALL_DIR/"
    echo "════════════════════════════════════════════════════════"
    echo ""

    # ── Pre-flight checks ────────────────────────────────────────────────────
    echo "🔍 Running pre-flight checks..."
    PREFLIGHT_FAILED=false

    # 1. Verify SAI-CAM is already installed
    if [ ! -d "$INSTALL_DIR" ]; then
        echo "   ❌ Installation directory not found: $INSTALL_DIR"
        echo "      SAI-CAM must be fully installed before using --portal."
        echo "      Run: sudo ./install.sh"
        PREFLIGHT_FAILED=true
    else
        echo "   ✅ Installation directory exists: $INSTALL_DIR"
    fi

    # 2. Verify src directory exists in installation
    if [ ! -d "$INSTALL_DIR/src" ]; then
        echo "   ❌ Source directory not found: $INSTALL_DIR/src/"
        echo "      SAI-CAM must be fully installed before using --portal."
        echo "      Run: sudo ./install.sh"
        PREFLIGHT_FAILED=true
    else
        echo "   ✅ Source directory exists: $INSTALL_DIR/src/"
    fi

    # 3. Verify the portal systemd service is registered
    if ! systemctl list-unit-files sai-cam-portal.service >/dev/null 2>&1; then
        echo "   ❌ sai-cam-portal.service is not registered with systemd"
        echo "      SAI-CAM must be fully installed before using --portal."
        echo "      Run: sudo ./install.sh"
        PREFLIGHT_FAILED=true
    else
        echo "   ✅ sai-cam-portal.service is registered"
    fi

    # 4. Verify source files exist in the repository
    if [ ! -f "$PROJECT_ROOT/src/status_portal.py" ]; then
        echo "   ❌ Source file not found: src/status_portal.py"
        PREFLIGHT_FAILED=true
    else
        echo "   ✅ Source: src/status_portal.py"
    fi

    if [ ! -d "$PROJECT_ROOT/src/portal" ]; then
        echo "   ❌ Source directory not found: src/portal/"
        PREFLIGHT_FAILED=true
    else
        PORTAL_FILE_COUNT=$(find "$PROJECT_ROOT/src/portal" -type f | wc -l)
        echo "   ✅ Source: src/portal/ ($PORTAL_FILE_COUNT files)"
    fi

    # 5. Verify system user/group exist
    if ! id "$SYSTEM_USER" >/dev/null 2>&1; then
        echo "   ❌ System user not found: $SYSTEM_USER"
        echo "      SAI-CAM must be fully installed before using --portal."
        PREFLIGHT_FAILED=true
    else
        echo "   ✅ System user exists: $SYSTEM_USER"
    fi

    # Abort if any pre-flight check failed
    if [ "$PREFLIGHT_FAILED" = true ]; then
        echo ""
        echo "❌ Portal update aborted: pre-flight checks failed."
        echo ""
        echo "   The --portal flag is ONLY for updating the web portal on an"
        echo "   already-installed SAI-CAM system. For first-time installation"
        echo "   or full updates, use:"
        echo ""
        echo "     sudo ./install.sh                  # Full installation"
        echo "     sudo ./install.sh --preserve-config # Code update (all components)"
        echo ""
        exit 1
    fi

    echo ""
    echo "   All pre-flight checks passed."
    echo ""

    # ── Copy portal files ────────────────────────────────────────────────────
    echo "📄 Copying portal files..."

    echo "   status_portal.py → $INSTALL_DIR/src/status_portal.py"
    sudo cp "$PROJECT_ROOT/src/status_portal.py" "$INSTALL_DIR/src/status_portal.py"

    echo "   update_manager.py → $INSTALL_DIR/src/update_manager.py"
    sudo cp "$PROJECT_ROOT/src/update_manager.py" "$INSTALL_DIR/src/update_manager.py"

    echo "   src/portal/* → $INSTALL_DIR/src/portal/"
    sudo mkdir -p "$INSTALL_DIR/src/portal"
    sudo cp -r "$PROJECT_ROOT/src/portal/"* "$INSTALL_DIR/src/portal/"

    # ── Set ownership and permissions ────────────────────────────────────────
    echo "🔐 Setting ownership and permissions..."
    sudo chown "$SYSTEM_USER:$SYSTEM_GROUP" "$INSTALL_DIR/src/status_portal.py"
    sudo chown "$SYSTEM_USER:$SYSTEM_GROUP" "$INSTALL_DIR/src/update_manager.py"
    sudo chown -R "$SYSTEM_USER:$SYSTEM_GROUP" "$INSTALL_DIR/src/portal"
    sudo chmod 755 "$INSTALL_DIR/src/status_portal.py"
    sudo chmod 644 "$INSTALL_DIR/src/update_manager.py"
    sudo find "$INSTALL_DIR/src/portal" -type f -exec chmod 644 {} \;
    sudo find "$INSTALL_DIR/src/portal" -type d -exec chmod 755 {} \;
    echo "   ✅ Ownership: $SYSTEM_USER:$SYSTEM_GROUP"
    echo "   ✅ Permissions: 755 (portal.py), 644 (assets), 755 (dirs)"

    # ── Restart portal service only ──────────────────────────────────────────
    echo "🔄 Restarting sai-cam-portal service..."
    echo "   (sai-cam camera service is NOT being restarted)"
    if sudo systemctl restart sai-cam-portal; then
        sleep 1
        if systemctl is-active --quiet sai-cam-portal; then
            echo "   ✅ sai-cam-portal is running"
        else
            echo "   ⚠️  sai-cam-portal was restarted but is not active"
            echo "      Check logs: sudo journalctl -u sai-cam-portal -n 20"
        fi
    else
        echo "   ❌ Failed to restart sai-cam-portal"
        echo "      Check logs: sudo journalctl -u sai-cam-portal -n 20"
        exit 1
    fi

    # ── Summary ──────────────────────────────────────────────────────────────
    echo ""
    echo "════════════════════════════════════════════════════════"
    echo "✅ Portal update complete"
    echo ""
    echo "   Updated files:"
    echo "     • $INSTALL_DIR/src/status_portal.py"
    echo "     • $INSTALL_DIR/src/portal/ ($PORTAL_FILE_COUNT files)"
    echo ""
    echo "   Services restarted:"
    echo "     • sai-cam-portal  ✅"
    echo "     • sai-cam         (not touched)"
    echo "     • nginx           (not touched)"
    echo ""
    echo "   Access portal: http://$(hostname -I 2>/dev/null | awk '{print $1}')/"
    echo "════════════════════════════════════════════════════════"
    exit 0
fi

echo "🚀 SAI-CAM Installation Script"
echo "=============================="

# Check for required files before proceeding
echo "📋 Checking for required files..."
check_required_files

# Validate config.yaml if possible (requires python3 + pyyaml)
if python3 -c "import yaml" 2>/dev/null; then
    validate_config
else
    echo "⚠️  Config validation skipped (PyYAML not installed yet)"
    echo "   Config will be validated after Python packages are installed"
fi

# Create backup of existing installation
echo "💾 Checking for existing configuration..."
backup_existing_config

echo "🔧 Starting SAI-CAM installation..."
echo "========================================"

# Network configuration from config.yaml:
echo ""
echo "🌐 Network Configuration"
echo "------------------------"
echo "Mode:       ${NETWORK_MODE:-'ethernet'}"
echo "Connection: ${CONNECTION_NAME:-'(not specified)'}"
echo "Interface:  ${INTERFACE:-'(not specified)'}"
echo "IP Address: ${NODE_IP:-'(not specified)'}"

# Configure WiFi regulatory domain (required before any WiFi operations)
echo "📡 Setting WiFi regulatory domain to $WIFI_COUNTRY_CODE..."
# On Raspberry Pi OS, use raspi-config (required to unblock WiFi on fresh installs)
if command -v raspi-config &> /dev/null; then
    sudo raspi-config nonint do_wifi_country "$WIFI_COUNTRY_CODE" 2>/dev/null || true
else
    sudo iw reg set "$WIFI_COUNTRY_CODE" 2>/dev/null || true
    # Persist regulatory domain on non-RPi systems
    if [ -f /etc/default/crda ]; then
        sudo sed -i "s/^REGDOMAIN=.*/REGDOMAIN=$WIFI_COUNTRY_CODE/" /etc/default/crda 2>/dev/null || true
    fi
fi

# Unblock WiFi radio (required on fresh installations)
echo "📡 Unblocking WiFi radio..."
sudo rfkill unblock wifi 2>/dev/null || true

# Only configure network if values are provided and non-empty
if [ -n "$CONNECTION_NAME" ] && [ -n "$INTERFACE" ] && [ -n "$NODE_IP" ]; then
    echo "⚙️  Setting up network connection..."

    # Check if connection already exists and delete it
    if nmcli con show "$CONNECTION_NAME" >/dev/null 2>&1; then
        echo "🗑️  Removing existing connection: $CONNECTION_NAME"
        sudo nmcli con delete "$CONNECTION_NAME"
    fi

    if [ "$NETWORK_MODE" = "wifi-client" ]; then
        # WiFi-client mode: Ethernet is static only (for cameras), WiFi provides internet
        echo "🔧 Creating ethernet connection with static IP (wifi-client mode)..."
        sudo nmcli con add con-name "$CONNECTION_NAME" ifname "$INTERFACE" type ethernet \
            ipv4.method manual ipv4.addresses "$NODE_IP"

        # Configure WiFi client for internet access
        if [ -n "$WIFI_CLIENT_SSID" ] && [ -n "$WIFI_CLIENT_PASSWORD" ]; then
            echo "📶 Configuring WiFi client connection..."
            # Remove existing WiFi client connection if exists
            if nmcli con show "sai-cam-wifi" >/dev/null 2>&1; then
                sudo nmcli con delete "sai-cam-wifi"
            fi
            sudo nmcli con add con-name "sai-cam-wifi" type wifi ifname "$WIFI_CLIENT_INTERFACE" \
                ssid "$WIFI_CLIENT_SSID" \
                wifi-sec.key-mgmt wpa-psk \
                wifi-sec.psk "$WIFI_CLIENT_PASSWORD" \
                connection.autoconnect yes \
                connection.autoconnect-priority 100
            echo "🔌 Activating WiFi client connection..."
            sudo nmcli con up "sai-cam-wifi" || echo "⚠️  WiFi connection created but failed to activate (may need manual intervention)"
        else
            echo "⚠️  WiFi client mode selected but no SSID/password configured"
            echo "   Configure wifi_client.ssid and wifi_client.password in config.yaml"
        fi
    else
        # Ethernet mode: Ethernet provides internet via DHCP (or static gateway if specified)
        if [ -n "$NETWORK_GATEWAY" ]; then
            # Static configuration with gateway
            echo "🔧 Creating ethernet connection with static IP and gateway..."
            sudo nmcli con add con-name "$CONNECTION_NAME" ifname "$INTERFACE" type ethernet \
                ipv4.method manual ipv4.addresses "$NODE_IP" ipv4.gateway "$NETWORK_GATEWAY"
        else
            # DHCP with additional static IP
            echo "🔧 Creating ethernet connection with DHCP + static IP..."
            sudo nmcli con add con-name "$CONNECTION_NAME" ifname "$INTERFACE" type ethernet \
                ipv4.method auto ipv4.addresses "$NODE_IP"
        fi
    fi

    echo "🔌 Activating ethernet connection..."
    sudo nmcli con up "$CONNECTION_NAME"

    echo "✅ Network configuration completed successfully"
else
    echo "⚠️  Network configuration skipped"
    echo "   Reason: Missing network settings in config.yaml"
    echo "   The system will use default network configuration"
fi

# Create shared system group
echo ""
echo "👥 Setting Up System Group"
echo "--------------------------"
if getent group "$SAICAM_GROUP" > /dev/null 2>&1; then
    echo "✅ Group '$SAICAM_GROUP' already exists"
else
    sudo groupadd --system "$SAICAM_GROUP"
    echo "✅ Created system group: $SAICAM_GROUP"
fi
# Ensure service user and root are both members
if ! id -nG "$SYSTEM_USER" 2>/dev/null | grep -qw "$SAICAM_GROUP"; then
    sudo usermod -aG "$SAICAM_GROUP" "$SYSTEM_USER"
    echo "✅ Added $SYSTEM_USER to $SAICAM_GROUP group"
else
    echo "✅ $SYSTEM_USER already in $SAICAM_GROUP group"
fi
if ! id -nG root 2>/dev/null | grep -qw "$SAICAM_GROUP"; then
    sudo usermod -aG "$SAICAM_GROUP" root
    echo "✅ Added root to $SAICAM_GROUP group"
else
    echo "✅ root already in $SAICAM_GROUP group"
fi

# Create directories
echo ""
echo "📁 Creating System Directories"
echo "------------------------------"
echo "🔧 Creating installation directories..."
sudo mkdir -p $INSTALL_DIR/bin
sudo mkdir -p $INSTALL_DIR/storage
sudo mkdir -p $CONFIG_DIR
sudo mkdir -p $LOG_DIR
sudo mkdir -p /var/lib/sai-cam

# Shared directories: setgid so new files inherit the group
sudo chown root:$SAICAM_GROUP /var/lib/sai-cam
sudo chmod 2775 /var/lib/sai-cam
sudo chown root:$SAICAM_GROUP $LOG_DIR
sudo chmod 2775 $LOG_DIR

echo "✅ Directories created successfully"
echo "   /var/lib/sai-cam  → root:$SAICAM_GROUP (setgid)"
echo "   $LOG_DIR → root:$SAICAM_GROUP (setgid)"

# Install system dependencies
echo ""
echo "📦 Installing System Dependencies"
echo "---------------------------------"
echo "🔄 Updating package repositories..."
sudo apt-get update > /dev/null 2>&1

echo "📥 Installing required packages: $SYSTEM_PACKAGES"
sudo apt-get install -y $SYSTEM_PACKAGES
echo "✅ System dependencies installed successfully"

# Set up virtual environment
echo ""
echo "🐍 Setting Up Python Environment"
echo "--------------------------------"
echo "🔧 Creating Python virtual environment..."
if ! python3 -m venv $INSTALL_DIR/venv; then
    echo "❌ ERROR: Failed to create Python virtual environment"
    exit 1
fi

if [ ! -f "$INSTALL_DIR/venv/bin/activate" ]; then
    echo "❌ ERROR: Virtual environment creation failed - activate script not found"
    exit 1
fi

echo "📥 Installing Python packages..."
if ! $INSTALL_DIR/venv/bin/pip3 install -r $PROJECT_ROOT/requirements.txt; then
    echo "❌ ERROR: Failed to install Python packages"
    echo "   Check requirements.txt and network connectivity"
    exit 1
fi
echo "✅ Python environment configured successfully"

# Validate config now that PyYAML is available (if not already validated)
if ! python3 -c "import yaml" 2>/dev/null; then
    echo ""
    echo "🔍 Running config validation..."
    # Use venv python which has PyYAML
    $INSTALL_DIR/venv/bin/python3 << EOF
import sys
import yaml

config_file = "$PROJECT_ROOT/config/config.yaml"
errors = []

try:
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
except yaml.YAMLError as e:
    print(f"❌ YAML syntax error: {e}")
    sys.exit(1)
except FileNotFoundError:
    print(f"❌ Config file not found: {config_file}")
    sys.exit(1)

if not config:
    errors.append("Config file is empty")
else:
    if 'device' not in config or not config.get('device', {}).get('id'):
        errors.append("Missing required field: device.id")
    cameras = config.get('cameras', [])
    if not cameras:
        errors.append("No cameras defined")
    else:
        print(f"   ✓ Found {len(cameras)} camera(s) configured")
    if 'server' not in config or not config.get('server', {}).get('url'):
        errors.append("Missing required field: server.url")
    device_id = config.get('device', {}).get('id', 'unknown')
    location = config.get('device', {}).get('location', 'unknown')
    print(f"   ✓ Device: {device_id} @ {location}")

if errors:
    for error in errors:
        print(f"❌ {error}")
    print("Please fix config/config.yaml before continuing.")
    sys.exit(1)
print("✅ Configuration is valid")
EOF
    if [ $? -ne 0 ]; then
        echo "❌ Installation aborted due to configuration errors"
        exit 1
    fi
fi

# Copy files
echo ""
echo "📋 Installing Service Files"
echo "---------------------------"

# Normalized deployment: all Python code goes to $INSTALL_DIR/src/
echo "📄 Copying Python source files to $INSTALL_DIR/src/..."
sudo mkdir -p $INSTALL_DIR/src
sudo cp $PROJECT_ROOT/src/version.py $INSTALL_DIR/src/
sudo cp $PROJECT_ROOT/src/camera_service.py $INSTALL_DIR/src/
sudo cp $PROJECT_ROOT/src/status_portal.py $INSTALL_DIR/src/
sudo cp $PROJECT_ROOT/src/config_helper.py $INSTALL_DIR/src/
sudo cp $PROJECT_ROOT/src/logging_utils.py $INSTALL_DIR/src/
sudo cp $PROJECT_ROOT/src/update_manager.py $INSTALL_DIR/src/

# Copy camera modules
echo "📦 Installing camera modules..."
sudo cp -r $PROJECT_ROOT/src/cameras $INSTALL_DIR/src/

# Copy portal web assets
echo "🌐 Installing portal web assets..."
sudo mkdir -p $INSTALL_DIR/src/portal
sudo cp -r $PROJECT_ROOT/src/portal/* $INSTALL_DIR/src/portal/

# Legacy compatibility: symlink bin/ -> src/ for any scripts expecting old paths
if [ ! -L "$INSTALL_DIR/bin" ]; then
    sudo rm -rf "$INSTALL_DIR/bin" 2>/dev/null || true
    sudo ln -sf src "$INSTALL_DIR/bin"
    echo "   Created symlink: bin -> src"
fi

# Copy environment configuration if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "🔐 Installing environment configuration..."
    sudo cp $PROJECT_ROOT/.env $INSTALL_DIR/
    sudo chmod 600 $INSTALL_DIR/.env
    sudo chown $SYSTEM_USER:$SYSTEM_GROUP $INSTALL_DIR/.env
else
    echo "📋 Creating .env template..."
    sudo cp $PROJECT_ROOT/.env.example $INSTALL_DIR/.env.example
fi

echo "⚙️  Copying configuration..."
if [ "$PRESERVE_CONFIG" = true ]; then
    # Check if production config exists
    if [ -f "$CONFIG_DIR/config.yaml" ]; then
        echo "ℹ️  Preserving existing production configuration at $CONFIG_DIR/config.yaml"
    else
        echo "⚠️  WARNING: No existing config found at $CONFIG_DIR/config.yaml"
        echo "   Installing default configuration from repository"
        sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/
    fi
else
    # Normal mode - check if production config exists and differs
    if [ -f "$CONFIG_DIR/config.yaml" ]; then
        # Compare configs (ignore whitespace differences)
        if ! diff -q -B "$PROJECT_ROOT/config/config.yaml" "$CONFIG_DIR/config.yaml" > /dev/null 2>&1; then
            echo ""
            echo "⚠️  Configuration Conflict Detected"
            echo "   Repository config differs from deployed config at $CONFIG_DIR/config.yaml"
            echo ""
            echo "   Options:"
            echo "   [1] Keep production config (preserve deployed settings)"
            echo "   [2] Overwrite with repository config (use repo version)"
            echo "   [3] Show diff (view differences first)"
            echo ""
            while true; do
                read -p "   Choose [1/2/3]: " config_choice
                case $config_choice in
                    1)
                        echo "ℹ️  Keeping existing production configuration"
                        break
                        ;;
                    2)
                        echo "📋 Overwriting with repository configuration..."
                        sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/
                        break
                        ;;
                    3)
                        echo ""
                        echo "--- Differences (production vs repository) ---"
                        diff --color=auto -u "$CONFIG_DIR/config.yaml" "$PROJECT_ROOT/config/config.yaml" | head -50 || true
                        echo "--- End of diff (first 50 lines) ---"
                        echo ""
                        ;;
                    *)
                        echo "   Invalid choice. Please enter 1, 2, or 3."
                        ;;
                esac
            done
        else
            echo "ℹ️  Configs are identical, no update needed"
        fi
    else
        # No existing config, install from repo
        echo "📋 Installing configuration from repository..."
        sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/
    fi
fi

# Merge missing config sections (fleet, updates, portal, wifi_ap) into production config.
# Runs after config is in place — covers --preserve-config, interactive keep, and fresh install.
merge_missing_config_sections

echo "🌐 Installing Nginx proxy configuration..."
generate_camera_proxy_config

echo "🔧 Installing systemd services..."
# Export variables for envsubst template processing
export SYSTEM_USER SYSTEM_GROUP INSTALL_DIR CONFIG_DIR LOG_DIR
# Generate service files from templates
envsubst < $PROJECT_ROOT/systemd/sai-cam.service.template | sudo tee /etc/systemd/system/sai-cam.service > /dev/null
envsubst < $PROJECT_ROOT/systemd/sai-cam-portal.service.template | sudo tee /etc/systemd/system/sai-cam-portal.service > /dev/null
echo "   User: $SYSTEM_USER, Group: $SYSTEM_GROUP"

echo "📝 Installing log rotation configuration..."
sudo cp $PROJECT_ROOT/systemd/logrotate.conf /etc/logrotate.d/sai-cam
echo "✅ Service files installed successfully"

# WiFi AP Configuration (NetworkManager-based approach)
echo ""
echo "📡 Checking WiFi Access Point Support"
echo "-------------------------------------"

# Skip WiFi AP if in wifi-client mode (same interface can't be client and AP)
if [ "$NETWORK_MODE" = "wifi-client" ]; then
    echo "⊘ WiFi AP skipped: network mode is 'wifi-client'"
    echo "   The WiFi interface is used for internet connectivity"
    echo "   WiFi AP requires a second WiFi interface (e.g., USB WiFi adapter)"
elif iw dev wlan0 info > /dev/null 2>&1; then
    echo "✅ WiFi hardware detected (wlan0)"

    # Generate WiFi AP configuration from config.yaml
    DEVICE_ID=$(read_config_value "device.id" "unknown")
    WIFI_PASSWORD=$(grep -A 5 "^wifi_ap:" "$PROJECT_ROOT/config/config.yaml" | grep "password:" | sed "s/.*password:\s*['\''\"]*\([^'\''\"#]*\)['\''\"#]*.*/\1/" | sed 's/[[:space:]]*$//')

    # Use default password if not found in config
    if [ -z "$WIFI_PASSWORD" ]; then
        WIFI_PASSWORD="saicam123"
    fi

    echo "🔧 Configuring NetworkManager WiFi AP..."

    # Remove existing connection if it exists
    if nmcli con show "sai-cam-ap" > /dev/null 2>&1; then
        echo "🗑️  Removing existing WiFi AP connection..."
        sudo nmcli con delete "sai-cam-ap" > /dev/null 2>&1
    fi

    # Create NetworkManager WiFi AP connection
    # Uses 'shared' mode which automatically spawns dnsmasq for DHCP
    echo "✨ Creating WiFi AP connection..."
    sudo nmcli con add \
        con-name "sai-cam-ap" \
        ifname wlan0 \
        type wifi \
        mode ap \
        ssid "SAI-Node-$DEVICE_ID" \
        ipv4.method shared \
        ipv4.address $AP_IP/$AP_NETMASK \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$WIFI_PASSWORD" > /dev/null 2>&1

    # Enable autoconnect on boot
    sudo nmcli con modify sai-cam-ap connection.autoconnect yes

    # Disable conflicting services (NetworkManager handles everything)
    echo "🧹 Disabling conflicting services..."
    sudo systemctl stop hostapd dnsmasq 2>/dev/null || true
    sudo systemctl disable hostapd dnsmasq 2>/dev/null || true
    sudo systemctl mask dnsmasq 2>/dev/null || true

    # Stop wpa_supplicant (conflicts with NetworkManager AP mode)
    echo "🔧 Configuring WiFi for AP mode..."
    sudo systemctl stop wpa_supplicant 2>/dev/null || true

    # Unblock WiFi (required on fresh Raspberry Pi OS installations)
    echo "📡 Unblocking WiFi radio..."
    sudo rfkill unblock wifi 2>/dev/null || true

    # Configure captive portal DNS hijacking
    echo "🌐 Configuring captive portal..."
    sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
    # Generate config with AP_IP from .env (replaces __AP_IP__ placeholder)
    sed "s/__AP_IP__/$AP_IP/g" "$PROJECT_ROOT/config/captive-portal-dnsmasq.conf" \
        | sudo tee /etc/NetworkManager/dnsmasq-shared.d/captive-portal-dnsmasq.conf > /dev/null
    sudo chmod 644 /etc/NetworkManager/dnsmasq-shared.d/captive-portal-dnsmasq.conf
    echo "✅ Captive portal DNS configured (AP: $AP_IP)"

    # Restart NetworkManager to reinitialize WiFi interface and load dnsmasq config
    echo "🔄 Restarting NetworkManager..."
    sudo systemctl restart NetworkManager
    sleep 3

    # Bring up the WiFi AP
    echo "🚀 Activating WiFi AP..."
    if sudo nmcli con up sai-cam-ap > /dev/null 2>&1; then
        echo "✅ WiFi AP configured and activated successfully"
        echo "   SSID: SAI-Node-$DEVICE_ID"
        echo "   Password: $WIFI_PASSWORD"
        echo "   IP: $AP_IP"
        echo "   DHCP: $DHCP_RANGE_START-${DHCP_RANGE_END##*.} (managed by NetworkManager)"
        echo "   Captive Portal: Enabled (auto-redirect to status portal)"
    else
        echo "⚠️  WiFi AP connection created but failed to activate"
        echo "   This can happen if WiFi is in use or rfkill blocked"
        echo "   Try manually: sudo rfkill unblock wifi && sudo systemctl stop wpa_supplicant && sudo nmcli con up sai-cam-ap"
    fi
else
    echo "⊘ No WiFi hardware detected, skipping AP setup"
fi

# Set permissions
echo ""
echo "🔐 Setting File Permissions"
echo "---------------------------"
echo "🔧 Configuring ownership and permissions..."
sudo chown -R $SYSTEM_USER:$SYSTEM_GROUP $INSTALL_DIR
# Shared dirs: owned by root with sai-cam group + setgid
sudo chown root:$SAICAM_GROUP $LOG_DIR
sudo chmod 2775 $LOG_DIR
# Fix ownership of existing log files so portal (admin) can write
sudo chown $SYSTEM_USER:$SAICAM_GROUP $LOG_DIR/*.log 2>/dev/null || true
sudo chmod 664 $LOG_DIR/*.log 2>/dev/null || true
sudo chown root:$SAICAM_GROUP /var/lib/sai-cam
sudo chmod 2775 /var/lib/sai-cam
# State file: group-writable so portal can update it
if [ -f /var/lib/sai-cam/update-state.json ]; then
    sudo chown root:$SAICAM_GROUP /var/lib/sai-cam/update-state.json
    sudo chmod 664 /var/lib/sai-cam/update-state.json
fi
sudo chown $SYSTEM_USER:$SYSTEM_GROUP $CONFIG_DIR/config.yaml
sudo chmod 640 $CONFIG_DIR/config.yaml
sudo chmod 644 /etc/nginx/sites-available/camera-proxy
sudo chmod 644 /etc/systemd/system/sai-cam.service
sudo chmod 644 /etc/logrotate.d/sai-cam
# Set permissions for Python source files
sudo chmod 644 $INSTALL_DIR/src/version.py
sudo chmod 755 $INSTALL_DIR/src/camera_service.py
sudo chmod 755 $INSTALL_DIR/src/status_portal.py
sudo chmod 644 $INSTALL_DIR/src/config_helper.py
sudo chmod 644 $INSTALL_DIR/src/logging_utils.py
sudo chmod 644 $INSTALL_DIR/src/update_manager.py
sudo find $INSTALL_DIR/src/cameras -name "*.py" -exec chmod 644 {} \;

# Set permissions for portal web assets
sudo find $INSTALL_DIR/src/portal -type f -exec chmod 644 {} \;
sudo find $INSTALL_DIR/src/portal -type d -exec chmod 755 {} \;

# Secure environment file if it exists
if [ -f "$INSTALL_DIR/.env" ]; then
    sudo chmod 600 $INSTALL_DIR/.env
fi

echo "✅ Permissions configured successfully"

# Install sudoers configuration for WiFi AP management
echo ""
echo "🔐 Installing Sudoers Configuration"
echo "-----------------------------------"
echo "🔧 Installing sudoers file for WiFi AP management..."
if [ -f "$PROJECT_ROOT/config/sai-cam-sudoers" ]; then
    # Install sudoers file
    sudo cp "$PROJECT_ROOT/config/sai-cam-sudoers" /etc/sudoers.d/sai-cam
    sudo chmod 0440 /etc/sudoers.d/sai-cam
    sudo chown root:root /etc/sudoers.d/sai-cam

    # Validate sudoers syntax
    echo "🧪 Validating sudoers syntax..."
    if sudo visudo -c -f /etc/sudoers.d/sai-cam > /dev/null 2>&1; then
        echo "✅ Sudoers configuration installed successfully"
        echo "   User '$SYSTEM_USER' can now manage WiFi AP without password"
    else
        echo "❌ ERROR: Sudoers syntax validation failed"
        echo "   Removing invalid sudoers file..."
        sudo rm -f /etc/sudoers.d/sai-cam
        echo "   WiFi AP control from portal will require manual sudo"
    fi
else
    echo "⚠️  Sudoers template not found at $PROJECT_ROOT/config/sai-cam-sudoers"
    echo "   WiFi AP control from portal will not work without sudo permissions"
fi

# Setup Nginx Configurations
echo ""
echo "🌐 Configuring Nginx Proxy"
echo "--------------------------"

# Generate self-signed TLS cert for HTTPS→HTTP redirect (if missing)
SSL_DIR="/etc/sai-cam/ssl"
if [ ! -f "$SSL_DIR/portal.crt" ] || [ ! -f "$SSL_DIR/portal.key" ]; then
    echo "🔒 Generating self-signed TLS certificate for HTTPS redirect..."
    sudo mkdir -p "$SSL_DIR"
    sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$SSL_DIR/portal.key" \
        -out "$SSL_DIR/portal.crt" \
        -subj "/CN=sai-cam" \
        -addext "subjectAltName=DNS:sai-cam.local,DNS:*.sai-cam.local,IP:$AP_IP" \
        > /dev/null 2>&1
    sudo chmod 600 "$SSL_DIR/portal.key"
    sudo chmod 644 "$SSL_DIR/portal.crt"
    echo "   Certificate generated (valid 10 years, self-signed)"
else
    echo "🔒 TLS certificate already exists, skipping generation"
fi

# Install portal nginx configuration (serves portal on port 80, HTTPS redirect on 443)
echo "🔧 Installing portal nginx configuration..."
# Generate config with AP_IP from .env (replaces __AP_IP__ placeholder)
sed "s/__AP_IP__/$AP_IP/g" "$PROJECT_ROOT/config/portal-nginx.conf" \
    | sudo tee /etc/nginx/sites-available/portal-nginx.conf > /dev/null
sudo chmod 644 /etc/nginx/sites-available/portal-nginx.conf
echo "   Portal configured with AP IP: $AP_IP"

# Disable default nginx site
echo "🗑️  Disabling default nginx site..."
sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# Enable portal site
echo "🔗 Enabling portal site..."
sudo ln -sf /etc/nginx/sites-available/portal-nginx.conf /etc/nginx/sites-enabled/ 2>/dev/null || true

# Enable camera proxy site
echo "🔗 Enabling camera proxy site..."
sudo ln -sf /etc/nginx/sites-available/camera-proxy /etc/nginx/sites-enabled/ 2>/dev/null || true

echo "🧪 Testing Nginx configuration..."
if sudo nginx -t > /dev/null 2>&1; then
    echo "✅ Nginx configuration valid"
    echo "🔄 Restarting Nginx..."
    sudo systemctl restart nginx
    echo "✅ Nginx proxy configured successfully"
else
    echo "⚠️  Nginx configuration test failed - proxy may not work correctly"
fi

# Enable and start services
echo ""
echo "🚀 Starting SAI-CAM Services"
echo "----------------------------"
echo "🔄 Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "⚙️  Enabling services..."
sudo systemctl enable sai-cam
sudo systemctl enable sai-cam-portal

# Install and enable self-update timer
echo "🔄 Installing self-update timer..."
envsubst < "$PROJECT_ROOT/systemd/sai-cam-update.service.template" | \
    sudo tee /etc/systemd/system/sai-cam-update.service > /dev/null
sudo cp "$PROJECT_ROOT/systemd/sai-cam-update.timer.template" \
    /etc/systemd/system/sai-cam-update.timer
sudo systemctl daemon-reload
sudo systemctl enable sai-cam-update.timer
sudo systemctl start sai-cam-update.timer
echo "   ✅ Update timer: every 6h with 30min jitter"

echo "📹 Starting sai-cam service..."
# Check if service is already running and restart it to apply new code
if systemctl is-active --quiet sai-cam; then
    echo "🔄 Service is running, restarting to apply updates..."
    if sudo systemctl restart sai-cam; then
        echo "✅ sai-cam service restarted successfully"
    else
        echo "❌ sai-cam service failed to restart"
        echo "   Check logs: sudo journalctl -u sai-cam -n 20"
    fi
else
    # Service not running, start it fresh
    if sudo systemctl start sai-cam; then
        echo "✅ sai-cam service started successfully"
    else
        echo "❌ sai-cam service failed to start"
        echo "   Check logs: sudo journalctl -u sai-cam -n 20"
    fi
fi

echo "🌐 Starting status portal service..."
if systemctl is-active --quiet sai-cam-portal; then
    echo "🔄 Portal is running, restarting..."
    sudo systemctl restart sai-cam-portal
else
    sudo systemctl start sai-cam-portal
fi

if systemctl is-active --quiet sai-cam-portal; then
    echo "✅ Status portal started successfully"
    echo "   Access at: http://$(hostname -I | awk '{print $1}')/"
else
    echo "⚠️  Status portal failed to start"
    echo "   Check logs: sudo journalctl -u sai-cam-portal -n 20"
fi

# System Monitoring Setup
echo ""
echo "🔧 Setting Up System Monitoring"
echo "--------------------------------"

# Copy monitoring scripts
if [ -d "$PROJECT_ROOT/system/monitoring" ]; then
    echo "📋 Installing monitoring scripts..."
    sudo mkdir -p $INSTALL_DIR/system/monitoring
    sudo mkdir -p $INSTALL_DIR/system/config
    sudo cp -r $PROJECT_ROOT/system/monitoring/* $INSTALL_DIR/system/monitoring/
    sudo cp -r $PROJECT_ROOT/system/config/* $INSTALL_DIR/system/config/
    sudo chmod +x $INSTALL_DIR/system/monitoring/*.sh
fi

# Install self-update system
echo "🔄 Installing self-update script..."
sudo cp "$PROJECT_ROOT/scripts/self-update.sh" "$INSTALL_DIR/system/self-update.sh"
sudo chmod 755 "$INSTALL_DIR/system/self-update.sh"

# Clone repo for self-update system (fresh install only)
if [ ! -d "$INSTALL_DIR/repo/.git" ]; then
    echo "📦 Cloning repository for self-update system..."
    sudo git clone --depth 50 https://github.com/AlterMundi/sai-cam.git "$INSTALL_DIR/repo" 2>&1 || {
        echo "⚠️  Failed to clone repo (self-update will clone on first run)"
    }
fi

# Setup cron jobs for monitoring and scheduled maintenance
echo "⏰ Setting up scheduled tasks..."
CRON_FILE="/etc/cron.d/sai-cam"
sudo tee "$CRON_FILE" > /dev/null << EOF
# SAI-CAM System Monitoring and Maintenance
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# System monitoring - every 5 minutes
*/5 * * * * $SYSTEM_USER $INSTALL_DIR/system/monitoring/system_monitor.sh >/dev/null 2>&1

# Service watchdog - every 10 minutes
*/10 * * * * root $INSTALL_DIR/system/monitoring/service_watchdog.sh >/dev/null 2>&1

# Internet watchdog - every 3 minutes (auto-enable WiFi AP when offline)
*/3 * * * * root $INSTALL_DIR/system/monitoring/internet_watchdog.sh >/dev/null 2>&1

# Storage cleanup - weekly on Sunday at 3 AM
0 3 * * 0 $SYSTEM_USER $INSTALL_DIR/system/monitoring/cleanup_storage.sh >/dev/null 2>&1

# Log cleanup - weekly on Sunday at 2 AM
0 2 * * 0 root $INSTALL_DIR/system/monitoring/cleanup_logs.sh >/dev/null 2>&1

# Scheduled daily reboot - every day at 4 AM (for long-term stability)
0 4 * * * root /sbin/shutdown -r +1 "Scheduled daily maintenance reboot" >/dev/null 2>&1
EOF
sudo chmod 644 "$CRON_FILE"
echo "✅ Scheduled tasks configured (including daily reboot at 4 AM)"

# Hardware watchdog (Raspberry Pi specific)
if [ -e /dev/watchdog ] || modprobe bcm2835_wdt 2>/dev/null; then
    echo "🐕 Configuring hardware watchdog..."

    # Ensure module loads on boot
    if ! grep -q "bcm2835_wdt" /etc/modules-load.d/*.conf 2>/dev/null; then
        echo "bcm2835_wdt" | sudo tee /etc/modules-load.d/watchdog.conf > /dev/null
    fi

    # Install watchdog daemon if not present
    if ! command -v watchdog &> /dev/null; then
        sudo apt-get install -y watchdog > /dev/null 2>&1 || true
    fi

    # Configure watchdog if installed
    if [ -f "$INSTALL_DIR/system/config/watchdog.conf" ]; then
        sudo cp "$INSTALL_DIR/system/config/watchdog.conf" /etc/watchdog.conf
        sudo systemctl enable watchdog 2>/dev/null || true
        # Stop first, wait, then start (avoid restart race condition)
        sudo systemctl stop watchdog 2>/dev/null || true
        sleep 2
        sudo systemctl start watchdog 2>/dev/null || true
        sleep 1
        if systemctl is-active watchdog > /dev/null 2>&1; then
            echo "✅ Hardware watchdog enabled (15s timeout)"
        else
            echo "⚠️  Hardware watchdog configured but failed to start"
            echo "   Try manually: sudo systemctl start watchdog"
        fi
    fi
else
    echo "ℹ️  Hardware watchdog not available (not a Raspberry Pi?)"
fi

# ══════════════════════════════════════════════════════════════════════════════
# vmagent metrics shipper (optional, --monitoring flag)
# ══════════════════════════════════════════════════════════════════════════════
if [ "$INSTALL_MONITORING" = true ]; then
    echo ""
    echo "📈 Installing vmagent Metrics Shipper"
    echo "-------------------------------------"

    VMAGENT_VERSION="v1.106.1"
    VMAGENT_DIR="$INSTALL_DIR/vmagent"

    # Detect architecture
    ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
    case "$ARCH" in
        amd64|x86_64)  ARCH="amd64" ;;
        arm64|aarch64) ARCH="arm64" ;;
        armhf|armv7l)  ARCH="arm"   ;;
        *)
            echo "❌ Unsupported architecture: $ARCH"
            echo "   vmagent installation skipped"
            INSTALL_MONITORING=false
            ;;
    esac

    if [ "$INSTALL_MONITORING" = true ]; then
        sudo mkdir -p "$VMAGENT_DIR/buffer"

        # Download vmagent if not present or version mismatch
        NEED_DOWNLOAD=true
        if [ -f "$VMAGENT_DIR/vmagent-prod" ]; then
            CURRENT_VER=$("$VMAGENT_DIR/vmagent-prod" -version 2>&1 | head -1 || echo "unknown")
            if echo "$CURRENT_VER" | grep -q "${VMAGENT_VERSION#v}"; then
                echo "✅ vmagent $VMAGENT_VERSION already installed"
                NEED_DOWNLOAD=false
            fi
        fi

        if [ "$NEED_DOWNLOAD" = true ]; then
            TARBALL="vmutils-linux-${ARCH}-${VMAGENT_VERSION}.tar.gz"
            DOWNLOAD_URL="https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VMAGENT_VERSION}/${TARBALL}"
            echo "📥 Downloading vmagent ${VMAGENT_VERSION} (${ARCH})..."
            echo "   URL: $DOWNLOAD_URL"
            if wget -q --show-progress -O "/tmp/${TARBALL}" "$DOWNLOAD_URL"; then
                echo "📦 Extracting vmagent-prod binary..."
                tar -xzf "/tmp/${TARBALL}" -C "$VMAGENT_DIR" vmagent-prod
                rm -f "/tmp/${TARBALL}"
                sudo chmod 755 "$VMAGENT_DIR/vmagent-prod"
                echo "✅ vmagent binary installed to $VMAGENT_DIR/vmagent-prod"
            else
                echo "❌ Failed to download vmagent"
                echo "   Check network connectivity and try again"
                INSTALL_MONITORING=false
            fi
        fi
    fi

    if [ "$INSTALL_MONITORING" = true ]; then
        # Read config values for vmagent
        NODE_ID=$(read_config_value "device.id" "unknown")

        # Read metrics config from config.yaml
        REMOTE_WRITE_URL=$(python3 -c "
import yaml, sys
try:
    with open('$PROJECT_ROOT/config/config.yaml') as f:
        c = yaml.safe_load(f)
    print(c.get('metrics', {}).get('remote_write_url', 'https://grafana2.altermundi.net/vmwrite'))
except Exception:
    print('https://grafana2.altermundi.net/vmwrite')
" 2>/dev/null)
        REMOTE_WRITE_URL=${REMOTE_WRITE_URL:-"https://grafana2.altermundi.net/vmwrite"}

        REMOTE_WRITE_USER=$(python3 -c "
import yaml, sys
try:
    with open('$PROJECT_ROOT/config/config.yaml') as f:
        c = yaml.safe_load(f)
    print(c.get('metrics', {}).get('remote_write_user', ''))
except Exception:
    print('')
" 2>/dev/null)

        REMOTE_WRITE_PASSWORD=$(python3 -c "
import yaml, sys
try:
    with open('$PROJECT_ROOT/config/config.yaml') as f:
        c = yaml.safe_load(f)
    print(c.get('metrics', {}).get('remote_write_password', ''))
except Exception:
    print('')
" 2>/dev/null)

        echo "🔧 Configuring vmagent..."
        echo "   Node ID:          $NODE_ID"
        echo "   Remote Write URL: $REMOTE_WRITE_URL"

        # Generate scrape config from template
        export NODE_ID
        envsubst < "$PROJECT_ROOT/config/vmagent-scrape.yml" | sudo tee /etc/sai-cam/vmagent-scrape.yml > /dev/null
        echo "   ✅ Scrape config: /etc/sai-cam/vmagent-scrape.yml"

        # Create auth env file (empty by default, populate with VM_AUTH_USER/VM_AUTH_PASSWORD if needed)
        if [ ! -f /etc/sai-cam/vmagent-auth.env ]; then
            sudo touch /etc/sai-cam/vmagent-auth.env
            sudo chmod 600 /etc/sai-cam/vmagent-auth.env
            sudo chown $SYSTEM_USER:$SYSTEM_GROUP /etc/sai-cam/vmagent-auth.env
        fi
        echo "   ✅ Auth env: /etc/sai-cam/vmagent-auth.env"

        # Generate systemd service from template
        export REMOTE_WRITE_URL REMOTE_WRITE_USER REMOTE_WRITE_PASSWORD
        envsubst < "$PROJECT_ROOT/systemd/vmagent.service.template" | sudo tee /etc/systemd/system/vmagent.service > /dev/null
        echo "   ✅ Service: /etc/systemd/system/vmagent.service"

        # Set permissions
        sudo chown -R "$SYSTEM_USER:$SYSTEM_GROUP" "$VMAGENT_DIR"

        # Enable and start vmagent
        sudo systemctl daemon-reload
        sudo systemctl enable vmagent
        if sudo systemctl restart vmagent; then
            sleep 2
            if systemctl is-active --quiet vmagent; then
                echo "✅ vmagent is running and shipping metrics"
            else
                echo "⚠️  vmagent was started but is not active"
                echo "   Check logs: sudo journalctl -u vmagent -n 20"
            fi
        else
            echo "❌ Failed to start vmagent"
            echo "   Check logs: sudo journalctl -u vmagent -n 20"
        fi
    fi
fi

# Create health check script
echo "📊 Creating health check script..."
sudo tee "$INSTALL_DIR/check_health.sh" > /dev/null << 'HEALTHSCRIPT'
#!/bin/bash
echo "SAI-CAM System Health Check"
echo "==========================="
echo

echo "System Resources:"
echo "-----------------"
if command -v vcgencmd &> /dev/null; then
    echo "Temperature: $(vcgencmd measure_temp | cut -d= -f2)"
fi
echo "CPU Usage: $(top -bn1 | grep "Cpu(s)" | awk '{print $2+$4}')%"
echo "Memory: $(free -h | grep Mem | awk '{print $3 "/" $2}')"
echo "Disk: $(df -h /opt/sai-cam | tail -1 | awk '{print $3 "/" $2 " (" $5 ")"}')"
echo

echo "Services Status:"
echo "----------------"
systemctl is-active sai-cam > /dev/null && echo "✓ sai-cam: running" || echo "✗ sai-cam: stopped"
systemctl is-active sai-cam-portal > /dev/null && echo "✓ portal: running" || echo "✗ portal: stopped"
systemctl is-active vmagent > /dev/null 2>&1 && echo "✓ vmagent: running" || echo "- vmagent: not installed"
systemctl is-active watchdog > /dev/null && echo "✓ watchdog: running" || echo "✗ watchdog: not running"
echo

echo "Storage:"
echo "--------"
du -sh /opt/sai-cam/storage 2>/dev/null || echo "No storage data"
HEALTHSCRIPT
sudo chmod +x "$INSTALL_DIR/check_health.sh"
echo "✅ Health check: $INSTALL_DIR/check_health.sh"

echo ""
if [ "$PRESERVE_CONFIG" = true ]; then
    echo "🎉 SAI-CAM Code Update Completed!"
    echo "=================================="
    echo ""
    echo "ℹ️  Production configuration preserved at: $CONFIG_DIR/config.yaml"
else
    echo "🎉 SAI-CAM Installation Completed!"
    echo "=================================="
fi
echo ""
echo "📊 Service Status:"
echo "------------------"
sudo systemctl status sai-cam --no-pager -l

echo ""
echo "🔍 Next Steps:"
echo "--------------"
echo "• Access status portal: http://$(hostname -I | awk '{print $1}')/"
echo "• Check system health: $INSTALL_DIR/check_health.sh"
echo "• Check service logs: sudo journalctl -u sai-cam -f"
echo "• Edit configuration: sudo nano $CONFIG_DIR/config.yaml"
echo "• Restart services: sudo systemctl restart sai-cam sai-cam-portal"
echo ""
echo "📅 Scheduled Maintenance:"
echo "  • Storage cleanup: Weekly Sunday 3 AM"
echo "  • Log rotation: Weekly Sunday 2 AM"
echo "  • System reboot: Daily at 4 AM"
if [ "$PRESERVE_CONFIG" = true ]; then
    echo ""
    echo "⚠️  Note: Configuration was preserved from production"
    echo "   To update config: sudo nano $CONFIG_DIR/config.yaml && sudo systemctl restart sai-cam"
fi
echo ""
if [ "$INSTALL_MONITORING" = true ]; then
    echo "📈 Monitoring:"
    echo "  • vmagent status: sudo systemctl status vmagent"
    echo "  • Metrics endpoint: curl http://localhost:8090/metrics"
    echo "  • Remote write: $REMOTE_WRITE_URL"
fi
echo ""
echo "📚 For troubleshooting, see the documentation in docs/"
