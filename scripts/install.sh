#!/bin/bash
set -e

# Default values
CONFIG_ONLY=false
PRESERVE_CONFIG=false

# Function to display help information
show_help() {
    cat << 'EOF'
SAI-CAM Installation Script
===========================

DESCRIPTION:
    This script installs and configures the SAI-CAM (Smart AI Camera) system
    on Linux systems. It supports both full installation and configuration-only
    updates for existing deployments.

USAGE:
    sudo ./install.sh [OPTIONS]

OPTIONS:
    -c, --config-only         Update configuration files only (no code/system changes)
    -p, --preserve-config     Update code only, preserve existing configuration
    -h, --help               Show this help message and exit

EXAMPLES:
    # Full installation (requires sudo)
    sudo ./install.sh

    # Update configuration only
    sudo ./install.sh --config-only

    # Update code and preserve production configuration
    sudo ./install.sh --preserve-config

    # Show help
    ./install.sh --help

REQUIREMENTS:
    - Ubuntu/Debian-based Linux distribution
    - Root privileges (sudo)
    - Network connectivity for package installation
    - Properly configured config/config.yaml file

WHAT THIS SCRIPT DOES:

Full Installation (-c flag NOT used):
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

Configuration-Only Update (-c flag used):
    1. Backs up existing configuration
    2. Updates config.yaml file only
    3. Preserves all system settings and services
    4. Suggests service restart if needed

Code-Only Update (-p flag used):
    1. Backs up existing files
    2. Updates all code files (camera_service.py, camera modules, etc.)
    3. Updates systemd service, nginx proxy, and logrotate configs
    4. Preserves existing /etc/sai-cam/config.yaml
    5. Restarts service to apply code changes

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
        -c|--config-only)
            CONFIG_ONLY=true
            shift
            ;;
        -p|--preserve-config)
            PRESERVE_CONFIG=true
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

# Validate that mutually exclusive flags aren't both set
if [ "$CONFIG_ONLY" = true ] && [ "$PRESERVE_CONFIG" = true ]; then
    echo "❌ ERROR: --config-only and --preserve-config are mutually exclusive"
    echo ""
    echo "Choose one:"
    echo "  --config-only      : Update configuration only (no code changes)"
    echo "  --preserve-config  : Update code only (preserve configuration)"
    echo ""
    echo "Try '$0 --help' for more information."
    exit 1
fi

# Internal variables for system maintenance (not user-configurable)
INSTALL_DIR="/opt/sai-cam"
CONFIG_DIR="/etc/sai-cam"
LOG_DIR="/var/log/sai-cam"
BACKUP_DIR="/var/backups/sai-cam"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# System packages required for installation
SYSTEM_PACKAGES="python3-pip python3-opencv python3-venv libsystemd-dev nginx"

# Default system user (can be overridden by config.yaml)
DEFAULT_USER="admin"
DEFAULT_GROUP="admin"

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
                grep -E "^\s*interface:" "$config_file" | sed 's/.*interface:\s*['\''\"]*\([^'\''\"#]*\)['\''\"#]*.*/\1/' | sed 's/[[:space:]]*$//'
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
SYSTEM_USER=$(read_config_value "system.user" "$DEFAULT_USER")
SYSTEM_GROUP=$(read_config_value "system.group" "$DEFAULT_GROUP")

# Function to check if required files exist
check_required_files() {
    local required_files=()

    if [ "$CONFIG_ONLY" = true ]; then
        required_files=(
            "$PROJECT_ROOT/config/config.yaml"
        )
    elif [ "$PRESERVE_CONFIG" = true ]; then
        # For preserve-config mode, we need code files but not config
        required_files=(
            "$PROJECT_ROOT/src/camera_service.py"
            "$PROJECT_ROOT/config/camera-proxy"
            "$PROJECT_ROOT/systemd/sai-cam.service"
            "$PROJECT_ROOT/systemd/logrotate.conf"
            "$PROJECT_ROOT/requirements.txt"
        )
    else
        # Full installation requires everything
        required_files=(
            "$PROJECT_ROOT/src/camera_service.py"
            "$PROJECT_ROOT/config/config.yaml"
            "$PROJECT_ROOT/config/camera-proxy"
            "$PROJECT_ROOT/systemd/sai-cam.service"
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

        if [ "$CONFIG_ONLY" = false ]; then
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

echo "🚀 SAI-CAM Installation Script"
echo "=============================="

# Check for required files before proceeding
echo "📋 Checking for required files..."
check_required_files

# Create backup of existing installation
echo "💾 Checking for existing configuration..."
backup_existing_config

if [ "$CONFIG_ONLY" = true ]; then
    echo "⚙️  Configuration-only update mode"
    echo "-----------------------------------"
    sudo mkdir -p $CONFIG_DIR
    sudo chown $SYSTEM_USER:$SYSTEM_GROUP $CONFIG_DIR
    sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/
    sudo chmod 644 $CONFIG_DIR/config.yaml
    echo "✅ Configuration updated successfully!"
    
    if systemctl is-active --quiet sai-cam; then
        echo ""
        echo "ℹ️  NOTE: The sai-cam service is running."
        echo "   To apply the new configuration, restart the service:"
        echo "   sudo systemctl restart sai-cam"
    fi
    echo ""
    echo "🎉 Configuration update completed!"
    exit 0
fi

# Continue with full installation if not config-only
echo "🔧 Starting full SAI-CAM installation..."
echo "========================================"

# Network configuration from config.yaml:
echo ""
echo "🌐 Network Configuration"
echo "------------------------"
echo "Connection: ${CONNECTION_NAME:-'(not specified)'}"
echo "Interface:  ${INTERFACE:-'(not specified)'}"
echo "IP Address: ${NODE_IP:-'(not specified)'}"

# Only configure network if values are provided and non-empty
if [ -n "$CONNECTION_NAME" ] && [ -n "$INTERFACE" ] && [ -n "$NODE_IP" ]; then
    echo "⚙️  Setting up network connection..."
    
    # Check if connection already exists and delete it
    if nmcli con show "$CONNECTION_NAME" >/dev/null 2>&1; then
        echo "🗑️  Removing existing connection: $CONNECTION_NAME"
        sudo nmcli con delete "$CONNECTION_NAME"
    fi
    
    # Create new connection with DHCP primary and static IP secondary
    echo "🔧 Creating network connection with DHCP + static IP..."
    sudo nmcli con add con-name "$CONNECTION_NAME" ifname "$INTERFACE" type ethernet ipv4.method auto ipv4.addresses "$NODE_IP"
    
    echo "🔌 Activating network connection..."
    sudo nmcli con up "$CONNECTION_NAME"
    
    echo "✅ Network configuration completed successfully"
else
    echo "⚠️  Network configuration skipped"
    echo "   Reason: Missing network settings in config.yaml"
    echo "   The system will use default network configuration"
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
echo "✅ Directories created successfully"

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

# Copy files
echo ""
echo "📋 Installing Service Files"
echo "---------------------------"
echo "📄 Copying camera service and modules..."
# Copy main camera service
sudo cp $PROJECT_ROOT/src/camera_service.py $INSTALL_DIR/bin/

# Copy new modular camera architecture
echo "📦 Installing camera modules..."
sudo cp -r $PROJECT_ROOT/src/cameras $INSTALL_DIR/
sudo cp $PROJECT_ROOT/src/config_helper.py $INSTALL_DIR/

# Copy status portal
echo "🌐 Installing status portal..."
sudo cp $PROJECT_ROOT/src/status_portal.py $INSTALL_DIR/
sudo mkdir -p $INSTALL_DIR/portal
sudo cp -r $PROJECT_ROOT/src/portal/* $INSTALL_DIR/portal/

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
    # Normal mode or config-only mode - install/update config
    sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/
fi

echo "🌐 Installing Nginx proxy configuration..."
generate_camera_proxy_config

echo "🔧 Installing systemd services..."
sudo cp $PROJECT_ROOT/systemd/sai-cam.service /etc/systemd/system/sai-cam.service
sudo cp $PROJECT_ROOT/systemd/sai-cam-portal.service /etc/systemd/system/sai-cam-portal.service

echo "📝 Installing log rotation configuration..."
sudo cp $PROJECT_ROOT/systemd/logrotate.conf /etc/logrotate.d/sai-cam
echo "✅ Service files installed successfully"

# WiFi AP Configuration (NetworkManager-based approach)
echo ""
echo "📡 Checking WiFi Access Point Support"
echo "-------------------------------------"
if iw dev wlan0 info > /dev/null 2>&1; then
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
        ipv4.address 192.168.4.1/24 \
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

    # Restart NetworkManager to reinitialize WiFi interface
    echo "🔄 Restarting NetworkManager..."
    sudo systemctl restart NetworkManager
    sleep 3

    # Bring up the WiFi AP
    echo "🚀 Activating WiFi AP..."
    if sudo nmcli con up sai-cam-ap > /dev/null 2>&1; then
        echo "✅ WiFi AP configured and activated successfully"
        echo "   SSID: SAI-Node-$DEVICE_ID"
        echo "   Password: $WIFI_PASSWORD"
        echo "   IP: 192.168.4.1"
        echo "   DHCP: 192.168.4.10-254 (managed by NetworkManager)"
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
sudo chown -R $SYSTEM_USER:$SYSTEM_GROUP $LOG_DIR
sudo chmod 644 $CONFIG_DIR/config.yaml
sudo chmod 644 /etc/nginx/sites-available/camera-proxy
sudo chmod 644 /etc/systemd/system/sai-cam.service
sudo chmod 644 /etc/logrotate.d/sai-cam
sudo chmod 755 $INSTALL_DIR/bin/camera_service.py

# Set permissions for new camera modules
sudo find $INSTALL_DIR/cameras -name "*.py" -exec chmod 644 {} \;
sudo chmod 644 $INSTALL_DIR/config_helper.py

# Set permissions for status portal
sudo chmod 755 $INSTALL_DIR/status_portal.py
sudo find $INSTALL_DIR/portal -type f -exec chmod 644 {} \;
sudo find $INSTALL_DIR/portal -type d -exec chmod 755 {} \;

# Secure environment file if it exists
if [ -f "$INSTALL_DIR/.env" ]; then
    sudo chmod 600 $INSTALL_DIR/.env
fi

echo "✅ Permissions configured successfully"

# Setup Nginx Configurations
echo ""
echo "🌐 Configuring Nginx Proxy"
echo "--------------------------"

# Install portal nginx configuration (serves portal on port 80)
echo "🔧 Installing portal nginx configuration..."
sudo cp "$PROJECT_ROOT/config/portal-nginx.conf" /etc/nginx/sites-available/portal-nginx.conf
sudo chmod 644 /etc/nginx/sites-available/portal-nginx.conf

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
echo "• Check service logs: sudo journalctl -u sai-cam -f"
echo "• Check portal logs: sudo journalctl -u sai-cam-portal -f"
echo "• Edit configuration: sudo nano $CONFIG_DIR/config.yaml"
echo "• Restart services: sudo systemctl restart sai-cam sai-cam-portal"
echo "• View camera feeds: Check Nginx proxy configuration (ports 8080+)"
if [ "$PRESERVE_CONFIG" = true ]; then
    echo ""
    echo "⚠️  Note: Configuration was preserved from production"
    echo "   If you need to update config, edit $CONFIG_DIR/config.yaml manually"
    echo "   or run: sudo ./scripts/install.sh --config-only"
fi
echo ""
echo "📚 For troubleshooting, see the documentation in docs/"
