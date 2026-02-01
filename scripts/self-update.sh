#!/bin/bash
# SAI-Cam Self-Update Script
# Pull-based update system that checks GitHub Releases and applies updates
# via install.sh --preserve-config with automatic rollback on failure.
#
# Called by systemd timer (sai-cam-update.timer) every 6h with 30min jitter.
# Maintains a git clone at /opt/sai-cam/repo/ and checks out release tags.
#
# Usage:
#   sudo /opt/sai-cam/system/self-update.sh          # Normal operation
#   sudo /opt/sai-cam/system/self-update.sh --force   # Ignore consecutive failure guard
#   sudo /opt/sai-cam/system/self-update.sh --check   # Check only, don't apply

set -euo pipefail

# --- Configuration ---
INSTALL_DIR="/opt/sai-cam"
CONFIG_FILE="/etc/sai-cam/config.yaml"
STATE_FILE="/var/lib/sai-cam/update-state.json"
LOCK_FILE="/var/lock/sai-cam-update.lock"
REPO_DIR="$INSTALL_DIR/repo"
REPO_URL="https://github.com/AlterMundi/sai-cam.git"
LOG_TAG="sai-cam-update"
HEALTH_TIMEOUT=120
HEALTH_INTERVAL=10
MAX_CONSECUTIVE_FAILURES=3
GITHUB_API="https://api.github.com/repos/AlterMundi/sai-cam/releases"
CURL_TIMEOUT=15
VENV_PYTHON="$INSTALL_DIR/venv/bin/python3"

# --- Parse arguments ---
FORCE=false
CHECK_ONLY=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --force)  FORCE=true; shift ;;
        --check)  CHECK_ONLY=true; shift ;;
        *)        shift ;;
    esac
done

# --- Logging ---
log() { logger -t "$LOG_TAG" -p "user.info" "$*"; echo "[$(date -Iseconds)] $*"; }
log_err() { logger -t "$LOG_TAG" -p "user.err" "$*"; echo "[$(date -Iseconds)] ERROR: $*" >&2; }

# --- State helpers (call update_manager.py via deployed venv) ---
read_state_field() {
    local field="$1"
    if [ -f "$STATE_FILE" ]; then
        "$VENV_PYTHON" -c "
import json, sys
try:
    with open('$STATE_FILE') as f: d = json.load(f)
    print(d.get('$field', ''))
except Exception: pass
" 2>/dev/null || echo ""
    fi
}

write_state() {
    # Usage: write_state key1=val1 key2=val2 ...
    local py_args=""
    for arg in "$@"; do
        local key="${arg%%=*}"
        local val="${arg#*=}"
        # Numbers: consecutive_failures
        if [[ "$key" == "consecutive_failures" ]]; then
            py_args+="    d['$key'] = $val"$'\n'
        else
            py_args+="    d['$key'] = '$val'"$'\n'
        fi
    done

    "$VENV_PYTHON" -c "
import json, os
from pathlib import Path
path = '$STATE_FILE'
Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
try:
    with open(path) as f: d = json.load(f)
except (FileNotFoundError, json.JSONDecodeError): d = {}
$py_args
tmp = path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(d, f, indent=2)
    f.flush()
    os.fsync(f.fileno())
os.rename(tmp, path)
" 2>/dev/null
}

get_current_version() {
    # Read VERSION from deployed camera_service.py
    local version_file="$INSTALL_DIR/bin/camera_service.py"
    if [ -f "$version_file" ]; then
        grep -oP 'VERSION\s*=\s*"?\K[0-9]+\.[0-9]+\.[0-9]+[^"]*' "$version_file" 2>/dev/null || echo "0.0.0"
    else
        echo "0.0.0"
    fi
}

read_config_value() {
    local key="$1"
    local default="${2:-}"
    if [ -f "$CONFIG_FILE" ]; then
        "$VENV_PYTHON" -c "
import yaml, sys
try:
    with open('$CONFIG_FILE') as f: c = yaml.safe_load(f)
    keys = '$key'.split('.')
    v = c
    for k in keys:
        v = v[k]
    print(v)
except Exception:
    print('$default')
" 2>/dev/null || echo "$default"
    else
        echo "$default"
    fi
}

# --- Acquire exclusive lock ---
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log "Another update process is running, exiting."
    exit 0
fi

# --- Check if updates are enabled ---
UPDATES_ENABLED=$(read_config_value "updates.enabled" "true")
if [ "$UPDATES_ENABLED" != "true" ]; then
    log "Updates disabled in config, exiting."
    exit 0
fi

CHANNEL=$(read_config_value "updates.channel" "stable")
APPLY_IMMEDIATELY=$(read_config_value "updates.apply_immediately" "true")

# --- Consecutive failure guard ---
CONSECUTIVE_FAILURES=$(read_state_field "consecutive_failures")
CONSECUTIVE_FAILURES=${CONSECUTIVE_FAILURES:-0}
if [ "$CONSECUTIVE_FAILURES" -ge "$MAX_CONSECUTIVE_FAILURES" ] && [ "$FORCE" != "true" ]; then
    log_err "Skipping update: $CONSECUTIVE_FAILURES consecutive failures (max $MAX_CONSECUTIVE_FAILURES). Use --force or clear state manually."
    exit 1
fi

# --- Get current version ---
CURRENT_VERSION=$(get_current_version)
log "Current version: $CURRENT_VERSION, channel: $CHANNEL"

# --- Query GitHub Releases API ---
log "Checking GitHub for new releases..."
RELEASES_JSON=$(curl -sf --max-time "$CURL_TIMEOUT" \
    -H "Accept: application/vnd.github.v3+json" \
    "$GITHUB_API" 2>/dev/null) || {
    log_err "Failed to query GitHub Releases API"
    write_state "last_check=$(date -Iseconds)" "status=check_failed"
    exit 1
}

# --- Find latest release for channel ---
TARGET_TAG=$("$VENV_PYTHON" -c "
import json, sys
releases = json.loads('''$RELEASES_JSON''')
channel = '$CHANNEL'
for r in releases:
    if r.get('draft', False):
        continue
    tag = r.get('tag_name', '')
    if not tag:
        continue
    if channel == 'stable' and r.get('prerelease', False):
        continue
    # Strip leading 'v' for version comparison
    print(tag)
    break
" 2>/dev/null) || {
    log_err "Failed to parse releases JSON"
    write_state "last_check=$(date -Iseconds)" "status=check_failed"
    exit 1
}

if [ -z "$TARGET_TAG" ]; then
    log "No suitable release found for channel=$CHANNEL"
    write_state "last_check=$(date -Iseconds)" "status=up_to_date" \
        "current_version=$CURRENT_VERSION" "channel=$CHANNEL"
    exit 0
fi

# Strip 'v' prefix for version comparison
TARGET_VERSION="${TARGET_TAG#v}"

# --- Compare versions ---
IS_NEWER=$("$VENV_PYTHON" -c "
try:
    from packaging.version import Version
    print('yes' if Version('$TARGET_VERSION') > Version('$CURRENT_VERSION') else 'no')
except ImportError:
    cv = tuple(int(x) for x in '$CURRENT_VERSION'.split('-')[0].split('.'))
    tv = tuple(int(x) for x in '$TARGET_VERSION'.split('-')[0].split('.'))
    print('yes' if tv > cv else 'no')
" 2>/dev/null)

if [ "$IS_NEWER" != "yes" ]; then
    log "Already up-to-date ($CURRENT_VERSION >= $TARGET_VERSION)"
    write_state "last_check=$(date -Iseconds)" "status=up_to_date" \
        "current_version=$CURRENT_VERSION" "latest_available=$TARGET_VERSION" \
        "channel=$CHANNEL"
    exit 0
fi

log "Update available: $CURRENT_VERSION -> $TARGET_VERSION ($TARGET_TAG)"
write_state "last_check=$(date -Iseconds)" "latest_available=$TARGET_VERSION" \
    "current_version=$CURRENT_VERSION" "channel=$CHANNEL"

# --- Check-only mode ---
if [ "$CHECK_ONLY" = "true" ]; then
    log "Check-only mode, not applying update."
    exit 0
fi

# --- Ensure repo clone exists ---
if [ ! -d "$REPO_DIR/.git" ]; then
    log "Cloning repository to $REPO_DIR..."
    git clone --depth 50 "$REPO_URL" "$REPO_DIR" 2>&1 | while read -r line; do
        log "git: $line"
    done
fi

# --- Fetch and checkout target tag ---
log "Fetching tag $TARGET_TAG..."
cd "$REPO_DIR"
git fetch --depth 50 origin "refs/tags/$TARGET_TAG:refs/tags/$TARGET_TAG" 2>&1 || {
    log_err "Failed to fetch tag $TARGET_TAG"
    write_state "status=fetch_failed"
    exit 1
}
git checkout "$TARGET_TAG" 2>&1 || {
    log_err "Failed to checkout tag $TARGET_TAG"
    write_state "status=checkout_failed"
    exit 1
}
log "Checked out $TARGET_TAG"

# --- Pre-update validation ---
log "Running pre-update validation..."
PREFLIGHT_PASS=true

# Check critical files exist in new code
CRITICAL_FILES=(
    "$REPO_DIR/src/camera_service.py"
    "$REPO_DIR/src/status_portal.py"
    "$REPO_DIR/scripts/install.sh"
    "$REPO_DIR/systemd/sai-cam.service.template"
    "$REPO_DIR/systemd/sai-cam-portal.service.template"
)
for f in "${CRITICAL_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        log_err "Pre-update check FAILED: missing $f"
        PREFLIGHT_PASS=false
    fi
done

# Verify VERSION in new code matches tag
NEW_VERSION=$(grep -oP 'VERSION\s*=\s*"?\K[0-9]+\.[0-9]+\.[0-9]+[^"]*' \
    "$REPO_DIR/src/camera_service.py" 2>/dev/null || echo "")
if [ "$NEW_VERSION" != "$TARGET_VERSION" ]; then
    log_err "Pre-update check FAILED: VERSION in code ($NEW_VERSION) != tag ($TARGET_VERSION)"
    PREFLIGHT_PASS=false
fi

# Quick import validation with existing venv
"$VENV_PYTHON" -c "import yaml, flask, psutil" 2>/dev/null || {
    log_err "Pre-update check FAILED: core Python imports broken"
    PREFLIGHT_PASS=false
}

# Check system resources
MEM_FREE_MB=$("$VENV_PYTHON" -c "import psutil; print(int(psutil.virtual_memory().available / 1024 / 1024))" 2>/dev/null || echo "0")
DISK_FREE_MB=$(df -BM --output=avail "$INSTALL_DIR" 2>/dev/null | tail -1 | tr -d 'M ' || echo "0")
if [ "$MEM_FREE_MB" -lt 200 ]; then
    log_err "Pre-update check FAILED: only ${MEM_FREE_MB}MB memory free (need 200MB)"
    PREFLIGHT_PASS=false
fi
if [ "$DISK_FREE_MB" -lt 500 ]; then
    log_err "Pre-update check FAILED: only ${DISK_FREE_MB}MB disk free (need 500MB)"
    PREFLIGHT_PASS=false
fi

if [ "$PREFLIGHT_PASS" != "true" ]; then
    log_err "Pre-update validation failed, aborting update."
    FAILURES=$((CONSECUTIVE_FAILURES + 1))
    write_state "status=preflight_failed" "consecutive_failures=$FAILURES"
    exit 1
fi
log "Pre-update validation passed."

# --- Save rollback state ---
write_state "status=updating" "previous_version=$CURRENT_VERSION" \
    "current_version=$CURRENT_VERSION" "latest_available=$TARGET_VERSION"

# --- Apply update via install.sh ---
log "Applying update via install.sh --preserve-config..."
cd "$REPO_DIR"
if bash scripts/install.sh --preserve-config 2>&1 | while read -r line; do
    log "install: $line"
done; then
    log "install.sh completed successfully"
else
    log_err "install.sh exited with error"
fi

# --- Post-update health check ---
log "Running post-update health check (timeout: ${HEALTH_TIMEOUT}s)..."
HEALTH_PASS=false
ELAPSED=0
while [ "$ELAPSED" -lt "$HEALTH_TIMEOUT" ]; do
    sleep "$HEALTH_INTERVAL"
    ELAPSED=$((ELAPSED + HEALTH_INTERVAL))

    # Check both services are active
    if ! systemctl is-active --quiet sai-cam; then
        log "Health check ($ELAPSED/${HEALTH_TIMEOUT}s): sai-cam not active"
        continue
    fi
    if ! systemctl is-active --quiet sai-cam-portal; then
        log "Health check ($ELAPSED/${HEALTH_TIMEOUT}s): sai-cam-portal not active"
        continue
    fi

    # Check portal API responds
    PORTAL_RESPONSE=$(curl -sf --max-time 5 http://127.0.0.1:8090/api/status 2>/dev/null) || {
        log "Health check ($ELAPSED/${HEALTH_TIMEOUT}s): portal API not responding"
        continue
    }

    # Check reported version matches target
    REPORTED_VERSION=$("$VENV_PYTHON" -c "
import json, sys
d = json.loads('''$PORTAL_RESPONSE''')
print(d.get('node', {}).get('version', ''))
" 2>/dev/null || echo "")

    if [ "$REPORTED_VERSION" = "$TARGET_VERSION" ]; then
        HEALTH_PASS=true
        break
    else
        log "Health check ($ELAPSED/${HEALTH_TIMEOUT}s): version mismatch (got '$REPORTED_VERSION', want '$TARGET_VERSION')"
    fi
done

# --- Handle result ---
if [ "$HEALTH_PASS" = "true" ]; then
    log "Update to $TARGET_VERSION successful!"
    write_state "status=updated" "current_version=$TARGET_VERSION" \
        "latest_available=$TARGET_VERSION" "previous_version=$CURRENT_VERSION" \
        "last_update=$(date -Iseconds)" "consecutive_failures=0"
    exit 0
fi

# --- Rollback ---
log_err "Health check failed after ${HEALTH_TIMEOUT}s, initiating rollback to v${CURRENT_VERSION}..."
write_state "status=rolling_back"

ROLLBACK_TAG="v${CURRENT_VERSION}"
cd "$REPO_DIR"
git fetch --depth 50 origin "refs/tags/$ROLLBACK_TAG:refs/tags/$ROLLBACK_TAG" 2>&1 || true
if git checkout "$ROLLBACK_TAG" 2>&1; then
    log "Checked out $ROLLBACK_TAG for rollback"
    bash scripts/install.sh --preserve-config 2>&1 | while read -r line; do
        log "rollback-install: $line"
    done

    # Wait briefly for services to stabilize
    sleep 15

    if systemctl is-active --quiet sai-cam; then
        FAILURES=$((CONSECUTIVE_FAILURES + 1))
        log "Rollback completed. sai-cam is active. Consecutive failures: $FAILURES"
        write_state "status=rollback_completed" "current_version=$CURRENT_VERSION" \
            "consecutive_failures=$FAILURES" "last_update=$(date -Iseconds)"
    else
        FAILURES=$((CONSECUTIVE_FAILURES + 1))
        log_err "Rollback FAILED: sai-cam not active after rollback"
        write_state "status=rollback_failed" "current_version=$CURRENT_VERSION" \
            "consecutive_failures=$FAILURES"
    fi
else
    FAILURES=$((CONSECUTIVE_FAILURES + 1))
    log_err "Failed to checkout rollback tag $ROLLBACK_TAG"
    write_state "status=rollback_failed" "consecutive_failures=$FAILURES"
fi

exit 1
