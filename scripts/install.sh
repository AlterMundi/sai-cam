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

# Define variables
INSTALL_DIR="/opt/sai-cam"
CONFIG_DIR="/etc/sai-cam"
LOG_DIR="/var/log/sai-cam"
BACKUP_DIR="/var/backups/sai-cam"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

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
            "$PROJECT_ROOT/systemd/camera-service.service"
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
        sudo mkdir -p "$BACKUP_DIR/$TIMESTAMP"

        # Backup configs if they exist
        if [ -d "$CONFIG_DIR" ]; then
            sudo cp -r "$CONFIG_DIR" "$BACKUP_DIR/$TIMESTAMP/"
            echo "Configuration backup created at: $BACKUP_DIR/$TIMESTAMP/$(basename $CONFIG_DIR)"
        fi

        if [ "$CONFIG_ONLY" = false ]; then
            # Backup systemd service file if it exists
            if [ -f "/etc/systemd/system/sai-cam.service" ]; then
                sudo cp "/etc/systemd/system/sai-cam.service" "$BACKUP_DIR/$TIMESTAMP/"
                echo "Service file backup created at: $BACKUP_DIR/$TIMESTAMP/sai-cam.service"
            fi

            # Backup logrotate config if it exists
            if [ -f "/etc/logrotate.d/sai-cam" ]; then
                sudo cp "/etc/logrotate.d/sai-cam" "$BACKUP_DIR/$TIMESTAMP/"
                echo "Logrotate config backup created at: $BACKUP_DIR/$TIMESTAMP/sai-cam"
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

# Create directories
sudo mkdir -p $INSTALL_DIR/bin
sudo mkdir -p $INSTALL_DIR/storage
sudo mkdir -p $CONFIG_DIR
sudo mkdir -p $LOG_DIR

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-opencv python3-venv

# Set up virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv $INSTALL_DIR/venv
source $INSTALL_DIR/venv/bin/activate
$INSTALL_DIR/venv/bin/pip3 install -r $PROJECT_ROOT/requirements.txt

# Copy files
echo "Copying service files..."
sudo cp $PROJECT_ROOT/src/camera_service.py $INSTALL_DIR/bin/
sudo cp $PROJECT_ROOT/config/config.yaml $CONFIG_DIR/
sudo cp $PROJECT_ROOT/systemd/camera-service.service /etc/systemd/system/sai-cam.service
sudo cp $PROJECT_ROOT/systemd/logrotate.conf /etc/logrotate.d/sai-cam

# Set permissions
echo "Setting file permissions..."
sudo chown -R admin:admin $INSTALL_DIR
sudo chown -R admin:admin $LOG_DIR
sudo chmod 644 $CONFIG_DIR/config.yaml
sudo chmod 644 /etc/systemd/system/sai-cam.service
sudo chmod 644 /etc/logrotate.d/sai-cam
sudo chmod 755 $INSTALL_DIR/bin/camera_service.py

# Enable and start service
echo "Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable sai-cam
sudo systemctl start sai-cam

echo "Installation completed successfully!"
echo "Service status:"
sudo systemctl status sai-cam
