#!/bin/bash

# Exit on any error
set -e

# Define variables
SERVICE_USER="admin"
SERVICE_GROUP="admin"
BASE_DIR="/home/$SERVICE_USER/camera_service"
VENV_DIR="$BASE_DIR/venv"
STORAGE_DIR="/home/$SERVICE_USER/camera_storage"
CONFIG_DIR="/etc/camera_service"

# Create necessary directories
sudo mkdir -p $CONFIG_DIR
sudo mkdir -p /var/log/camera_service
mkdir -p $BASE_DIR
mkdir -p $STORAGE_DIR

# Install required system packages
sudo apt-get update
sudo apt-get install -y python3-pip python3-opencv python3-venv python3-full

# Create and activate virtual environment
python3 -m venv $VENV_DIR
source $VENV_DIR/bin/activate

# Install Python packages in virtual environment
$VENV_DIR/bin/pip3 install pyyaml requests psutil watchdog opencv-python

# Copy files
sudo cp config.yaml $CONFIG_DIR/
cp camera_service.py $BASE_DIR/
sudo cp camera_service.service /etc/systemd/system/

# Set permissions
sudo chown -R $SERVICE_USER:$SERVICE_GROUP $BASE_DIR
sudo chown -R $SERVICE_USER:$SERVICE_GROUP $STORAGE_DIR
sudo chown -R $SERVICE_USER:$SERVICE_GROUP /var/log/camera_service
sudo chmod 644 $CONFIG_DIR/config.yaml
sudo chmod 644 /etc/systemd/system/camera_service.service
sudo chmod 755 $BASE_DIR/camera_service.py

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable camera_service
sudo systemctl start camera_service

echo "Installation complete. Service status:"
sudo systemctl status camera_service
