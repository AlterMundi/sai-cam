# SAI-Cam Self-Update System

Pull-based self-update system for SAI-Cam edge nodes. Checks GitHub Releases on a timer, applies updates via `install.sh --preserve-config`, and rolls back automatically on failure.

## How It Works

1. A systemd timer (`sai-cam-update.timer`) fires every 6 hours with 30-minute random jitter
2. `self-update.sh` queries the GitHub Releases API for new versions
3. If a newer release exists (filtered by channel), it checks out the tag in `/opt/sai-cam/repo/`
4. Pre-update validation: checks critical files, version match, Python imports, system resources
5. Applies update: `install.sh --preserve-config` (preserves `/etc/sai-cam/config.yaml`)
6. Post-update health check: verifies services are running and API reports correct version
7. On failure: rolls back to previous version and increments failure counter

## Configuration

In `/etc/sai-cam/config.yaml`:

```yaml
updates:
  enabled: true          # Enable/disable automatic updates
  channel: 'stable'      # 'stable' = releases only, 'beta' = includes pre-releases
  apply_immediately: true # true = restart services now
```

## Manual Operations

### Trigger an update check now

```bash
sudo systemctl start sai-cam-update.service
journalctl -u sai-cam-update -f
```

### Check timer status

```bash
systemctl list-timers sai-cam-update.timer
```

### View update state

```bash
cat /var/lib/sai-cam/update-state.json
# Or via API:
curl -s http://localhost:8090/api/update/status | python3 -m json.tool
```

### Clear consecutive failure guard

After 3 consecutive failures, updates are paused. To reset:

```bash
sudo python3 -c "
import json
p = '/var/lib/sai-cam/update-state.json'
with open(p) as f: d = json.load(f)
d['consecutive_failures'] = 0
d['status'] = 'up_to_date'
with open(p, 'w') as f: json.dump(d, f, indent=2)
print('Cleared.')
"
```

Or force an update despite the guard:

```bash
sudo /opt/sai-cam/system/self-update.sh --force
```

### Check only (don't apply)

```bash
sudo /opt/sai-cam/system/self-update.sh --check
```

### Disable updates entirely

Set `updates.enabled: false` in `/etc/sai-cam/config.yaml`, or:

```bash
sudo systemctl stop sai-cam-update.timer
sudo systemctl disable sai-cam-update.timer
```

## State File

Location: `/var/lib/sai-cam/update-state.json`

| Field | Description |
|-------|-------------|
| `status` | `up_to_date`, `updating`, `updated`, `rollback_completed`, `rollback_failed` |
| `current_version` | Currently deployed version |
| `latest_available` | Latest version seen on GitHub |
| `previous_version` | Version before last update attempt |
| `last_check` | ISO timestamp of last API check |
| `last_update` | ISO timestamp of last successful update |
| `consecutive_failures` | Count of sequential failed updates (resets on success) |
| `channel` | `stable` or `beta` |

## Rollback Behavior

- Health check runs for up to 120 seconds after applying an update
- Checks: both services active, portal API responds, version matches target
- On failure: checks out the previous tag and re-runs `install.sh --preserve-config`
- After 3 consecutive failures, updates are paused until manually cleared
- Safety nets: `service_watchdog.sh` (cron, every 10min) and daily 4 AM reboot

## Fleet Monitoring

Prometheus metrics (shipped via vmagent):
- `saicam_update_available` (0/1)
- `saicam_update_last_check_timestamp` (unix timestamp)
- `saicam_update_consecutive_failures` (count)

Query all nodes:
```bash
for node in saicam3.local saicam5.local; do
    echo -n "$node: "
    curl -sf "http://$node/api/update/status" | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(f'v{d[\"current_version\"]} ({d[\"status\"]})')" \
        2>/dev/null || echo "UNREACHABLE"
done
```

## Files

| File | Purpose |
|------|---------|
| `scripts/self-update.sh` | Core update orchestrator |
| `src/update_manager.py` | Python state management module |
| `systemd/sai-cam-update.service.template` | Oneshot service for update runs |
| `systemd/sai-cam-update.timer.template` | Timer: 6h interval, 30min jitter |
| `/var/lib/sai-cam/update-state.json` | Runtime state (on deployed nodes) |
| `/opt/sai-cam/repo/` | Git clone used for tag checkouts |
