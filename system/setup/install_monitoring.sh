#!/bin/bash

# DEPRECATED: Monitoring is now integrated into scripts/install.sh
# This script is kept for reference only.
#
# To install monitoring, run: sudo ./scripts/install.sh
# The main installer now handles:
#   - Hardware watchdog setup
#   - Cron job configuration
#   - Log rotation
#   - Scheduled weekly reboot
#
# See system/README.md for more information.

echo "WARNING: This script is deprecated."
echo "Monitoring is now installed automatically by scripts/install.sh"
echo ""
echo "If you need to manually reinstall monitoring, run:"
echo "  sudo ./scripts/install.sh --preserve-config"
exit 0

# --- DEPRECATED CODE BELOW ---

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAI_CAM_DIR="/opt/sai-cam"
SYSTEM_DIR="${SAI_CAM_DIR}/system"

echo "SAI-CAM System Monitoring Setup"
echo "================================"

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root or with sudo"
    exit 1
fi

# Step 1: Enable hardware watchdog
echo "1. Configuring hardware watchdog..."
modprobe bcm2835_wdt
echo "bcm2835_wdt" >> /etc/modules-load.d/watchdog.conf

# Install watchdog package
apt-get update
apt-get install -y watchdog

# Configure watchdog
cp "${SYSTEM_DIR}/config/watchdog.conf" /etc/watchdog.conf
systemctl enable watchdog
systemctl restart watchdog

# Step 2: Create log directories
echo "2. Creating log directories..."
mkdir -p /var/log/sai-cam
chown admin:admin /var/log/sai-cam

# Step 3: Install monitoring scripts
echo "3. Installing monitoring scripts..."
chmod +x "${SYSTEM_DIR}/monitoring/"*.sh

# Step 4: Setup cron jobs
echo "4. Setting up cron jobs..."
CRON_FILE="/etc/cron.d/sai-cam-monitoring"
cat > "$CRON_FILE" << EOF
# SAI-CAM System Monitoring Cron Jobs
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# System monitoring - every 5 minutes
*/5 * * * * admin ${SYSTEM_DIR}/monitoring/system_monitor.sh >/dev/null 2>&1

# Service watchdog - every 10 minutes
*/10 * * * * root ${SYSTEM_DIR}/monitoring/service_watchdog.sh >/dev/null 2>&1

# Log cleanup - weekly on Sunday at 2 AM
0 2 * * 0 root ${SYSTEM_DIR}/monitoring/cleanup_logs.sh >/dev/null 2>&1

# Storage cleanup - daily at 3 AM
0 3 * * * admin ${SYSTEM_DIR}/monitoring/cleanup_storage.sh >/dev/null 2>&1
EOF

# Step 5: Setup log rotation
echo "5. Configuring log rotation..."
cp "${SYSTEM_DIR}/config/logrotate.conf" /etc/logrotate.d/sai-cam

# Step 6: Update sai-cam service with better watchdog support
echo "6. Updating sai-cam service configuration..."
if [ -f /etc/systemd/system/sai-cam.service ]; then
    cp /etc/systemd/system/sai-cam.service /etc/systemd/system/sai-cam.service.backup
fi

cat > /etc/systemd/system/sai-cam.service << 'EOF'
[Unit]
Description=SAI Camera Service
After=network-online.target zerotier-one.service
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=admin
Group=admin
WorkingDirectory=/opt/sai-cam
Environment=PYTHONPATH=/opt/sai-cam
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/sai-cam/venv/bin/python3 /opt/sai-cam/bin/camera_service.py
Restart=always
RestartSec=10

# Watchdog configuration
WatchdogSec=30
NotifyAccess=all

# Resource limits
MemoryMax=512M
CPUQuota=80%

# Process management
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

# Security
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/sai-cam/storage /var/log/sai-cam

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl restart sai-cam

# Step 7: Create monitoring dashboard script
echo "7. Creating monitoring dashboard..."
cat > "${SAI_CAM_DIR}/check_health.sh" << 'EOF'
#!/bin/bash

echo "SAI-CAM System Health Check"
echo "==========================="
echo

echo "System Resources:"
echo "-----------------"
echo "Temperature: $(vcgencmd measure_temp | cut -d= -f2)"
echo "CPU Usage: $(top -bn1 | grep "Cpu(s)" | awk '{print $2+$4}')%"
echo "Memory: $(free -h | grep Mem | awk '{print $3 "/" $2}')"
echo "Disk: $(df -h /opt/sai-cam | tail -1 | awk '{print $3 "/" $2 " (" $5 ")"}')"
echo

echo "Services Status:"
echo "----------------"
systemctl is-active sai-cam && echo "✓ sai-cam: running" || echo "✗ sai-cam: stopped"
systemctl is-active watchdog && echo "✓ watchdog: running" || echo "✗ watchdog: stopped"
systemctl is-active zerotier-one && echo "✓ zerotier: running" || echo "✗ zerotier: stopped"
echo

echo "Recent Warnings (last 20 lines):"
echo "---------------------------------"
grep -E "WARNING|ERROR|CRITICAL" /var/log/sai-cam/system_monitor.log 2>/dev/null | tail -20 || echo "No recent warnings"
echo

echo "Storage Usage:"
echo "--------------"
du -sh /opt/sai-cam/storage/* 2>/dev/null | head -10 || echo "No storage data"
EOF

chmod +x "${SAI_CAM_DIR}/check_health.sh"

# Step 8: Test monitoring
echo "8. Testing monitoring setup..."
"${SYSTEM_DIR}/monitoring/system_monitor.sh"

echo
echo "Installation complete!"
echo "======================"
echo
echo "Monitoring is now active with:"
echo "  - Hardware watchdog (15s timeout)"
echo "  - System monitoring (every 5 minutes)"
echo "  - Service watchdog (every 10 minutes)" 
echo "  - Automatic log rotation"
echo
echo "Check system health with: ${SAI_CAM_DIR}/check_health.sh"
echo "View logs at: /var/log/sai-cam/"
echo
echo "The system will automatically reboot if it becomes unresponsive."