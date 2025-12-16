# SAI-CAM System Monitoring

System monitoring and watchdog components for long-term SAI-CAM stability.

**Note:** Monitoring is now automatically installed by the main `scripts/install.sh`.

## Features

- **Hardware Watchdog**: Automatic system reboot on hang (15-second timeout, Raspberry Pi)
- **Systemd Watchdog**: Service restart if camera_service.py stops responding (60s)
- **Service Monitoring**: Auto-restart of critical services via cron
- **Resource Monitoring**: CPU, memory, temperature, and disk usage tracking
- **Storage Management**: Automatic cleanup of old images
- **Log Rotation**: Prevents log files from filling disk space
- **Scheduled Reboot**: Daily reboot for long-term stability (4 AM)

## Scheduled Tasks

After installation, the following cron jobs run automatically:

| Task | Schedule | Description |
|------|----------|-------------|
| System monitor | Every 5 min | Check CPU, memory, temp, disk |
| Service watchdog | Every 10 min | Verify services are running |
| Storage cleanup | Sunday 3 AM | Remove old images |
| Log cleanup | Sunday 2 AM | Clean old log files |
| Daily reboot | Daily 4 AM | Preventive maintenance reboot |

## Manual Commands

```bash
# Check system health
/opt/sai-cam/check_health.sh

# Run system monitor manually
/opt/sai-cam/system/monitoring/system_monitor.sh

# Check service health
sudo /opt/sai-cam/system/monitoring/service_watchdog.sh

# Force storage cleanup
/opt/sai-cam/system/monitoring/cleanup_storage.sh

# Check watchdog status
sudo systemctl status watchdog
```

## Logs

Monitor logs are stored in `/var/log/sai-cam/`:
- `camera_service.log` - Main service log
- `system_monitor.log` - Resource monitoring (if enabled)
- `service.log` - Systemd stdout
- `error.log` - Systemd stderr

## Troubleshooting

### System keeps rebooting
1. Check hardware watchdog: `grep timeout /etc/watchdog.conf`
2. Review system load: `grep WARNING /var/log/sai-cam/system_monitor.log`
3. Temporarily disable: `sudo systemctl stop watchdog`

### Services not restarting
1. Check systemd status: `systemctl status sai-cam`
2. Review service logs: `journalctl -u sai-cam -n 50`
3. Check cron is running: `systemctl status cron`

### Storage filling up
1. Check current usage: `du -sh /opt/sai-cam/storage`
2. Run manual cleanup: `/opt/sai-cam/system/monitoring/cleanup_storage.sh`
3. Check retention settings in config.yaml

## Disabling Features

```bash
# Disable scheduled reboot
sudo sed -i '/shutdown -r/d' /etc/cron.d/sai-cam

# Disable hardware watchdog
sudo systemctl disable watchdog
sudo systemctl stop watchdog

# Remove all cron jobs
sudo rm /etc/cron.d/sai-cam
```
