/**
 * SAI-Cam Modular Dashboard
 * Progressive enhancement with feature detection
 * Tiered SSE: 1s health, 20s status, 500s slow
 */

let statusData = null;
let serviceStatus = { active: false, status: 'unknown' };

// Block Registry - Add new blocks here for auto-inclusion
const BLOCKS = {
  'system-resources': {
    title: 'System Resources',
    icon: '🖥️',
    order: 1,
    detector: (status) => true,  // Always present
    render: function(data) {
      const sys = data.system;
      const tempGauge = sys.temperature ? `
        <div class="gauge gauge-temp">
          <div class="gauge-value ${sys.temperature > 70 ? 'critical' : sys.temperature > 60 ? 'warning' : ''}">${sys.temperature}°C</div>
          <div class="gauge-info">
            <div class="gauge-label">Temperature</div>
          </div>
        </div>
      ` : '';

      return `
        <div class="block">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="gauges">
            <div class="gauge" data-gauge="cpu">
              <div class="gauge-circle">
                <svg viewBox="0 0 36 36" class="circular-chart">
                  <path class="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <path class="circle ${sys.cpu_percent > 80 ? 'critical' : sys.cpu_percent > 60 ? 'warning' : ''}"
                        stroke-dasharray="${sys.cpu_percent}, 100"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <text x="18" y="20.35" class="percentage">${sys.cpu_percent}%</text>
                </svg>
              </div>
              <div class="gauge-info">
                <div class="gauge-label">CPU</div>
              </div>
            </div>
            <div class="gauge" data-gauge="memory">
              <div class="gauge-circle">
                <svg viewBox="0 0 36 36" class="circular-chart">
                  <path class="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <path class="circle ${sys.memory_percent > 80 ? 'critical' : sys.memory_percent > 60 ? 'warning' : ''}"
                        stroke-dasharray="${sys.memory_percent}, 100"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <text x="18" y="20.35" class="percentage">${sys.memory_percent}%</text>
                </svg>
              </div>
              <div class="gauge-info">
                <div class="gauge-label">Memory</div>
                <div class="gauge-detail" data-memory-detail>${sys.memory_used_mb}MB / ${sys.memory_total_mb}MB</div>
              </div>
            </div>
            <div class="gauge" data-gauge="disk">
              <div class="gauge-circle">
                <svg viewBox="0 0 36 36" class="circular-chart">
                  <path class="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <path class="circle ${sys.disk_percent > 80 ? 'critical' : sys.disk_percent > 60 ? 'warning' : ''}"
                        stroke-dasharray="${sys.disk_percent}, 100"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <text x="18" y="20.35" class="percentage">${sys.disk_percent}%</text>
                </svg>
              </div>
              <div class="gauge-info">
                <div class="gauge-label">Disk</div>
                <div class="gauge-detail" data-disk-detail>${sys.disk_used_gb}GB / ${sys.disk_total_gb}GB</div>
              </div>
            </div>
            ${tempGauge}
          </div>
          <div class="uptime">Uptime: ${formatUptime(sys.system_uptime)}</div>
          <div class="uptime service-uptime">Service: ${formatUptime(sys.service_uptime)}</div>
        </div>
      `;
    }
  },

  'wifi-ap': {
    title: 'WiFi Access Point',
    icon: '📡',
    order: 2,
    detector: (status) => status.features.wifi_ap && status.data.wifi_ap !== null,
    render: function(data) {
      const wifi = data.wifi_ap;
      return `
        <div class="block">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="metrics">
            <div class="metric-item">
              <div class="metric-label">SSID</div>
              <div class="metric-value">${wifi.ssid}</div>
            </div>
            <div class="metric-item">
              <div class="metric-label">Connected Clients</div>
              <div class="metric-value">${wifi.connected_clients}</div>
            </div>
            <div class="metric-item">
              <div class="metric-label">Channel</div>
              <div class="metric-value">${wifi.channel}</div>
            </div>
            <div class="metric-item">
              <div class="metric-label">Interface</div>
              <div class="metric-value">${wifi.interface}</div>
            </div>
          </div>
          <div class="wifi-actions">
            <button class="btn btn-danger" onclick="disableWifiAP()" id="disable-wifi-btn">
              Disable WiFi AP
            </button>
          </div>
        </div>
      `;
    }
  },

  'wifi-ap-disabled': {
    title: 'WiFi Access Point',
    icon: '📡',
    order: 2,
    detector: (status) => !status.features.wifi_ap || status.data.wifi_ap === null,
    render: function(data) {
      return `
        <div class="block">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="wifi-status-disabled">
            <p>WiFi Access Point is currently disabled</p>
          </div>
          <div class="wifi-actions">
            <button class="btn btn-primary" onclick="enableWifiAP()" id="enable-wifi-btn">
              Enable WiFi AP
            </button>
          </div>
        </div>
      `;
    }
  },

  'cameras': {
    title: 'Cameras',
    icon: '📷',
    order: 4,
    detector: (status) => status.features.cameras && status.data.cameras.length > 0,
    render: function(data) {
      const cameras = data.cameras;
      const onlineCount = cameras.filter(c => c.online).length;

      const cameraCards = cameras.map(cam => `
        <div class="camera-card ${cam.online ? 'online' : 'offline'}" data-camera="${cam.id}">
          <div class="camera-header">
            <h4>${cam.id}</h4>
            <span class="badge ${cam.online ? 'online' : 'offline'}" data-camera-badge>
              ${cam.online ? '●' : '○'}
            </span>
          </div>
          <div class="camera-meta">
            <span class="camera-type">${cam.type.toUpperCase()}</span>
            <span class="camera-address-inline">${cam.address}</span>
          </div>
          <div class="camera-position-row" onclick="editCameraPosition(this, '${cam.id}')" title="Click to edit position">
            <span class="camera-position-text">📍 ${cam.position || 'not set'}</span>
            <span class="btn-icon">✏</span>
          </div>
          <div class="camera-thumbnail-area">
            ${cam.latest_image ? `
              <div class="camera-thumbnail" onclick="openImageModal('${cam.id}', '${cam.id} - ${cam.position || ''}')" title="Click to enlarge">
                <img src="/api/images/${cam.id}/latest?t=${Date.now()}" alt="${cam.id}" loading="lazy" />
                <div class="thumbnail-overlay"><span>🔍</span></div>
              </div>
            ` : cam.online ? `
              <div class="camera-no-image">No images captured yet</div>
            ` : `
              <div class="camera-error">${cam.error || 'Disconnected'}</div>
            `}
          </div>
          <div class="camera-info">
            <small data-camera-last-capture>Last: ${cam.last_capture || 'N/A'}</small>
            <small>Interval: ${cam.capture_interval}s</small>
          </div>
          <div class="camera-actions">
            <button class="btn-cam" onclick="forceCapture('${cam.id}')" ${!cam.online ? 'disabled' : ''} title="Force capture now">
              📸 Capture
            </button>
            <button class="btn-cam btn-cam-secondary" onclick="restartCamera('${cam.id}')" title="Restart camera">
              ↻
            </button>
          </div>
        </div>
      `).join('');

      return `
        <div class="block wide">
          <h3>
            <span class="icon">${this.icon}</span> ${this.title}
            <span class="count">(${onlineCount}/${cameras.length} online)</span>
          </h3>
          <div class="camera-grid">${cameraCards}</div>
        </div>
      `;
    }
  },

  'storage': {
    title: 'Storage',
    icon: '💾',
    order: 5,
    detector: (status) => status.features.storage && status.data.storage !== null,
    render: function(data) {
      const storage = data.storage;
      const thresholdMb = (storage.cleanup_threshold_gb || storage.max_size_gb || 1) * 1024;
      const usedPercent = thresholdMb > 0
        ? Math.min(100, Math.round((storage.total_size_mb / thresholdMb) * 100))
        : 0;
      const barClass = usedPercent > 90 ? 'critical' : usedPercent > 70 ? 'warning' : '';

      return `
        <div class="block">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="metrics">
            <div class="metric-item">
              <div class="metric-label">Total Images</div>
              <div class="metric-value">${storage.total_images}</div>
            </div>
            <div class="metric-item">
              <div class="metric-label">Uploaded</div>
              <div class="metric-value success">${storage.uploaded_images}</div>
            </div>
            <div class="metric-item">
              <div class="metric-label">Storage Used</div>
              <div class="metric-value">${storage.total_size_mb}MB</div>
            </div>
          </div>
          <div class="storage-bar ${barClass}">
            <div class="storage-bar-fill" style="width: ${usedPercent}%"></div>
            <div class="storage-bar-label">${storage.total_size_mb}MB / ${thresholdMb >= 1024 ? ((thresholdMb/1024).toFixed(1) + 'GB') : (thresholdMb + 'MB')} (${usedPercent}%)</div>
          </div>
        </div>
      `;
    }
  },

  'network': {
    title: 'Network',
    icon: '🌐',
    order: 3,
    detector: (status) => status.data.network !== null,
    render: function(data) {
      const network = data.network;
      const mode = network.mode || 'ethernet';
      const modeLabel = (mode === 'wifi-client' || mode === 'wifi') ? 'WiFi' : 'Ethernet';
      const modeIcon = (mode === 'wifi-client' || mode === 'wifi') ? '📶' : '🔌';

      // Sort interfaces: WAN first, then others
      const sortedInterfaces = Object.entries(network.interfaces || {}).sort(([a], [b]) => {
        if (a === network.wan_interface) return -1;
        if (b === network.wan_interface) return 1;
        return a.localeCompare(b);
      });

      const interfaces = sortedInterfaces.map(([name, iface]) => {
        const isVpn = name.startsWith('zt');
        const typeLabel = isVpn ? 'VPN (ZeroTier)' : iface.type;
        const ips = (iface.ips || [iface.ip]).join(', ');
        return `
          <div class="network-interface">
            <div class="interface-row">
              <span class="interface-name">${name}</span>
              <span class="interface-ip">${ips}</span>
            </div>
            <div class="interface-type">${typeLabel}</div>
          </div>
        `;
      }).join('');

      return `
        <div class="block">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="network-mode-banner ${mode}">
            <span class="mode-icon">${modeIcon}</span>
            <span class="mode-label">Mode: ${modeLabel}</span>
          </div>
          <div class="network-internet-row">
            <span class="metric-label">Internet Connection</span>
            <div class="network-internet-pill ${network.upstream_online ? 'online' : 'offline'}">
              <span class="status-dot"></span>
              <span>${network.upstream_online ? 'Online' : 'Offline'}</span>
            </div>
          </div>
          <div class="network-interfaces">
            ${interfaces}
          </div>
        </div>
      `;
    }
  },

  'logs': {
    title: 'Recent Logs',
    icon: '📄',
    order: 6,
    detector: (status) => true,
    render: function(data) {
      // Logs will be fetched separately
      return `
        <div class="block wide">
          <h3>
            <span class="icon">${this.icon}</span> ${this.title}
            <div class="log-level-toggle">
              <button class="btn btn-small" id="log-level-btn" onclick="toggleLogLevel()">
                <span id="log-level-text">INFO</span>
              </button>
            </div>
          </h3>
          <div class="log-viewer" id="log-viewer">
            <div class="log-loading">Loading logs...</div>
          </div>
        </div>
      `;
    }
  },

  'updates': {
    title: 'Updates',
    icon: '🔄',
    order: 7,
    detector: (status) => status.data.update !== undefined && status.data.update !== null,
    render: function(data) {
      const u = data.update;
      const statusLabels = {
        'unknown': 'Unknown',
        'up_to_date': 'Up to date',
        'updated': 'Updated',
        'updating': 'Updating...',
        'check_failed': 'Check failed',
        'fetch_failed': 'Fetch failed',
        'preflight_failed': 'Preflight failed',
        'rollback_completed': 'Rolled back',
        'rollback_failed': 'Rollback failed',
        'rolling_back': 'Rolling back...',
      };
      const statusClass = u.consecutive_failures > 0 ? 'warning'
        : ['check_failed', 'fetch_failed', 'preflight_failed', 'rollback_failed'].includes(u.status) ? 'critical'
        : ['up_to_date', 'updated'].includes(u.status) ? 'ok'
        : '';
      const statusLabel = statusLabels[u.status] || u.status;

      const lastCheck = u.last_check ? formatTimestamp(u.last_check) : 'Never';
      const lastUpdate = u.last_update ? formatTimestamp(u.last_update) : 'Never';

      return `
        <div class="block">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="update-version-row">
            <div class="update-current">
              <span class="update-version-label">Current</span>
              <span class="update-version-value">v${u.current_version}</span>
            </div>
            ${u.latest_available ? `
              <div class="update-arrow">${u.update_available ? '→' : '='}</div>
              <div class="update-latest ${u.update_available ? 'available' : ''}">
                <span class="update-version-label">Latest</span>
                <span class="update-version-value">v${u.latest_available}</span>
              </div>
            ` : ''}
          </div>
          ${u.update_available ? `
            <div class="update-banner">Update available</div>
          ` : ''}
          <div class="update-details">
            <div class="update-detail-row">
              <span class="update-detail-label">Status</span>
              <span class="update-status-badge ${statusClass}">${statusLabel}</span>
            </div>
            <div class="update-detail-row">
              <span class="update-detail-label">Channel</span>
              <span class="update-detail-value">${u.channel}</span>
            </div>
            <div class="update-detail-row">
              <span class="update-detail-label">Last check</span>
              <span class="update-detail-value">${lastCheck}</span>
            </div>
            <div class="update-detail-row">
              <span class="update-detail-label">Last update</span>
              <span class="update-detail-value">${lastUpdate}</span>
            </div>
            ${u.consecutive_failures > 0 ? `
              <div class="update-detail-row">
                <span class="update-detail-label">Failures</span>
                <span class="update-detail-value critical">${u.consecutive_failures}</span>
              </div>
            ` : ''}
          </div>
        </div>
      `;
    }
  }
};

// Utility functions

function formatTimestamp(isoStr) {
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    const now = new Date();
    const diffMs = now - d;
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHrs = Math.floor(diffMin / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    return `${diffDays}d ago`;
  } catch (e) {
    return isoStr;
  }
}

function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`;
  } else if (hours > 0) {
    return `${hours}h ${minutes}m`;
  } else {
    return `${minutes}m`;
  }
}

function createBlock(blockConfig, data) {
  const blockEl = document.createElement('div');
  blockEl.className = 'block-wrapper';
  try {
    blockEl.innerHTML = blockConfig.render.call(blockConfig, data);
  } catch (error) {
    console.error(`Error rendering block ${blockConfig.title}:`, error);
    blockEl.innerHTML = `
      <div class="block">
        <h3><span class="icon">⚠️</span> ${blockConfig.title}</h3>
        <div class="error-message">
          <p>Failed to render this block</p>
        </div>
      </div>
    `;
  }
  return blockEl;
}

async function fetchStatus() {
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error('Failed to fetch status');
    return await response.json();
  } catch (error) {
    console.error('Error fetching status:', error);
    return null;
  }
}

async function fetchServiceStatus() {
  try {
    const response = await fetch('/api/service/status');
    if (!response.ok) return { active: false, status: 'error' };
    return await response.json();
  } catch (error) {
    console.error('Error fetching service status:', error);
    return { active: false, status: 'error' };
  }
}

function updateServiceStatusUI(status) {
  serviceStatus = status;
  updateNodeStatus();
}

function updateNodeStatus() {
  const el = document.getElementById('node-status');
  if (!el) return;
  const text = el.querySelector('.status-text');

  if (!serviceStatus.active && serviceStatus.status !== 'unknown') {
    el.className = 'node-status warning';
    text.textContent = 'Service stopped';
  } else if (serviceStatus.active) {
    el.className = 'node-status live';
    text.textContent = 'Live';
  } else {
    el.className = 'node-status';
    text.textContent = 'Connecting...';
  }
}

async function manualRefresh() {
  const btn = document.getElementById('refresh-btn');
  if (btn) {
    btn.disabled = true;
    btn.classList.add('refreshing');
  }

  // Fetch fresh data
  const [status, svcStatus] = await Promise.all([
    fetchStatus(),
    fetchServiceStatus()
  ]);

  if (status) {
    // Force full re-render
    statusData = null;
    await renderDashboard();
  }

  updateServiceStatusUI(svcStatus);

  if (btn) {
    btn.disabled = false;
    btn.classList.remove('refreshing');
  }
}

async function fetchLogs() {
  try {
    const response = await fetch('/api/logs?lines=20');
    if (!response.ok) throw new Error('Failed to fetch logs');
    const data = await response.json();
    return data.logs || [];
  } catch (error) {
    console.error('Error fetching logs:', error);
    return [];
  }
}

function updateLogs(logs) {
  const logViewer = document.getElementById('log-viewer');
  if (!logViewer) return;

  if (logs.length === 0) {
    logViewer.innerHTML = '<div class="log-empty">No logs available</div>';
    return;
  }

  const logLines = logs.map(line => {
    let className = 'log-line';
    if (line.includes('ERROR')) className += ' log-error';
    else if (line.includes('WARNING')) className += ' log-warning';
    else if (line.includes('INFO')) className += ' log-info';

    return `<div class="${className}">${escapeHtml(line)}</div>`;
  }).join('');

  logViewer.innerHTML = logLines;
  // Auto-scroll to bottom
  logViewer.scrollTop = logViewer.scrollHeight;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function renderDashboard(forceFullRender = false) {
  const status = await fetchStatus();
  if (!status) {
    const loadingEl = document.getElementById('loading');
    if (loadingEl) {
      loadingEl.innerHTML = `
        <div class="error-message">
          <h3>Failed to load status</h3>
          <p>Retrying in 5 seconds...</p>
        </div>
      `;
    }
    return;
  }

  // Force full render if requested (e.g., after WiFi toggle)
  if (forceFullRender) {
    statusData = null;
  }

  // Update header
  document.getElementById('node-id').textContent = status.node.id;
  document.getElementById('node-location').textContent = `📍 ${status.node.location}`;
  document.getElementById('version').textContent = status.node.version;
  document.getElementById('update-time').textContent = new Date().toLocaleTimeString();

  // Update network info in header
  if (status.data.network) {
    const network = status.data.network;
    const mode = network.mode || 'ethernet';
    const modeIcon = mode === 'wifi-client' ? '📶' : '🔌';

  }

  // Render blocks
  const container = document.getElementById('blocks-container');
  const loading = document.getElementById('loading');
  if (loading) loading.remove();

  // Only do full re-render on initial load or forced refresh
  // SSE handles incremental updates after that
  const isInitialLoad = statusData === null;

  if (isInitialLoad) {
    // Preserve log content to avoid flash on force refresh
    const existingLogContent = document.getElementById('log-viewer')?.innerHTML;

    // Clear container for fresh render
    container.innerHTML = '';

    // Sort blocks by order
    const sortedBlocks = Object.entries(BLOCKS).sort((a, b) => a[1].order - b[1].order);

    sortedBlocks.forEach(([key, blockConfig]) => {
      if (blockConfig.detector(status)) {
        const blockEl = createBlock(blockConfig, status.data);
        blockEl.dataset.blockKey = key;
        container.appendChild(blockEl);
      }
    });

    // Restore log content if we had any
    if (existingLogContent && existingLogContent !== '<div class="log-loading">Loading logs...</div>') {
      const logViewer = document.getElementById('log-viewer');
      if (logViewer) logViewer.innerHTML = existingLogContent;
    }
  }

  // Update log level button to show current state
  updateLogLevelButton();

  statusData = status;

  // Fetch and update logs in background (won't flash since content is preserved)
  fetchLogs().then(logs => updateLogs(logs));
}

// WiFi AP control functions

async function enableWifiAP() {
  const btn = document.getElementById('enable-wifi-btn');
  if (!btn) return;

  // Disable button and show loading state
  btn.disabled = true;
  btn.textContent = 'Enabling...';
  btn.classList.add('btn-loading');

  try {
    const response = await fetch('/api/wifi_ap/enable', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      }
    });

    const data = await response.json();

    if (response.ok && data.success) {
      // Show success message
      showNotification('WiFi AP enabled successfully', 'success');

      // Refresh dashboard after short delay (force full render for WiFi block update)
      setTimeout(() => {
        renderDashboard(true);
      }, 2000);
    } else {
      // Show error message
      const errorMsg = data.error || 'Failed to enable WiFi AP';
      showNotification(errorMsg, 'error');

      // Re-enable button
      btn.disabled = false;
      btn.textContent = 'Enable WiFi AP';
      btn.classList.remove('btn-loading');
    }
  } catch (error) {
    console.error('Error enabling WiFi AP:', error);
    showNotification('Network error: Could not enable WiFi AP', 'error');

    // Re-enable button
    btn.disabled = false;
    btn.textContent = 'Enable WiFi AP';
    btn.classList.remove('btn-loading');
  }
}

async function disableWifiAP() {
  const btn = document.getElementById('disable-wifi-btn');
  if (!btn) return;

  // Confirm action
  if (!confirm('Are you sure you want to disable the WiFi Access Point?')) {
    return;
  }

  // Disable button and show loading state
  btn.disabled = true;
  btn.textContent = 'Disabling...';
  btn.classList.add('btn-loading');

  try {
    const response = await fetch('/api/wifi_ap/disable', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      }
    });

    const data = await response.json();

    if (response.ok && data.success) {
      // Show success message
      showNotification('WiFi AP disabled successfully', 'success');

      // Refresh dashboard after short delay (force full render for WiFi block update)
      setTimeout(() => {
        renderDashboard(true);
      }, 2000);
    } else {
      // Show error message
      const errorMsg = data.error || 'Failed to disable WiFi AP';
      showNotification(errorMsg, 'error');

      // Re-enable button
      btn.disabled = false;
      btn.textContent = 'Disable WiFi AP';
      btn.classList.remove('btn-loading');
    }
  } catch (error) {
    console.error('Error disabling WiFi AP:', error);
    showNotification('Network error: Could not disable WiFi AP', 'error');

    // Re-enable button
    btn.disabled = false;
    btn.textContent = 'Disable WiFi AP';
    btn.classList.remove('btn-loading');
  }
}

// Log level control functions
// Levels cycle: WARNING (default, production) → INFO → DEBUG → WARNING
const LOG_LEVELS = ['WARNING', 'INFO', 'DEBUG'];
let currentLogLevel = 'WARNING';

async function fetchLogLevel() {
  try {
    const response = await fetch('/api/log_level');
    if (response.ok) {
      const data = await response.json();
      currentLogLevel = data.level || 'WARNING';
      updateLogLevelButton();
    }
  } catch (error) {
    console.error('Error fetching log level:', error);
  }
}

function updateLogLevelButton() {
  const btn = document.getElementById('log-level-btn');
  const text = document.getElementById('log-level-text');
  if (text) {
    text.textContent = currentLogLevel;
  }
  if (btn) {
    // Remove all level classes
    btn.classList.remove('log-level-warning', 'log-level-info', 'log-level-debug');
    // Add current level class
    btn.classList.add(`log-level-${currentLogLevel.toLowerCase()}`);
  }
}

async function toggleLogLevel() {
  const btn = document.getElementById('log-level-btn');
  if (!btn) return;

  // Cycle to next level: WARNING → INFO → DEBUG → WARNING
  const currentIndex = LOG_LEVELS.indexOf(currentLogLevel);
  const newLevel = LOG_LEVELS[(currentIndex + 1) % LOG_LEVELS.length];

  btn.disabled = true;

  try {
    const response = await fetch('/api/log_level', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level: newLevel })
    });

    const data = await response.json();

    if (response.ok && data.success) {
      currentLogLevel = newLevel;
      updateLogLevelButton();
      const levelDescriptions = {
        'WARNING': 'WARNING (only warnings & errors)',
        'INFO': 'INFO (normal operation)',
        'DEBUG': 'DEBUG (verbose)'
      };
      showNotification(`Log level: ${levelDescriptions[newLevel]}`, 'success');
    } else {
      showNotification(data.error || 'Failed to change log level', 'error');
    }
  } catch (error) {
    console.error('Error setting log level:', error);
    showNotification('Network error changing log level', 'error');
  }

  btn.disabled = false;
}

// Image modal for full-size camera images
function openImageModal(cameraId, cameraName) {
  // Create modal if it doesn't exist
  let modal = document.getElementById('image-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'image-modal';
    modal.className = 'image-modal';
    modal.innerHTML = `
      <div class="modal-backdrop" onclick="closeImageModal()"></div>
      <div class="modal-content">
        <div class="modal-header">
          <span class="modal-title"></span>
          <button class="modal-close" onclick="closeImageModal()">&times;</button>
        </div>
        <div class="modal-body">
          <img src="" alt="Camera image" />
          <div class="modal-loading">Loading...</div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }

  // Update modal content
  const img = modal.querySelector('.modal-body img');
  const title = modal.querySelector('.modal-title');
  const loading = modal.querySelector('.modal-loading');

  title.textContent = cameraName || cameraId;
  img.style.display = 'none';
  loading.style.display = 'block';

  // Load image with cache-busting
  img.onload = () => {
    loading.style.display = 'none';
    img.style.display = 'block';
  };
  img.onerror = () => {
    loading.textContent = 'Failed to load image';
  };
  img.src = `/api/images/${cameraId}/latest?t=${Date.now()}`;

  // Show modal
  modal.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeImageModal() {
  const modal = document.getElementById('image-modal');
  if (modal) {
    modal.classList.remove('open');
    document.body.style.overflow = '';
  }
}

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeImageModal();
});

function showNotification(message, type = 'info') {
  // Create notification element
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.textContent = message;

  // Add to body
  document.body.appendChild(notification);

  // Trigger animation
  setTimeout(() => {
    notification.classList.add('notification-show');
  }, 10);

  // Remove after 4 seconds
  setTimeout(() => {
    notification.classList.remove('notification-show');
    setTimeout(() => {
      notification.remove();
    }, 300);
  }, 4000);
}

// ========================================
// Camera Action Functions
// ========================================

async function forceCapture(cameraId) {
  try {
    const response = await fetch(`/api/cameras/${cameraId}/capture`, { method: 'POST' });
    const result = await response.json();
    if (result.ok) {
      showNotification(`Capture triggered for ${cameraId}`, 'success');
    } else {
      showNotification(result.error || 'Failed', 'error');
    }
  } catch (e) {
    showNotification('Service unavailable', 'error');
  }
}

async function restartCamera(cameraId) {
  if (!confirm(`Restart camera ${cameraId}?`)) return;
  try {
    const response = await fetch(`/api/cameras/${cameraId}/restart`, { method: 'POST' });
    const result = await response.json();
    showNotification(
      result.ok ? `${cameraId} restarting...` : (result.error || 'Failed'),
      result.ok ? 'success' : 'error'
    );
  } catch (e) {
    showNotification('Service unavailable', 'error');
  }
}

function editCameraPosition(row, cameraId) {
  // Already editing
  if (row.querySelector('input')) return;

  const textSpan = row.querySelector('.camera-position-text');
  const currentText = textSpan.textContent.replace(/^📍\s*/, '');
  const currentValue = currentText === 'not set' ? '' : currentText;

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'position-inline-input';
  input.value = currentValue;
  input.placeholder = 'e.g. north, entrance...';

  textSpan.style.display = 'none';
  row.querySelector('.btn-icon').style.display = 'none';
  row.insertBefore(input, textSpan);
  input.focus();
  input.select();

  async function save() {
    const position = input.value.trim();
    input.disabled = true;
    try {
      const response = await fetch(`/api/cameras/${cameraId}/position`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position })
      });
      const result = await response.json();
      if (result.ok) {
        showNotification(`Position updated for ${cameraId}`, 'success');
        manualRefresh();
      } else {
        showNotification(result.error || 'Failed', 'error');
        revert();
      }
    } catch (e) {
      showNotification('Service unavailable', 'error');
      revert();
    }
  }

  function revert() {
    input.remove();
    textSpan.style.display = '';
    row.querySelector('.btn-icon').style.display = '';
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    if (e.key === 'Escape') { e.preventDefault(); revert(); }
  });
  input.addEventListener('blur', save);

  // Stop click from bubbling back to the row
  input.addEventListener('click', (e) => e.stopPropagation());
}

// ========================================
// SSE (Server-Sent Events) Implementation
// ========================================

let eventSource = null;
let sseWasDisconnected = false;

function connectEventStream() {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource('/api/events');

  eventSource.addEventListener('health', (e) => {
    try {
      const health = JSON.parse(e.data);
      updateHealthData(health);
    } catch (error) {
      console.error('Error parsing health data:', error);
    }
  });

  eventSource.addEventListener('log', (e) => {
    try {
      const {line} = JSON.parse(e.data);
      appendLogLine(line);
    } catch (error) {
      console.error('Error parsing log data:', error);
    }
  });

  eventSource.addEventListener('status', (e) => {
    try {
      const status = JSON.parse(e.data);
      updateStatusData(status);
    } catch (error) {
      console.error('Error parsing status data:', error);
    }
  });

  eventSource.addEventListener('slow', (e) => {
    try {
      const data = JSON.parse(e.data);
      updateSlowData(data);
    } catch (error) {
      console.error('Error parsing slow data:', error);
    }
  });

  eventSource.onerror = () => {
    console.warn('SSE connection error, reconnecting in 5s...');
    sseWasDisconnected = true;
    updateConnectionStatus(false);
    eventSource.close();
    setTimeout(connectEventStream, 5000);
  };

  eventSource.onopen = () => {
    console.log('SSE connection established');
    updateConnectionStatus(true);

    // Refresh data after reconnection (version-change reload is handled by updateHealthData)
    if (sseWasDisconnected) {
      sseWasDisconnected = false;
      manualRefresh();
    }
  };
}

function updateConnectionStatus(connected) {
  if (!connected) {
    const el = document.getElementById('node-status');
    if (!el) return;
    el.className = 'node-status disconnected';
    el.querySelector('.status-text').textContent = 'Reconnecting...';
  } else {
    updateNodeStatus();
  }
}

// Selective update functions for SSE events

function updateHealthData(health) {
  // Auto-reload if server version changed (e.g. after an update)
  if (health.portal_version) {
    const displayedVersion = document.getElementById('version')?.textContent;
    if (displayedVersion && health.portal_version !== displayedVersion) {
      console.log(`Server version changed: ${displayedVersion} → ${health.portal_version}, reloading...`);
      location.reload();
      return;
    }
  }

  // Update timestamp
  const timeEl = document.getElementById('update-time');
  if (timeEl) {
    timeEl.textContent = new Date().toLocaleTimeString();
  }

  // Update system gauges
  if (health.system) {
    updateGauge('cpu', health.system.cpu_percent);
    updateGauge('memory', health.system.memory_percent, {
      detail: `${health.system.memory_used_mb}MB / ${health.system.memory_total_mb}MB`
    });
    updateGauge('disk', health.system.disk_percent, {
      detail: `${health.system.disk_used_gb}GB / ${health.system.disk_total_gb}GB`
    });
  }

  // Update camera cards from health socket data
  if (health.cameras) {
    Object.entries(health.cameras).forEach(([id, cam]) => {
      updateCameraCard(id, cam);
    });
  }

}

function updateGauge(type, value, options = {}) {
  const gauge = document.querySelector(`[data-gauge="${type}"]`);
  if (!gauge) return;

  const circle = gauge.querySelector('.circle');
  const percentage = gauge.querySelector('.percentage');
  const detail = gauge.querySelector('.gauge-detail');

  if (circle) {
    // Update stroke-dasharray for the circle
    circle.setAttribute('stroke-dasharray', `${value}, 100`);
    // Update color classes
    circle.classList.remove('critical', 'warning');
    if (value > 80) circle.classList.add('critical');
    else if (value > 60) circle.classList.add('warning');
  }

  if (percentage) {
    percentage.textContent = `${value}%`;
  }

  if (detail && options.detail) {
    detail.textContent = options.detail;
  }
}

function updateCameraCard(id, status) {
  const card = document.querySelector(`[data-camera="${id}"]`);
  if (!card) return;

  const isOnline = status.state === 'healthy' && status.thread_alive;

  // Update card class
  card.classList.remove('online', 'offline');
  card.classList.add(isOnline ? 'online' : 'offline');

  // Update badge
  const badge = card.querySelector('[data-camera-badge]');
  if (badge) {
    badge.classList.remove('online', 'offline');
    badge.classList.add(isOnline ? 'online' : 'offline');
    badge.textContent = isOnline ? '●' : '○';
  }

  // Update last capture time
  const lastCapture = card.querySelector('[data-camera-last-capture]');
  if (lastCapture && status.last_success_age !== undefined) {
    lastCapture.textContent = `Last: ${formatAge(status.last_success_age)}`;
  }
}

function formatAge(seconds) {
  if (seconds === undefined || seconds === null) return 'N/A';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
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

  // Append to viewer
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

// Generic block re-renderer: merges dataOverrides into statusData and replaces the block in DOM
function rerenderBlock(blockKey, dataOverrides) {
  if (!statusData) return;
  const container = document.getElementById('blocks-container');
  if (!container) return;

  // Merge new data into statusData
  Object.assign(statusData.data, dataOverrides);

  const blockConfig = BLOCKS[blockKey];
  if (!blockConfig) return;

  // Find existing block wrapper by matching the block's rendered content
  const wrappers = container.querySelectorAll('.block-wrapper');
  for (const wrapper of wrappers) {
    // Match by checking if this wrapper was rendered by this block config
    // Use a data attribute for reliable matching
    if (wrapper.dataset.blockKey === blockKey) {
      const newBlock = createBlock(blockConfig, statusData.data);
      newBlock.dataset.blockKey = blockKey;
      wrapper.replaceWith(newBlock);
      return;
    }
  }
}

function updateStatusData(status) {
  // 20s tier: network, update state, wifi AP

  if (status.network) {
    rerenderBlock('network', { network: status.network });
  }

  if (status.update) {
    rerenderBlock('updates', { update: status.update });
  }

  // WiFi AP: re-render whichever wifi block is visible
  if (status.wifi_ap !== undefined) {
    if (statusData) statusData.data.wifi_ap = status.wifi_ap;
    // Determine which wifi block to show
    if (status.wifi_ap) {
      rerenderBlock('wifi-ap', { wifi_ap: status.wifi_ap });
      // Remove disabled block if present
      const container = document.getElementById('blocks-container');
      const disabled = container?.querySelector('[data-block-key="wifi-ap-disabled"]');
      if (disabled) disabled.remove();
    } else {
      rerenderBlock('wifi-ap-disabled', {});
      const container = document.getElementById('blocks-container');
      const enabled = container?.querySelector('[data-block-key="wifi-ap"]');
      if (enabled) enabled.remove();
    }
  }
}

function updateSlowData(data) {
  // 500s tier: storage
  if (data.storage) {
    rerenderBlock('storage', { storage: data.storage });
  }
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', async () => {
  // 1. Initial full render
  await renderDashboard();

  // 2. Fetch initial log level and service status
  await Promise.all([
    fetchLogLevel(),
    fetchServiceStatus().then(updateServiceStatusUI)
  ]);

  // 3. Connect SSE for real-time updates (replaces polling)
  connectEventStream();

  // 4. Periodic syncs (service status and log level not in SSE)
  setInterval(fetchLogLevel, 30000);
  setInterval(() => fetchServiceStatus().then(updateServiceStatusUI), 30000);
});
