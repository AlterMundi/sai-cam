#!/bin/bash

# SAI-CAM Storage Management Script
# Manages camera recordings and maintains storage health

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGFILE="/var/log/sai-cam/storage.log"
SAI_CAM_STORAGE="/opt/sai-cam/storage"

# Storage thresholds
MAX_STORAGE_GB=${MAX_STORAGE_GB:-10}  # Maximum storage size in GB
MIN_FREE_SPACE_GB=${MIN_FREE_SPACE_GB:-2}  # Minimum free space in GB

log_message() {
    mkdir -p "$(dirname "$LOGFILE")"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOGFILE"
}

get_storage_size_gb() {
    local size_kb=$(du -s "$SAI_CAM_STORAGE" 2>/dev/null | cut -f1)
    echo $((size_kb / 1024 / 1024))
}

get_free_space_gb() {
    local free_kb=$(df /opt/sai-cam | tail -1 | awk '{print $4}')
    echo $((free_kb / 1024 / 1024))
}

organize_by_date() {
    # Organize recordings by date if not already organized
    local base_dir="$1"
    local file_pattern="$2"
    
    find "$base_dir" -maxdepth 1 -type f -name "$file_pattern" 2>/dev/null | while read file; do
        local date_dir=$(date -r "$file" +%Y-%m-%d)
        local target_dir="$base_dir/$date_dir"
        
        mkdir -p "$target_dir"
        mv "$file" "$target_dir/" 2>/dev/null
    done
}

cleanup_by_size() {
    local current_size=$(get_storage_size_gb)
    local free_space=$(get_free_space_gb)
    
    if [ "$current_size" -gt "$MAX_STORAGE_GB" ] || [ "$free_space" -lt "$MIN_FREE_SPACE_GB" ]; then
        log_message "Storage cleanup triggered: ${current_size}GB used, ${free_space}GB free"
        
        # Delete oldest files first
        find "$SAI_CAM_STORAGE" -type f \( -name "*.mp4" -o -name "*.jpg" \) -printf '%T+ %p\n' | \
            sort | head -100 | cut -d' ' -f2- | while read file; do
            rm -f "$file"
            log_message "Deleted: $file"
            
            # Check if we've freed enough space
            new_size=$(get_storage_size_gb)
            new_free=$(get_free_space_gb)
            if [ "$new_size" -le "$MAX_STORAGE_GB" ] && [ "$new_free" -ge "$MIN_FREE_SPACE_GB" ]; then
                break
            fi
        done
    fi
}

verify_recordings() {
    # Check for corrupted video files
    find "$SAI_CAM_STORAGE" -type f -name "*.mp4" -size -1k -delete -print 2>/dev/null | while read file; do
        log_message "Deleted corrupted file: $file"
    done
}

generate_report() {
    local total_videos=$(find "$SAI_CAM_STORAGE" -type f -name "*.mp4" 2>/dev/null | wc -l)
    local total_images=$(find "$SAI_CAM_STORAGE" -type f \( -name "*.jpg" -o -name "*.png" \) 2>/dev/null | wc -l)
    local storage_size=$(get_storage_size_gb)
    local free_space=$(get_free_space_gb)
    
    log_message "Storage Report: Videos=$total_videos, Images=$total_images, Used=${storage_size}GB, Free=${free_space}GB"
}

# Main execution
log_message "Starting storage management"

# Create storage directories if they don't exist
mkdir -p "${SAI_CAM_STORAGE}"/{videos,images,thumbnails,logs}

# Organize files by date
organize_by_date "${SAI_CAM_STORAGE}/videos" "*.mp4"
organize_by_date "${SAI_CAM_STORAGE}/images" "*.jpg"

# Verify and cleanup corrupted files
verify_recordings

# Cleanup by size if needed
cleanup_by_size

# Generate storage report
generate_report

log_message "Storage management complete"
exit 0