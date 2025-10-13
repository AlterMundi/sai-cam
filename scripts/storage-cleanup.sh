#!/bin/bash
# SAI-Cam Storage Cleanup Utility
# Cleans up old images from local storage when full
#
# Usage:
#   ./scripts/storage-cleanup.sh [storage_path] [max_size_gb]
#   ./scripts/storage-cleanup.sh /opt/sai-cam/storage 5

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default values
STORAGE_PATH="${1:-/opt/sai-cam/storage}"
MAX_SIZE_GB="${2:-5}"
MAX_SIZE_BYTES=$((MAX_SIZE_GB * 1024 * 1024 * 1024))

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}SAI-Cam Storage Cleanup Utility${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${BLUE}Storage path: ${STORAGE_PATH}${NC}"
echo -e "${BLUE}Max size: ${MAX_SIZE_GB}GB${NC}"
echo ""

# Check if storage path exists
if [ ! -d "$STORAGE_PATH" ]; then
    echo -e "${RED}✗ Storage path does not exist: $STORAGE_PATH${NC}"
    exit 1
fi

# Get current size
echo -e "${YELLOW}Analyzing storage...${NC}"
CURRENT_SIZE=$(du -sb "$STORAGE_PATH" | cut -f1)
CURRENT_SIZE_GB=$(echo "scale=2; $CURRENT_SIZE / 1024 / 1024 / 1024" | bc)
IMAGE_COUNT=$(find "$STORAGE_PATH" -name "*.jpg" -type f | wc -l)

echo -e "${BLUE}Current size: ${CURRENT_SIZE_GB}GB${NC}"
echo -e "${BLUE}Image count: ${IMAGE_COUNT}${NC}"

# Check if cleanup needed
if [ "$CURRENT_SIZE" -lt "$MAX_SIZE_BYTES" ]; then
    echo -e "${GREEN}✓ Storage is within limit. No cleanup needed.${NC}"
    exit 0
fi

OVER_SIZE=$((CURRENT_SIZE - MAX_SIZE_BYTES))
OVER_SIZE_GB=$(echo "scale=2; $OVER_SIZE / 1024 / 1024 / 1024" | bc)

echo -e "${YELLOW}⚠ Storage exceeds limit by ${OVER_SIZE_GB}GB${NC}"
echo -e "${YELLOW}Cleanup required!${NC}"
echo ""

# Calculate target size (cleanup to 80% of max to avoid immediate refill)
TARGET_SIZE=$((MAX_SIZE_BYTES * 80 / 100))
BYTES_TO_DELETE=$((CURRENT_SIZE - TARGET_SIZE))
BYTES_TO_DELETE_GB=$(echo "scale=2; $BYTES_TO_DELETE / 1024 / 1024 / 1024" | bc)

echo -e "${BLUE}Target size: $(echo "scale=2; $TARGET_SIZE / 1024 / 1024 / 1024" | bc)GB (80% of max)${NC}"
echo -e "${BLUE}Need to delete: ${BYTES_TO_DELETE_GB}GB${NC}"
echo ""

# Ask for confirmation
read -p "$(echo -e ${YELLOW}Continue with cleanup? [y/N]: ${NC})" -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cleanup cancelled${NC}"
    exit 0
fi

# Find and delete oldest files
echo -e "${YELLOW}Finding oldest images...${NC}"

DELETED_COUNT=0
DELETED_SIZE=0

# Get list of files sorted by age (oldest first)
find "$STORAGE_PATH" -name "*.jpg" -type f -printf '%T@ %s %p\n' | sort -n | while read timestamp size filepath; do
    if [ "$DELETED_SIZE" -ge "$BYTES_TO_DELETE" ]; then
        break
    fi

    # Delete file
    rm -f "$filepath"
    DELETED_SIZE=$((DELETED_SIZE + size))
    DELETED_COUNT=$((DELETED_COUNT + 1))

    # Show progress every 100 files
    if [ $((DELETED_COUNT % 100)) -eq 0 ]; then
        DELETED_GB=$(echo "scale=2; $DELETED_SIZE / 1024 / 1024 / 1024" | bc)
        echo -e "${BLUE}  Deleted ${DELETED_COUNT} files (${DELETED_GB}GB)${NC}"
    fi
done

# Final stats
NEW_SIZE=$(du -sb "$STORAGE_PATH" | cut -f1)
NEW_SIZE_GB=$(echo "scale=2; $NEW_SIZE / 1024 / 1024 / 1024" | bc)
NEW_COUNT=$(find "$STORAGE_PATH" -name "*.jpg" -type f | wc -l)

echo ""
echo -e "${GREEN}✓ Cleanup complete!${NC}"
echo -e "${BLUE}Files deleted: ${DELETED_COUNT}${NC}"
echo -e "${BLUE}New size: ${NEW_SIZE_GB}GB${NC}"
echo -e "${BLUE}Remaining images: ${NEW_COUNT}${NC}"
echo ""
echo -e "${GREEN}Storage is now within limit.${NC}"
