#!/bin/bash
set -e

# Default values
CONFIG_ONLY=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--config-only)
            CONFIG_ONLY=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [-c|--config-only]"
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
        # Simple YAML parser for specific keys
        case $key in
            "network.node_ip")
                grep -E "^\s*node_ip:" "$config_file" | sed 's/.*node_ip:\s*['\''\"]*\([^'\''\"]*\)['\''\"]*$/\1/' | tr -d ' '
                ;;
            "network.interface")
                grep -E "^\s*interface:" "$config_file" | sed 's/.*interface:\s*['\''\"]*\([^'\''\"]*\)['\''\"]*$/\1/' | tr -d ' '
                ;;
            "network.connection_name")
                grep -E "^\s*connection_name:" "$config_file" | sed 's/.*connection_name:\s*['\''\"]*\([^'\''\"]*\)['\''\"]*$/\1/' | tr -d ' '
                ;;
            "system.user")
                grep -E "^\s*user:" "$config_file" | sed 's/.*user:\s*['\''\"]*\([^'\''\"]*\)['\''\"]*$/\1/' | tr -d ' '
                ;;
            "system.group")
                grep -E "^\s*group:" "$config_file" | sed 's/.*group:\s*['\''\"]*\([^'\''\"]*\)['\''\"]*$/\1/' | tr -d ' '
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
            "$PROJECT_ROOT/systemd/sai-network.service"
            "$PROJECT_ROOT/systemd/logrotate.conf"
            "$PROJECT_ROOT/requirements.txt"
        )
    fi

    local missing_files=0
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            echo "ERROR: Required file not found: $file"
            missing_files=1
        fi
    done

    if [ $missing_files -eq 1 ]; then
        echo "Installation aborted due to missing files"
        exit 1
    fi
}

# Function to backup existing config

backup_existing_config() {
    if [ -d "$CONFIG_DIR" ]; then
        echo "Creating backup of existing configuration..."
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/config"
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/systemd"
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP/logrotate"

        # Backup configs if they exist
        if [ -d "$CONFIG_DIR" ]; then
            sudo cp -r "$CONFIG_DIR"/* "$BACKUP_DIR/$TIMESTAMP/config/"
            echo "Configuration backup created at: $BACKUP_DIR/$TIMESTAMP/config/"
        fi

        if [ "$CONFIG_ONLY" = false ]; then
            # Backup systemd service file if it exists
            if [ -f "/etc/systemd/system/sai-cam.service" ]; then
                sudo cp "/etc/systemd/system/sai-cam.service" "$BACKUP_DIR/$TIMESTAMP/systemd/"
                echo "Service file backup created at: $BACKUP_DIR/$TIMESTAMP/systemd/sai-cam.service"
            fi

            # Backup systemd service file if it exists
            if [ -f "/etc/systemd/system/sai-network.service" ]; then
                sudo cp "/etc/systemd/system/sai-network.service" "$BACKUP_DIR/$TIMESTAMP/systemd/"
                echo "Service file backup created at: $BACKUP_DIR/$TIMESTAMP/systemd/sai-network.service"
            fi

            # Backup logrotate config if it exists
            if [ -f "/etc/logrotate.d/sai-cam" ]; then
                sudo cp "/etc/logrotate.d/sai-cam" "$BACKUP_DIR/$TIMESTAMP/logrotate/"
                echo "Logrotate config backup created at: $BACKUP_DIR/$TIMESTAMP/logrotate/sai-cam"
            fi
        fi
    fi
}
# Verify we're running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "Please run this script with sudo"
    exit 1
fi

# Check for required files before proceeding
echo "Checking for required files..."
check_required_files

# Create backup of existing installation
echo "Checking for existing configuration..."
backup_existing_config

if [ "$CONFIG_ONLY" = true ]; then
    echo "Updating configuration only..."
    sudo mkdir -p $CONFIG_DIR
    sudo chown $SYSTEM_USER:$SYSTEM_GROUP $CONFIG_DIR
    sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/
    sudo chmod 644 $CONFIG_DIR/config.yaml
    echo "Configuration updated successfully!"
    if systemctl is-active --quiet sai-cam; then
        echo "Note: The sai-cam service is running. You may want to restart it to apply the new configuration:"
        echo "sudo systemctl restart sai-cam"
    fi
    exit 0
fi

# Continue with full installation if not config-only
echo "Starting installation..."

# crear un nuevo perfil "saicam" que use DHCP como primaria y añada la IP fija como secundaria:
## Network configuration from config.yaml:
echo "Configuring network: $CONNECTION_NAME on $INTERFACE with IP $NODE_IP"
sudo nmcli con add con-name "$CONNECTION_NAME" ifname $INTERFACE type ethernet ipv4.method auto ipv4.addresses "$NODE_IP"
sudo nmcli con up $CONNECTION_NAME

# Create directories
sudo mkdir -p $INSTALL_DIR/bin
sudo mkdir -p $INSTALL_DIR/storage
sudo mkdir -p $CONFIG_DIR
sudo mkdir -p $LOG_DIR

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y $SYSTEM_PACKAGES

# Set up virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv $INSTALL_DIR/venv
source $INSTALL_DIR/venv/bin/activate
$INSTALL_DIR/venv/bin/pip3 install -r $PROJECT_ROOT/requirements.txt

# Copy files
echo "Copying service files..."
sudo cp $PROJECT_ROOT/src/camera_service.py $INSTALL_DIR/bin/
sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/
sudo cp $PROJECT_ROOT/config/camera-proxy /etc/nginx/sites-available/
sudo cp $PROJECT_ROOT/systemd/sai-cam.service /etc/systemd/system/sai-cam.service
sudo cp $PROJECT_ROOT/systemd/sai-network.service /etc/systemd/system/sai-network.service
sudo cp $PROJECT_ROOT/systemd/logrotate.conf /etc/logrotate.d/sai-cam

# Set permissions
echo "Setting file permissions..."
sudo chown -R $SYSTEM_USER:$SYSTEM_GROUP $INSTALL_DIR
sudo chown -R $SYSTEM_USER:$SYSTEM_GROUP $LOG_DIR
sudo chmod 644 $CONFIG_DIR/config.yaml
sudo chmod 644 /etc/nginx/sites-available/camera-proxy
sudo chmod 644 /etc/systemd/system/sai-cam.service
sudo chmod 644 /etc/systemd/system/sai-network.service
sudo chmod 644 /etc/logrotate.d/sai-cam
sudo chmod 755 $INSTALL_DIR/bin/camera_service.py

# Setup a Camera Proxy for the node
sudo ln -s /etc/nginx/sites-available/camera-proxy /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Enable and start service
echo "Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable sai-network
sudo systemctl start sai-network
sudo systemctl enable sai-cam
sudo systemctl start sai-cam

echo "Installation completed successfully!"
echo "Service status:"
sudo systemctl status sai-cam
