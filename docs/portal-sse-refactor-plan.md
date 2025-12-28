# Portal SSE Refactor Plan

## Overview

Refactor the status portal dashboard from polling-based updates to Server-Sent Events (SSE) for real-time, efficient monitoring.

## Current State (Problems)

```
┌──────────────────────────────────────────────────────────┐
│  Every 5 seconds:                                        │
│  1. fetchStatus() → GET /api/status (all data)          │
│  2. container.innerHTML = '' (destroy everything)        │
│  3. Rebuild all blocks from scratch                      │
│  4. fetchLogs() → GET /api/logs                          │
│  5. Update log viewer                                    │
└──────────────────────────────────────────────────────────┘
```

**Issues:**
- Visual flashing on every refresh
- State loss (scroll position, animations)
- Bandwidth waste (~50KB every 5s even if nothing changed)
- Up to 5s latency for changes
- Button states reset on refresh

## Target State

```
┌──────────────────────────────────────────────────────────┐
│  On page load:                                           │
│  1. GET /api/status → Full initial state                │
│  2. Render dashboard once                                │
│  3. Open EventSource('/api/events')                      │
│                                                          │
│  On SSE event:                                           │
│  - Update only affected DOM elements                     │
│  - Append logs (not replace)                             │
│  - Smooth transitions                                    │
└──────────────────────────────────────────────────────────┘
```

---

## Implementation Steps

### Phase 1: Backend - Unified Event Stream

**File:** `src/status_portal.py`

#### 1.1 Add Event Stream Endpoint

```python
@app.route('/api/events')
def api_events():
    """Unified SSE endpoint for all dashboard updates"""
    def generate():
        last_health_hash = None
        log_path = Path('/var/log/sai-cam/camera_service.log')
        last_log_size = log_path.stat().st_size if log_path.exists() else 0
        last_system_update = 0

        # Send initial state
        health = query_health_socket()
        if health:
            yield f"event: health\ndata: {json.dumps(health)}\n\n"

        while True:
            try:
                now = time.time()

                # Health updates (every 5s or on change)
                if now - last_system_update >= 5:
                    health = query_health_socket()
                    if health:
                        health_hash = hash(json.dumps(health, sort_keys=True))
                        if health_hash != last_health_hash:
                            yield f"event: health\ndata: {json.dumps(health)}\n\n"
                            last_health_hash = health_hash
                    last_system_update = now

                # Log updates (real-time)
                if log_path.exists():
                    current_size = log_path.stat().st_size
                    if current_size > last_log_size:
                        with open(log_path, 'r') as f:
                            f.seek(last_log_size)
                            for line in f:
                                line = line.strip()
                                if line:
                                    yield f"event: log\ndata: {json.dumps({'line': line})}\n\n"
                        last_log_size = current_size
                    elif current_size < last_log_size:
                        # Log rotated
                        last_log_size = 0

                time.sleep(1)

            except GeneratorExit:
                break
            except Exception as e:
                logger.error(f"SSE error: {e}")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(5)

    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
    return response
```

#### 1.2 Add System Status Endpoint (for initial load)

Keep existing `/api/status` for initial full state load.

---

### Phase 2: Frontend - Event-Driven Updates

**File:** `src/portal/dashboard.js`

#### 2.1 Refactor Initialization

```javascript
// Global state
let eventSource = null;
let dashboardState = null;

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Load initial state
    dashboardState = await fetchStatus();
    if (!dashboardState) {
        showError('Failed to load status');
        return;
    }

    // 2. Render dashboard once
    renderInitialDashboard(dashboardState);

    // 3. Connect to event stream
    connectEventStream();

    // 4. Load initial logs
    const logs = await fetchLogs();
    renderLogs(logs);

    // 5. Fetch log level
    fetchLogLevel();
});
```

#### 2.2 Event Stream Handler

```javascript
function connectEventStream() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource('/api/events');

    eventSource.addEventListener('health', (e) => {
        const health = JSON.parse(e.data);
        updateHealthData(health);
    });

    eventSource.addEventListener('log', (e) => {
        const {line} = JSON.parse(e.data);
        appendLogLine(line);
    });

    eventSource.addEventListener('error', (e) => {
        console.error('SSE error, reconnecting in 5s...');
        setTimeout(connectEventStream, 5000);
    });

    eventSource.onerror = () => {
        // Connection lost, will auto-reconnect
        updateConnectionStatus(false);
    };

    eventSource.onopen = () => {
        updateConnectionStatus(true);
    };
}
```

#### 2.3 Selective Update Functions

```javascript
function updateHealthData(health) {
    // Update timestamp
    document.getElementById('update-time').textContent =
        new Date().toLocaleTimeString();

    // Update system gauges (if data changed)
    if (health.system) {
        updateGauge('cpu', health.system.cpu_percent);
        updateGauge('memory', health.system.memory_percent);
        updateGauge('disk', health.system.disk_percent);
    }

    // Update camera cards
    if (health.cameras) {
        Object.entries(health.cameras).forEach(([id, cam]) => {
            updateCameraCard(id, cam);
        });
    }

    // Update thread status
    if (health.threads) {
        updateThreadStatus(health.threads);
    }
}

function updateGauge(type, value) {
    const gauge = document.querySelector(`[data-gauge="${type}"]`);
    if (!gauge) return;

    const circle = gauge.querySelector('.circle');
    const text = gauge.querySelector('.percentage');

    if (circle) {
        circle.setAttribute('stroke-dasharray', `${value}, 100`);
    }
    if (text) {
        text.textContent = `${value}%`;
    }
}

function updateCameraCard(id, status) {
    const card = document.querySelector(`[data-camera="${id}"]`);
    if (!card) return;

    const badge = card.querySelector('.badge');
    const isOnline = status.state === 'healthy' && status.thread_alive;

    card.className = `camera-card ${isOnline ? 'online' : 'offline'}`;
    if (badge) {
        badge.className = `badge ${isOnline ? 'online' : 'offline'}`;
        badge.textContent = isOnline ? '●' : '○';
    }

    // Update last capture time
    const lastCapture = card.querySelector('.camera-last-capture');
    if (lastCapture && status.last_success_age !== undefined) {
        lastCapture.textContent = formatAge(status.last_success_age);
    }
}

function appendLogLine(line) {
    const viewer = document.getElementById('log-viewer');
    if (!viewer) return;

    // Remove "Loading..." if present
    const loading = viewer.querySelector('.log-loading');
    if (loading) loading.remove();

    // Create log line element
    const div = document.createElement('div');
    div.className = 'log-line';
    if (line.includes('ERROR')) div.className += ' log-error';
    else if (line.includes('WARNING')) div.className += ' log-warning';
    else if (line.includes('DEBUG')) div.className += ' log-debug';
    div.textContent = line;

    // Append and scroll
    viewer.appendChild(div);

    // Keep max 200 lines
    while (viewer.children.length > 200) {
        viewer.removeChild(viewer.firstChild);
    }

    // Auto-scroll if near bottom
    const isNearBottom = viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 100;
    if (isNearBottom) {
        viewer.scrollTop = viewer.scrollHeight;
    }
}
```

#### 2.4 Add Data Attributes to HTML

Update block renders to include data attributes for selective updates:

```javascript
// In cameras block render:
<div class="camera-card ${cam.online ? 'online' : 'offline'}" data-camera="${cam.id}">

// In system block render:
<div class="gauge" data-gauge="cpu">
<div class="gauge" data-gauge="memory">
<div class="gauge" data-gauge="disk">
```

---

### Phase 3: Connection Status Indicator

#### 3.1 Add UI Element

```html
<!-- In header -->
<div id="connection-status" class="connection-status">
    <span class="status-dot"></span>
    <span class="status-text">Connected</span>
</div>
```

#### 3.2 Add Styles

```css
.connection-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.8em;
}

.connection-status .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--success-color);
}

.connection-status.disconnected .status-dot {
    background: var(--error-color);
    animation: pulse 1s infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
```

---

### Phase 4: Cleanup & Testing

#### 4.1 Remove Polling Code

```javascript
// DELETE these:
setInterval(renderDashboard, REFRESH_INTERVAL);
setInterval(fetchLogLevel, 30000);

// Keep only:
// - Initial load
// - SSE connection
// - Manual refresh button (optional)
```

#### 4.2 Add Manual Refresh Button

```javascript
// Optional: Allow manual refresh
async function manualRefresh() {
    dashboardState = await fetchStatus();
    renderInitialDashboard(dashboardState);
    showNotification('Dashboard refreshed', 'info');
}
```

---

## File Changes Summary

| File | Changes |
|------|---------|
| `src/status_portal.py` | Add `/api/events` SSE endpoint |
| `src/portal/dashboard.js` | Refactor to event-driven, add selective updates |
| `src/portal/styles.css` | Add connection status styles |
| `src/portal/index.html` | Add connection status element |

---

## Testing Checklist

- [ ] Initial page load shows all data correctly
- [ ] SSE connection established (check Network tab)
- [ ] Camera status updates in real-time when camera fails/recovers
- [ ] Log lines append smoothly without flashing
- [ ] Log viewer auto-scrolls when near bottom
- [ ] Log viewer preserves scroll position when scrolled up
- [ ] Connection lost shows indicator, auto-reconnects
- [ ] No memory leaks (check heap over time)
- [ ] Works after page sits idle for 10+ minutes
- [ ] Log level toggle still works
- [ ] WiFi AP toggle still works

---

## Rollback Plan

If issues arise:
1. Revert to polling by uncommenting `setInterval(renderDashboard, 5000)`
2. SSE endpoint can remain (unused) without harm
3. All changes are additive, no data model changes

---

## Future Enhancements

1. **Heartbeat**: Server sends `event: ping` every 30s to detect stale connections
2. **Reconnection backoff**: Exponential backoff on connection failures
3. **Event buffering**: Queue events if connection temporarily lost
4. **Selective subscriptions**: Client specifies which events to receive
