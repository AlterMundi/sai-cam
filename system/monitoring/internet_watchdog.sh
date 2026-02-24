#!/bin/bash
# SAI-CAM Internet Watchdog
# Monitors internet connectivity and auto-enables WiFi AP when offline
# Only active in ethernet mode (wifi-client uses wlan0 for internet)

# Configuration
PING_TARGET="8.8.8.8"
PING_COUNT=2
PING_TIMEOUT=3
STATE_FILE="/tmp/sai-cam-internet-state"
CONFIG_FILE="/etc/sai-cam/config.yaml"
AP_CONNECTION="sai-cam-ap"
FAIL_COUNT_FILE="/tmp/sai-cam-net-fails"
MAX_FAILS_RESTART=3   # ~9 min  → bounce eth interface
MAX_FAILS_REBOOT=6    # ~18 min → reboot

# Get network mode from config
get_network_mode() {
    if [ -f "$CONFIG_FILE" ]; then
        grep -E "^\s*mode:" "$CONFIG_FILE" | head -1 | sed "s/.*mode:[[:space:]]*['\"]*//" | sed "s/['\"].*//"
    else
        echo "ethernet"
    fi
}

# Check if WiFi AP connection exists
ap_exists() {
    nmcli con show "$AP_CONNECTION" > /dev/null 2>&1
}

# Check if WiFi AP is currently active
ap_is_active() {
    nmcli con show --active | grep -q "$AP_CONNECTION"
}

# Enable WiFi AP
enable_ap() {
    if ! ap_is_active; then
        logger -t "sai-cam-internet-watchdog" "Internet down - enabling WiFi AP"
        nmcli con up "$AP_CONNECTION" 2>/dev/null
    fi
}

# Disable WiFi AP
disable_ap() {
    if ap_is_active; then
        logger -t "sai-cam-internet-watchdog" "Internet restored - disabling WiFi AP"
        nmcli con down "$AP_CONNECTION" 2>/dev/null
    fi
}

# Check internet connectivity
internet_is_up() {
    ping -c "$PING_COUNT" -W "$PING_TIMEOUT" "$PING_TARGET" > /dev/null 2>&1
}

# Main logic
main() {
    # Only run in ethernet mode
    NETWORK_MODE=$(get_network_mode)
    if [ "$NETWORK_MODE" != "ethernet" ]; then
        exit 0
    fi

    # Also skip if wlan0 is currently carrying the default route or has an IP
    # (catches ethernet-mode nodes like saicam6 that use WiFi for internet)
    if ip route show default 2>/dev/null | grep -q "dev wlan0"; then
        exit 0
    fi
    if nmcli -t -f DEVICE,TYPE,STATE dev 2>/dev/null | grep -q "^wlan0:wifi:connected"; then
        exit 0
    fi

    # Check if AP connection exists
    if ! ap_exists; then
        exit 0
    fi

    # Get previous state
    PREV_STATE="unknown"
    if [ -f "$STATE_FILE" ]; then
        PREV_STATE=$(cat "$STATE_FILE")
    fi

    # Check current internet status
    if internet_is_up; then
        CURR_STATE="up"
        # Internet restored - disable AP if it was auto-enabled
        if [ "$PREV_STATE" = "down" ]; then
            disable_ap
        fi
    else
        CURR_STATE="down"
        # Internet down - enable AP
        if [ "$PREV_STATE" != "down" ]; then
            enable_ap
        fi
    fi

    # Save current state
    echo "$CURR_STATE" > "$STATE_FILE"

    # --- Escalating recovery ---
    if [ "$CURR_STATE" = "up" ]; then
        echo 0 > "$FAIL_COUNT_FILE"
    else
        FAILS=$(cat "$FAIL_COUNT_FILE" 2>/dev/null || echo 0)
        FAILS=$((FAILS + 1))
        echo "$FAILS" > "$FAIL_COUNT_FILE"
        logger -t "sai-cam-internet-watchdog" \
            "Consecutive failures: $FAILS / $MAX_FAILS_REBOOT"

        if [ "$FAILS" -ge "$MAX_FAILS_REBOOT" ]; then
            logger -t "sai-cam-internet-watchdog" \
                "CRITICAL: $FAILS failures — rebooting"
            echo 0 > "$FAIL_COUNT_FILE"
            sync
            /sbin/reboot -f

        elif [ "$FAILS" -ge "$MAX_FAILS_RESTART" ]; then
            ETH_IFACE=$(ip -o link show | \
                awk -F': ' '!/lo|wlan|docker|br-|veth|zt/{print $2; exit}')
            if [ -n "$ETH_IFACE" ]; then
                logger -t "sai-cam-internet-watchdog" \
                    "$FAILS failures — bouncing $ETH_IFACE"
                ip link set "$ETH_IFACE" down
                sleep 3
                ip link set "$ETH_IFACE" up
            fi
        fi
    fi
}

main "$@"
