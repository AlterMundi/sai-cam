#!/bin/bash
set -e

# Default values
CONFIG_ONLY=false

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
    -c, --config-only     Update configuration files only (no system changes)
    -h, --help           Show this help message and exit

EXAMPLES:
    # Full installation (requires sudo)
    sudo ./install.sh

    # Update configuration only
    sudo ./install.sh --config-only

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

CONFIGURATION:
    Edit config/config.yaml before running this script. Key sections:

    network:           # Optional - for static IP configuration
      node_ip: '192.168.220.10/24'
      interface: 'eth0'
      connection_name: 'saicam'

    cameras:           # Required - define your cameras
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
SYSTEM_PACKAGES="python3-pip python3-opencv python3-venv libsystemd-dev nginx"

# Default system user (can be overridden by config.yaml)
DEFAULT_USER="admin"
DEFAULT_GROUP="admin"

# Network configuration defaults (can be overridden by config.yaml)
DEFAULT_NODE_IP="192.168.220.10/24"
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
            *)
                echo "$default_value"
                ;;
        esac
    else
        echo "$default_value"
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
    else
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
    if [ -d "$CONFIG_DIR" ]; then
        echo "📦 Creating backup of existing configuration..."
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/config"
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/systemd"
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/logrotate"

        # Backup configs if they exist
        if [ -d "$CONFIG_DIR" ]; then
            sudo cp -r "$CONFIG_DIR"/* "$BACKUP_DIR/$TIMESTAMP/config/"
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
python3 -m venv $INSTALL_DIR/venv

echo "📥 Installing Python packages..."
source $INSTALL_DIR/venv/bin/activate
$INSTALL_DIR/venv/bin/pip3 install -r $PROJECT_ROOT/requirements.txt > /dev/null 2>&1
echo "✅ Python environment configured successfully"

# Copy files
echo ""
echo "📋 Installing Service Files"
echo "---------------------------"
echo "📄 Copying camera service..."
sudo cp $PROJECT_ROOT/src/camera_service.py $INSTALL_DIR/bin/

echo "⚙️  Copying configuration..."
sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/

echo "🌐 Installing Nginx proxy configuration..."
sudo cp $PROJECT_ROOT/config/camera-proxy /etc/nginx/sites-available/

echo "🔧 Installing systemd service..."
sudo cp $PROJECT_ROOT/systemd/sai-cam.service /etc/systemd/system/sai-cam.service

echo "📝 Installing log rotation configuration..."
sudo cp $PROJECT_ROOT/systemd/logrotate.conf /etc/logrotate.d/sai-cam
echo "✅ Service files installed successfully"

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
echo "✅ Permissions configured successfully"

# Setup Camera Proxy
echo ""
echo "🌐 Configuring Nginx Proxy"
echo "--------------------------"
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

echo "⚙️  Enabling sai-cam service..."
sudo systemctl enable sai-cam

echo "📹 Starting sai-cam service..."
if sudo systemctl start sai-cam; then
    echo "✅ sai-cam service started successfully"
else
    echo "❌ sai-cam service failed to start"
    echo "   Check logs: sudo journalctl -u sai-cam -n 20"
fi

echo ""
echo "🎉 SAI-CAM Installation Completed!"
echo "=================================="
echo ""
echo "📊 Service Status:"
echo "------------------"
sudo systemctl status sai-cam --no-pager -l

echo ""
echo "🔍 Next Steps:"
echo "--------------"
echo "• Check service logs: sudo journalctl -u sai-cam -f"
echo "• Edit configuration: sudo nano $CONFIG_DIR/config.yaml"
echo "• Restart service: sudo systemctl restart sai-cam"
echo "• View camera feeds: Check Nginx proxy configuration"
echo ""
echo "📚 For troubleshooting, see the documentation in docs/"
