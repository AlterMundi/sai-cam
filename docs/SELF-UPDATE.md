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

## Release Workflow

### `release.sh` reference

Current version is derived from git tags (`git describe --tags --abbrev=0`),
not from `src/version.py`. The script writes `version.py` as a derived
artifact during release — never edit it by hand.

```
./scripts/release.sh              # patch bump (default): 0.2.26 → 0.2.27
./scripts/release.sh --minor      # minor bump: 0.2.26 → 0.3.0
./scripts/release.sh --major      # major bump: 0.2.26 → 1.0.0
./scripts/release.sh --beta       # beta pre-release: 0.2.26 → 0.2.27-beta.1
./scripts/release.sh --beta       # next beta: 0.2.27-beta.1 → 0.2.27-beta.2
./scripts/release.sh --promote    # promote beta to stable: 0.2.27-beta.2 → 0.2.27
./scripts/release.sh --dry-run    # preview, no changes
./scripts/release.sh --force-branch  # skip the "must be on main" check
```

Safety checks before pushing: must be on `main`, clean working tree,
up-to-date with remote, tag must not already exist.

### Stable release

```bash
./scripts/release.sh
# CI creates a GitHub Release (not pre-release)
# All nodes pick it up on their next 6h check
```

### Beta iteration procedure

Beta nodes (`channel: beta` in config.yaml) see pre-releases that stable
nodes ignore. This is the development iteration loop:

```bash
# 1. Make your changes on main
git add -A && git commit -m "fix: whatever"

# 2. Release as pre-release (bumps version, tags, pushes, CI creates release)
./scripts/release.sh --beta

# 3. Trigger update on your beta node (or wait for the 6h timer)
ssh saicam3.local "sudo /opt/sai-cam/system/self-update.sh --force"

# 4. Test on the node, check portal auto-refreshes to new version

# 5. Found a bug? Fix it, repeat from step 1 — each iteration bumps the version
./scripts/release.sh --beta       # new version, new tag, new pre-release

# 6. Happy with the result? Promote to stable for the whole fleet
./scripts/release.sh --promote    # strips pre-release suffix, full release
```

### Setting up a beta node

```bash
ssh saicam3.local "sudo nano /etc/sai-cam/config.yaml"
# Add or edit:
#   updates:
#     enabled: true
#     channel: beta
#     apply_immediately: true
```

### Manual check from the portal

The Updates card has a ↻ button that queries GitHub Releases from the
browser (via `POST /api/update/check`). This is read-only — it reports
whether an update is available but does not apply it.

### Tips

- **Every iteration gets its own version number.** Don't reuse tags.
  Tags are immutable release identifiers — re-tagging the same version
  creates confusion in the fleet and breaks caching. Version numbers are
  free; use them liberally.
- **Pre-releases are invisible to stable nodes.** You can release v0.2.23,
  v0.2.24, v0.2.25 as pre-releases and stable nodes won't see any of them.
  Only the final promoted release reaches the fleet.
- **The portal auto-reloads on version change.** The SSE health event
  includes `portal_version`; when the browser detects a mismatch it does
  `location.reload()`. No manual refresh needed after updates.
- **`--dry-run` is your friend.** Always preview before releasing to
  verify the version bump is what you expect.

## Rollback Behavior

- Health check runs for up to 120 seconds after applying an update
- Checks: both services active, portal API responds, version matches target
- On failure: checks out the previous tag and re-runs `install.sh --preserve-config`
- After 3 consecutive failures, updates are paused until manually cleared
- Safety nets: `service_watchdog.sh` (cron, every 10min) and daily 4 AM reboot

## Fleet Command API

Remote node control from developer machine. Each node's status portal
exposes `/api/fleet/*` endpoints; the `fleet.py` CLI drives them in parallel.

### Setup

1. Generate a token: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Add to node config (`/etc/sai-cam/config.yaml`):
   ```yaml
   fleet:
     token: '<generated-token>'
     allowed_config_keys:
       - updates.channel
       - updates.enabled
       - logging.level
   ```
3. Restart portal: `sudo systemctl restart sai-cam-portal`
4. Add the node to `fleet/nodes.yaml` (copy from `fleet/nodes.yaml.example`)

### Fleet CLI usage

```bash
./scripts/fleet.py --list                        # Show registry
./scripts/fleet.py --ping                        # Ping all nodes
./scripts/fleet.py --update saicam3              # Trigger update on one node
./scripts/fleet.py --update ALL                  # Trigger update on all nodes
./scripts/fleet.py --restart saicam1 saicam2     # Restart services
./scripts/fleet.py --reboot saicam3              # Reboot a node (1 min delay)
./scripts/fleet.py --set updates.channel=beta saicam3
./scripts/fleet.py --set logging.level=DEBUG ALL
./scripts/fleet.py --canary                      # Canary rollout workflow
```

### Fleet API endpoints

All under `/api/fleet/` on each node's portal (port 8090).
Require `Authorization: Bearer <token>` except ping.

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/fleet/ping` | Version, uptime, node_id (no auth) |
| POST | `/api/fleet/update/apply` | Trigger `sai-cam-update.service` |
| POST | `/api/fleet/service/restart` | Restart sai-cam + portal |
| POST | `/api/fleet/reboot` | Schedule reboot (+1 min) |
| POST | `/api/fleet/config` | Set whitelisted config key |

### Canary rollout

```bash
./scripts/fleet.py --canary
```

1. Pings canary node for baseline version
2. Triggers update on canary
3. Polls until version changes (up to 3 min)
4. Health-checks canary via `/api/status`
5. Prompts: "Roll to fleet? [y/N]"
6. If yes, updates all stable nodes in parallel
7. Prints rollout report table

### Security

- Bearer tokens per node (stored in `fleet/nodes.yaml`, gitignored)
- Config changes restricted to `fleet.allowed_config_keys` whitelist
- Sudoers scoped to exact commands (`systemctl restart`, `shutdown -r +1`)
- Nodes on local mesh network, not internet-exposed

## Fleet Monitoring

Prometheus metrics (shipped via vmagent):
- `saicam_update_available` (0/1)
- `saicam_update_last_check_timestamp` (unix timestamp)
- `saicam_update_consecutive_failures` (count)

Query all nodes via fleet CLI:
```bash
./scripts/fleet.py --ping
```

## Files

| File | Purpose |
|------|---------|
| `scripts/self-update.sh` | Core update orchestrator |
| `scripts/release.sh` | Version bump, tag, push (reads version from git tags) |
| `scripts/fleet.py` | Fleet CLI — remote node control |
| `src/update_manager.py` | Python state management module |
| `src/status_portal.py` | Portal API (includes `/api/fleet/*` endpoints) |
| `fleet/nodes.yaml.example` | Fleet registry template |
| `fleet/nodes.yaml` | Real fleet registry with tokens (gitignored) |
| `config/sai-cam-sudoers` | Sudoers rules for fleet operations |
| `systemd/sai-cam-update.service.template` | Oneshot service for update runs |
| `systemd/sai-cam-update.timer.template` | Timer: 6h interval, 30min jitter |
| `/var/lib/sai-cam/update-state.json` | Runtime state (on deployed nodes) |
| `/opt/sai-cam/repo/` | Git clone used for tag checkouts |
