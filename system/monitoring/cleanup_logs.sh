#!/bin/bash

# SAI-CAM Log and Storage Cleanup Script
# Manages disk space by cleaning old logs and recordings

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGFILE="/var/log/sai-cam/cleanup.log"
SAI_CAM_STORAGE="/opt/sai-cam/storage"

# Retention periods (in days)
VIDEO_RETENTION=${VIDEO_RETENTION_DAYS:-7}
IMAGE_RETENTION=${IMAGE_RETENTION_DAYS:-14}
LOG_RETENTION=${LOG_RETENTION_DAYS:-7}

log_message() {
    mkdir -p "$(dirname "$LOGFILE")"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}

get_disk_usage() {
    df /opt/sai-cam | tail -1 | awk '{print $5}' | sed 's/%//'
}

cleanup_old_videos() {
    local count=0
    if [ -d "${SAI_CAM_STORAGE}/videos" ]; then
        count=$(find "${SAI_CAM_STORAGE}/videos" -type f -name "*.mp4" -mtime +${VIDEO_RETENTION} -delete -print 2>/dev/null | wc -l)
        [ "$count" -gt 0 ] && log_message "Deleted $count video files older than ${VIDEO_RETENTION} days"
    fi
}

cleanup_old_images() {
    local count=0
    if [ -d "${SAI_CAM_STORAGE}/images" ]; then
        count=$(find "${SAI_CAM_STORAGE}/images" -type f \( -name "*.jpg" -o -name "*.png" \) -mtime +${IMAGE_RETENTION} -delete -print 2>/dev/null | wc -l)
        [ "$count" -gt 0 ] && log_message "Deleted $count image files older than ${IMAGE_RETENTION} days"
    fi
}

cleanup_system_logs() {
    # Clear journal logs older than specified retention
    journalctl --vacuum-time=${LOG_RETENTION}d 2>/dev/null
    
    # Clean apt cache
    apt-get clean 2>/dev/null
    
    # Remove old kernels (keep current and one previous)
    apt-get autoremove --purge -y 2>/dev/null
    
    # Clear old log files
    find /var/log -type f -name "*.gz" -mtime +${LOG_RETENTION} -delete 2>/dev/null
    find /var/log -type f -name "*.old" -mtime +${LOG_RETENTION} -delete 2>/dev/null
    find /var/log -type f -name "*.[0-9]" -mtime +${LOG_RETENTION} -delete 2>/dev/null
}

cleanup_temp_files() {
    # Clear old temporary files
    find /tmp -type f -atime +1 -delete 2>/dev/null
    find /var/tmp -type f -atime +7 -delete 2>/dev/null
    
    # Clear Python cache if exists
    find /opt/sai-cam -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
}

emergency_cleanup() {
    # More aggressive cleanup if disk usage is critical (>90%)
    local usage=$(get_disk_usage)
    
    if [ "$usage" -gt 90 ]; then
        log_message "CRITICAL: Disk usage at ${usage}%, performing emergency cleanup"
        
        # Delete older videos (3 days instead of 7)
        find "${SAI_CAM_STORAGE}/videos" -type f -name "*.mp4" -mtime +3 -delete 2>/dev/null
        
        # Delete all thumbnails
        rm -rf "${SAI_CAM_STORAGE}/thumbnails/"* 2>/dev/null
        
        # Clear all logs older than 1 day
        find /var/log -type f -mtime +1 -delete 2>/dev/null
        
        # Truncate active log files if they're too large
        find /var/log -type f -size +100M -exec truncate -s 10M {} \; 2>/dev/null
    fi
}

# Main cleanup process
log_message "Starting cleanup process"

initial_usage=$(get_disk_usage)
log_message "Initial disk usage: ${initial_usage}%"

# Perform cleanup tasks
cleanup_old_videos
cleanup_old_images
cleanup_system_logs
cleanup_temp_files

# Check if emergency cleanup is needed
emergency_cleanup

# Report final status
final_usage=$(get_disk_usage)
freed=$((initial_usage - final_usage))

log_message "Cleanup complete. Disk usage: ${final_usage}% (freed ${freed}%)"

# Storage report
if [ -d "${SAI_CAM_STORAGE}" ]; then
    storage_size=$(du -sh "${SAI_CAM_STORAGE}" 2>/dev/null | cut -f1)
    log_message "SAI-CAM storage size: ${storage_size}"
fi

exit 0