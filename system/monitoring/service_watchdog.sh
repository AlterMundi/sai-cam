#!/bin/bash

# SAI-CAM Service Watchdog
# Monitors and restarts critical services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGFILE="/var/log/sai-cam/service_watchdog.log"

# Service restart limits
MAX_RESTART_ATTEMPTS=3
RESTART_WINDOW=300  # 5 minutes

log_message() {
    mkdir -p "$(dirname "$LOGFILE")"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}

get_restart_count() {
    local service=$1
    local count_file="/tmp/${service}_restart_count"
    local window_file="/tmp/${service}_restart_window"
    
    if [ -f "$window_file" ]; then
        local last_time=$(cat "$window_file")
        local current_time=$(date +%s)
        local time_diff=$((current_time - last_time))
        
        if [ "$time_diff" -gt "$RESTART_WINDOW" ]; then
            # Reset counter if outside window
            echo "0" > "$count_file"
            echo "$current_time" > "$window_file"
        fi
    else
        echo "$(date +%s)" > "$window_file"
        echo "0" > "$count_file"
    fi
    
    cat "$count_file" 2>/dev/null || echo "0"
}

increment_restart_count() {
    local service=$1
    local count_file="/tmp/${service}_restart_count"
    local current_count=$(get_restart_count "$service")
    echo $((current_count + 1)) > "$count_file"
}

check_and_restart_service() {
    local service_name="$1"
    local process_pattern="$2"
    local restart_count=$(get_restart_count "$service_name")
    
    # Check if service is enabled
    if ! systemctl is-enabled --quiet "$service_name" 2>/dev/null; then
        return 0  # Skip if service is not enabled
    fi
    
    # Check if process is running
    if ! pgrep -f "$process_pattern" > /dev/null; then
        log_message "Service $service_name not running (pattern: $process_pattern)"
        
        if [ "$restart_count" -ge "$MAX_RESTART_ATTEMPTS" ]; then
            log_message "ERROR: Max restart attempts ($MAX_RESTART_ATTEMPTS) reached for $service_name"
            return 1
        fi
        
        log_message "Attempting to restart $service_name (attempt $((restart_count + 1))/$MAX_RESTART_ATTEMPTS)"
        systemctl restart "$service_name" 2>&1 | tee -a "$LOGFILE"
        
        sleep 5
        
        if pgrep -f "$process_pattern" > /dev/null; then
            log_message "Successfully restarted $service_name"
            increment_restart_count "$service_name"
        else
            log_message "ERROR: Failed to restart $service_name"
            increment_restart_count "$service_name"
            return 1
        fi
    fi
    
    return 0
}

check_sai_cam_health() {
    # Check if sai-cam service is healthy
    if systemctl is-active --quiet sai-cam; then
        # Additional health checks
        local pid=$(systemctl show -p MainPID sai-cam | cut -d= -f2)
        if [ "$pid" != "0" ]; then
            # Check CPU usage of the process
            local cpu_usage=$(ps -p "$pid" -o %cpu= 2>/dev/null | tr -d ' ')
            if [ -n "$cpu_usage" ]; then
                cpu_int=${cpu_usage%.*}
                if [ "$cpu_int" -gt 95 ]; then
                    log_message "WARNING: sai-cam using ${cpu_usage}% CPU"
                fi
            fi
            
            # Check memory usage
            local mem_usage=$(ps -p "$pid" -o %mem= 2>/dev/null | tr -d ' ')
            if [ -n "$mem_usage" ]; then
                mem_int=${mem_usage%.*}
                if [ "$mem_int" -gt 50 ]; then
                    log_message "WARNING: sai-cam using ${mem_usage}% memory"
                fi
            fi
        fi
    else
        check_and_restart_service "sai-cam" "camera_service.py"
    fi
}

check_hung_processes() {
    # Check for processes in uninterruptible sleep (D state)
    local hung_count=$(ps aux | awk '$8 ~ /^D/ {count++} END {print count+0}')
    
    if [ "$hung_count" -gt 3 ]; then
        log_message "WARNING: $hung_count processes in uninterruptible sleep state"
        
        # List the hung processes
        ps aux | awk '$8 ~ /^D/ {print $2, $11}' | while read pid cmd; do
            log_message "  Hung process: PID=$pid CMD=$cmd"
        done
        
        # Critical threshold - schedule reboot
        if [ "$hung_count" -gt 5 ]; then
            log_message "CRITICAL: Too many hung processes ($hung_count)"
            
            # Check if a reboot is already scheduled
            if ! shutdown -c 2>/dev/null; then
                log_message "Scheduling emergency reboot in 2 minutes"
                shutdown -r +2 "Emergency reboot due to hung processes" &
            fi
        fi
    fi
}

# Main execution
log_message "Starting service watchdog check"

# Check critical system services
check_and_restart_service "NetworkManager" "NetworkManager"
check_and_restart_service "ssh" "sshd"
check_and_restart_service "zerotier-one" "zerotier-one"

# Check sai-cam specific health
check_sai_cam_health

# Check for system issues
check_hung_processes

# Clean up old restart count files (older than 1 hour)
find /tmp -name "*_restart_count" -mmin +60 -delete 2>/dev/null
find /tmp -name "*_restart_window" -mmin +60 -delete 2>/dev/null

log_message "Service watchdog check completed"
exit 0