# SAI-CAM System Monitoring

Comprehensive monitoring and watchdog system for SAI-CAM on Raspberry Pi.

## Features

- **Hardware Watchdog**: Automatic system reboot on hang (15-second timeout)
- **Service Monitoring**: Auto-restart of critical services
- **Resource Monitoring**: CPU, memory, temperature, and disk usage tracking
- **Storage Management**: Automatic cleanup of old recordings
- **Log Rotation**: Prevents log files from filling disk space

## Quick Start

```bash
# Install monitoring system
sudo /opt/sai-cam/system/setup/install_monitoring.sh

# Check system health
/opt/sai-cam/check_health.sh
```

## Directory Structure

```
system/
├── monitoring/         # Monitoring scripts
│   ├── system_monitor.sh      # System resource monitoring
│   ├── service_watchdog.sh    # Service health checks
│   ├── cleanup_logs.sh        # Log cleanup
│   └── cleanup_storage.sh     # Storage management
├── setup/             # Installation scripts
│   └── install_monitoring.sh  # One-command setup
└── config/            # Configuration files
    ├── watchdog.conf          # Hardware watchdog config
    └── logrotate.conf         # Log rotation config
```

## Configuration

### Environment Variables

Add to `/opt/sai-cam/.env`:

```bash
# Monitoring thresholds
MONITOR_TEMP_THRESHOLD=70      # Temperature warning (°C)
MONITOR_CPU_THRESHOLD=90       # CPU usage warning (%)
MONITOR_MEM_THRESHOLD=90       # Memory usage warning (%)
MONITOR_DISK_THRESHOLD=85      # Disk usage warning (%)

# Storage management
MAX_STORAGE_GB=10              # Maximum storage size
MIN_FREE_SPACE_GB=2            # Minimum free space
VIDEO_RETENTION_DAYS=7         # Video retention period
IMAGE_RETENTION_DAYS=14        # Image retention period
LOG_RETENTION_DAYS=7           # Log retention period
```

### Cron Schedule

Default schedule (configured automatically):
- System monitoring: Every 5 minutes
- Service watchdog: Every 10 minutes  
- Storage cleanup: Daily at 3 AM
- Log cleanup: Weekly on Sunday at 2 AM

## Manual Commands

```bash
# Run system monitor manually
/opt/sai-cam/system/monitoring/system_monitor.sh

# Check service health
sudo /opt/sai-cam/system/monitoring/service_watchdog.sh

# Force storage cleanup
/opt/sai-cam/system/monitoring/cleanup_storage.sh

# View recent warnings
grep -E "WARNING|ERROR" /var/log/sai-cam/system_monitor.log | tail -20

# Check watchdog status
sudo systemctl status watchdog
```

## Logs

Monitor logs are stored in `/var/log/sai-cam/`:
- `system_monitor.log` - Resource monitoring
- `service_watchdog.log` - Service health checks
- `storage.log` - Storage management
- `cleanup.log` - Cleanup operations

## Troubleshooting

### System keeps rebooting
1. Check watchdog timeout: `grep timeout /etc/watchdog.conf`
2. Review system load: `grep WARNING /var/log/sai-cam/system_monitor.log`
3. Temporarily disable: `sudo systemctl stop watchdog`

### Services not restarting
1. Check restart limits: `grep MAX_RESTART /opt/sai-cam/system/monitoring/service_watchdog.sh`
2. Review service logs: `journalctl -u sai-cam -n 50`
3. Reset restart counters: `rm /tmp/*_restart_*`

### Storage filling up
1. Check retention settings in `.env`
2. Run manual cleanup: `sudo /opt/sai-cam/system/monitoring/cleanup_storage.sh`
3. Review storage report: `tail /var/log/sai-cam/storage.log`

## Integration with Git

To add to your repository:

```bash
cd /opt/sai-cam
git add system/
git commit -m "Add system monitoring and watchdog"
git push
```

## Uninstall

To remove monitoring:

```bash
# Disable services
sudo systemctl disable watchdog
sudo rm /etc/cron.d/sai-cam-monitoring
sudo rm /etc/logrotate.d/sai-cam

# Remove logs (optional)
sudo rm -rf /var/log/sai-cam
```

## Safety Features

- **Restart Limits**: Services won't restart more than 3 times in 5 minutes
- **Emergency Cleanup**: Aggressive cleanup when disk usage exceeds 90%
- **Graceful Degradation**: Monitoring continues even if some checks fail
- **Process Protection**: Critical processes are protected from accidental termination

## Performance Impact

The monitoring system has minimal impact:
- CPU: <1% average usage
- Memory: <10MB RSS
- Disk I/O: Negligible (logs are buffered)

## Support

For issues or improvements, check:
- System health: `/opt/sai-cam/check_health.sh`
- Recent logs: `journalctl -f -u sai-cam`
- Monitoring logs: `/var/log/sai-cam/`