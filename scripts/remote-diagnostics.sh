#!/bin/bash
# SAI-Cam Remote Node Diagnostics Script
# Usage: ./scripts/remote-diagnostics.sh [hostname]
# Example: ./scripts/remote-diagnostics.sh admin@saicam5.local

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default host
HOST="${1:-admin@saicam5.local}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}SAI-Cam Remote Node Diagnostics${NC}"
echo -e "${BLUE}Target: ${HOST}${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to run remote command
run_remote() {
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$HOST" "$1" 2>&1
}

# Function to print section header
section() {
    echo -e "\n${BLUE}=== $1 ===${NC}"
}

# Function to print status
status() {
    local level=$1
    shift
    case $level in
        OK) echo -e "${GREEN}✓${NC} $*" ;;
        WARN) echo -e "${YELLOW}⚠${NC} $*" ;;
        ERROR) echo -e "${RED}✗${NC} $*" ;;
        INFO) echo -e "  $*" ;;
    esac
}

# Check connectivity
section "Network Connectivity"
if ping -c 1 -W 2 "${HOST#*@}" &>/dev/null; then
    status OK "Host is reachable"
else
    status ERROR "Host is NOT reachable"
    exit 1
fi

if run_remote "echo 'SSH OK'" | grep -q "SSH OK"; then
    status OK "SSH connection successful"
else
    status ERROR "SSH connection failed"
    exit 1
fi

# System information
section "System Information"
HOSTNAME=$(run_remote "hostname")
UPTIME=$(run_remote "uptime -p")
KERNEL=$(run_remote "uname -r")
status INFO "Hostname: $HOSTNAME"
status INFO "Uptime: $UPTIME"
status INFO "Kernel: $KERNEL"

# Service status
section "SAI-Cam Service Status"
SERVICE_STATUS=$(run_remote "systemctl is-active sai-cam 2>&1" || echo "inactive")
if [ "$SERVICE_STATUS" = "active" ]; then
    status OK "Service is running"

    PID=$(run_remote "systemctl show -p MainPID --value sai-cam")
    MEMORY=$(run_remote "ps -p $PID -o rss= 2>/dev/null | awk '{printf \"%.1f MB\", \$1/1024}'")
    CPU=$(run_remote "ps -p $PID -o %cpu= 2>/dev/null")
    SINCE=$(run_remote "systemctl show -p ActiveEnterTimestamp --value sai-cam | awk '{print \$2, \$3}'")

    status INFO "PID: $PID"
    status INFO "Memory: $MEMORY"
    status INFO "CPU: ${CPU}%"
    status INFO "Running since: $SINCE"
else
    status ERROR "Service is NOT running (status: $SERVICE_STATUS)"
fi

# Resource usage
section "System Resources"
MEM_INFO=$(run_remote "free -h | grep Mem")
MEM_USED=$(echo "$MEM_INFO" | awk '{print $3}')
MEM_TOTAL=$(echo "$MEM_INFO" | awk '{print $2}')
MEM_PERCENT=$(echo "$MEM_INFO" | awk '{printf "%.0f", ($3/$2)*100}')

status INFO "Memory: $MEM_USED / $MEM_TOTAL (${MEM_PERCENT}%)"

if [ "$MEM_PERCENT" -gt 80 ]; then
    status WARN "High memory usage"
fi

DISK_INFO=$(run_remote "df -h / | tail -1")
DISK_USED=$(echo "$DISK_INFO" | awk '{print $3}')
DISK_TOTAL=$(echo "$DISK_INFO" | awk '{print $2}')
DISK_PERCENT=$(echo "$DISK_INFO" | awk '{print $5}' | tr -d '%')

status INFO "Root disk: $DISK_USED / $DISK_TOTAL (${DISK_PERCENT}%)"

if [ "$DISK_PERCENT" -gt 80 ]; then
    status WARN "High disk usage"
fi

# Storage analysis
section "Image Storage"
STORAGE_PATH="/opt/sai-cam/storage"
STORAGE_SIZE=$(run_remote "du -sh $STORAGE_PATH 2>/dev/null | cut -f1" || echo "N/A")
IMAGE_COUNT=$(run_remote "find $STORAGE_PATH -name '*.jpg' 2>/dev/null | wc -l" || echo "0")
OLDEST_IMAGE=$(run_remote "find $STORAGE_PATH -name '*.jpg' -printf '%T+ %p\n' 2>/dev/null | sort | head -1 | cut -d' ' -f1" || echo "N/A")
NEWEST_IMAGE=$(run_remote "find $STORAGE_PATH -name '*.jpg' -printf '%T+ %p\n' 2>/dev/null | sort | tail -1 | cut -d' ' -f1" || echo "N/A")

status INFO "Storage size: $STORAGE_SIZE"
status INFO "Image count: $IMAGE_COUNT"
status INFO "Oldest image: $OLDEST_IMAGE"
status INFO "Newest image: $NEWEST_IMAGE"

# Parse storage size for warning
STORAGE_GB=$(echo "$STORAGE_SIZE" | sed 's/[^0-9.]//g')
STORAGE_UNIT=$(echo "$STORAGE_SIZE" | sed 's/[0-9.]//g')

if [ "$STORAGE_UNIT" = "G" ] && [ "${STORAGE_GB%.*}" -gt 5 ]; then
    status ERROR "Storage exceeds configured limit (5GB)"
elif [ "$IMAGE_COUNT" -gt 10000 ]; then
    status WARN "Large number of images in storage ($IMAGE_COUNT)"
fi

# Camera connectivity
section "Camera Network Connectivity"
CONFIG_PATH="/etc/sai-cam/config.yaml"
if run_remote "test -f $CONFIG_PATH" &>/dev/null; then
    CAMERA_IPS=$(run_remote "grep -A3 'type: .onvif' $CONFIG_PATH | grep 'address:' | awk '{print \$2}' | tr -d \"'\"")

    for IP in $CAMERA_IPS; do
        if run_remote "ping -c 1 -W 2 $IP &>/dev/null"; then
            status OK "Camera $IP reachable"
        else
            status ERROR "Camera $IP NOT reachable"
        fi
    done
else
    status WARN "Config file not found"
fi

# Server connectivity
section "Server Connectivity"
SERVER_URL=$(run_remote "grep 'url:' $CONFIG_PATH 2>/dev/null | awk '{print \$2}' | tr -d \"'\"" || echo "")
if [ -n "$SERVER_URL" ]; then
    SERVER_HOST=$(echo "$SERVER_URL" | sed -E 's|https?://([^/]+).*|\1|')
    status INFO "Server: $SERVER_HOST"

    if run_remote "curl -I --max-time 5 $SERVER_URL &>/dev/null"; then
        status OK "Server is reachable"
    else
        status ERROR "Server is NOT reachable"
    fi
fi

# Recent logs analysis
section "Recent Service Logs (Last 50 lines)"
LOG_FILE="/var/log/sai-cam/camera_service.log"
if run_remote "test -f $LOG_FILE"; then
    ERROR_COUNT=$(run_remote "tail -50 $LOG_FILE | grep -c '\[ERROR\]'" || echo "0")
    WARN_COUNT=$(run_remote "tail -50 $LOG_FILE | grep -c '\[WARNING\]'" || echo "0")

    status INFO "Recent errors: $ERROR_COUNT"
    status INFO "Recent warnings: $WARN_COUNT"

    if [ "$ERROR_COUNT" -gt 10 ]; then
        status ERROR "High error rate in logs"
        echo -e "\n${RED}Last 10 errors:${NC}"
        run_remote "tail -50 $LOG_FILE | grep '\[ERROR\]' | tail -10"
    fi
else
    status WARN "Log file not accessible"
fi

# Camera status from logs
section "Camera Status from Logs"
if run_remote "test -f $LOG_FILE"; then
    CAMERAS=$(run_remote "grep -oP 'Camera \K(cam\d+)' $LOG_FILE | sort -u")

    for CAM in $CAMERAS; do
        LAST_ERROR=$(run_remote "grep 'Camera $CAM' $LOG_FILE | grep ERROR | tail -1" || echo "")
        if echo "$LAST_ERROR" | grep -q "Not connected"; then
            status ERROR "$CAM: Not connected"
        elif echo "$LAST_ERROR" | grep -q "Reconnection failed"; then
            status ERROR "$CAM: Reconnection failed"
        elif [ -z "$LAST_ERROR" ]; then
            status OK "$CAM: No recent errors"
        else
            status WARN "$CAM: Check logs for details"
        fi
    done
fi

# Configuration check
section "Configuration"
if run_remote "test -f $CONFIG_PATH"; then
    CAM_COUNT=$(run_remote "grep -c 'id: .cam' $CONFIG_PATH" || echo "0")
    CAPTURE_INTERVAL=$(run_remote "grep 'capture_interval:' $CONFIG_PATH | head -1 | awk '{print \$2}'")
    MAX_SIZE=$(run_remote "grep 'max_size_gb:' $CONFIG_PATH | awk '{print \$2}'")

    status INFO "Configured cameras: $CAM_COUNT"
    status INFO "Capture interval: ${CAPTURE_INTERVAL}s"
    status INFO "Max storage: ${MAX_SIZE}GB"
else
    status ERROR "Configuration file not found"
fi

# Summary
section "Diagnostic Summary"
echo ""
if [ "$SERVICE_STATUS" = "active" ] && [ "$ERROR_COUNT" -lt 10 ]; then
    status OK "Node appears healthy"
elif [ "$SERVICE_STATUS" != "active" ]; then
    status ERROR "Service not running - requires immediate attention"
else
    status WARN "Node has issues - review errors above"
fi

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Diagnostics complete${NC}"
echo -e "${BLUE}========================================${NC}"
