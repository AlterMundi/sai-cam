#!/bin/bash

# SAI-CAM System Monitor
# Monitors system health and camera service status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGFILE="/var/log/sai-cam/system_monitor.log"

# Load environment if available
if [ -f "/opt/sai-cam/.env" ]; then
    export $(grep -v '^#' /opt/sai-cam/.env | xargs)
fi

# Configurable thresholds
ALERT_THRESHOLD_TEMP=${MONITOR_TEMP_THRESHOLD:-70}
ALERT_THRESHOLD_CPU=${MONITOR_CPU_THRESHOLD:-90}
ALERT_THRESHOLD_MEM=${MONITOR_MEM_THRESHOLD:-90}
ALERT_THRESHOLD_DISK=${MONITOR_DISK_THRESHOLD:-85}

log_message() {
    mkdir -p "$(dirname "$LOGFILE")"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}

check_temperature() {
    if command -v vcgencmd &> /dev/null; then
        temp=$(vcgencmd measure_temp | grep -o '[0-9]*\.[0-9]*')
        temp_int=${temp%.*}
        if [ "$temp_int" -gt "$ALERT_THRESHOLD_TEMP" ]; then
            log_message "WARNING: High temperature: ${temp}°C"
            return 1
        fi
        echo "$temp"
    else
        echo "N/A"
    fi
}

check_cpu_usage() {
    cpu_usage=$(top -bn1 | grep "Cpu(s)" | awk '{print $2+$4}' | cut -d'%' -f1)
    cpu_int=${cpu_usage%.*}
    if [ "$cpu_int" -gt "$ALERT_THRESHOLD_CPU" ]; then
        log_message "WARNING: High CPU usage: ${cpu_usage}%"
        return 1
    fi
    echo "$cpu_usage"
}

check_memory() {
    mem_usage=$(free | grep Mem | awk '{printf("%.1f"), $3/$2 * 100.0}')
    mem_int=${mem_usage%.*}
    if [ "$mem_int" -gt "$ALERT_THRESHOLD_MEM" ]; then
        log_message "WARNING: High memory usage: ${mem_usage}%"
        # Log top memory consumers
        log_message "Top memory users: $(ps aux --sort=-%mem | head -3 | tail -2 | awk '{print $11 ":" $4"%"}')"
        return 1
    fi
    echo "$mem_usage"
}

check_disk_usage() {
    disk_usage=$(df /opt/sai-cam | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$disk_usage" -gt "$ALERT_THRESHOLD_DISK" ]; then
        log_message "WARNING: High disk usage: ${disk_usage}%"
        # Check storage directory size
        storage_size=$(du -sh /opt/sai-cam/storage 2>/dev/null | cut -f1)
        log_message "Storage directory size: ${storage_size}"
        return 1
    fi
    echo "$disk_usage"
}

check_sai_cam_service() {
    if ! systemctl is-active --quiet sai-cam; then
        log_message "ERROR: sai-cam service is not running"
        return 1
    fi
    
    # Check if camera process is responsive
    if ! pgrep -f "camera_service.py" > /dev/null; then
        log_message "WARNING: camera_service.py process not found"
        return 1
    fi
    
    # Check for zombie processes
    zombie_count=$(ps aux | awk '$8 ~ /^Z/ {count++} END {print count+0}')
    if [ "$zombie_count" -gt 0 ]; then
        log_message "WARNING: $zombie_count zombie process(es) detected"
    fi
    
    echo "OK"
}

check_network_connectivity() {
    # Check if ZeroTier is running
    if systemctl is-active --quiet zerotier-one; then
        zt_status="UP"
    else
        zt_status="DOWN"
        log_message "WARNING: ZeroTier service is down"
    fi
    
    # Check network connectivity
    if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
        net_status="OK"
    else
        net_status="NO_INTERNET"
        log_message "WARNING: No internet connectivity"
    fi
    
    echo "Network: $net_status, ZeroTier: $zt_status"
}

# Main monitoring
temp=$(check_temperature)
cpu=$(check_cpu_usage)
mem=$(check_memory)
disk=$(check_disk_usage)
sai_cam=$(check_sai_cam_service)
network=$(check_network_connectivity)

# Log status
log_message "STATUS: Temp=${temp}°C CPU=${cpu}% MEM=${mem}% DISK=${disk}% Service=${sai_cam} ${network}"

# Check for hung processes
hung_processes=$(ps aux | awk '$8 ~ /^D/ {print $2, $11}')
if [ -n "$hung_processes" ]; then
    log_message "WARNING: Detected hung processes in D state: $hung_processes"
fi

# Alert on critical conditions
critical=0
[ "$cpu_int" -gt "$ALERT_THRESHOLD_CPU" ] && critical=$((critical + 1))
[ "$mem_int" -gt "$ALERT_THRESHOLD_MEM" ] && critical=$((critical + 1))
[ "$disk_usage" -gt "$ALERT_THRESHOLD_DISK" ] && critical=$((critical + 1))

if [ "$critical" -ge 2 ]; then
    log_message "CRITICAL: Multiple system resources at critical levels"
fi

exit 0