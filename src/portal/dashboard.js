/**
 * SAI-Cam Modular Dashboard
 * Progressive enhancement with feature detection
 */

const REFRESH_INTERVAL = 5000; // 5 seconds
let statusData = null;

// Block Registry - Add new blocks here for auto-inclusion
const BLOCKS = {
  'system-resources': {
    title: 'System Resources',
    icon: '🖥️',
    order: 1,
    detector: (status) => true,  // Always present
    render: (data) => {
      const sys = data.system;
      const tempGauge = sys.temperature ? `
        <div class="gauge">
          <div class="gauge-label">Temperature</div>
          <div class="gauge-value ${sys.temperature > 70 ? 'critical' : sys.temperature > 60 ? 'warning' : ''}">${sys.temperature}°C</div>
        </div>
      ` : '';

      return `
        <div class="block">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="gauges">
            <div class="gauge">
              <div class="gauge-label">CPU</div>
              <div class="gauge-circle">
                <svg viewBox="0 0 36 36" class="circular-chart">
                  <path class="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <path class="circle ${sys.cpu_percent > 80 ? 'critical' : sys.cpu_percent > 60 ? 'warning' : ''}"
                        stroke-dasharray="${sys.cpu_percent}, 100"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <text x="18" y="20.35" class="percentage">${sys.cpu_percent}%</text>
                </svg>
              </div>
            </div>
            <div class="gauge">
              <div class="gauge-label">Memory</div>
              <div class="gauge-circle">
                <svg viewBox="0 0 36 36" class="circular-chart">
                  <path class="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <path class="circle ${sys.memory_percent > 80 ? 'critical' : sys.memory_percent > 60 ? 'warning' : ''}"
                        stroke-dasharray="${sys.memory_percent}, 100"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <text x="18" y="20.35" class="percentage">${sys.memory_percent}%</text>
                </svg>
              </div>
              <div class="gauge-detail">${sys.memory_used_mb}MB / ${sys.memory_total_mb}MB</div>
            </div>
            <div class="gauge">
              <div class="gauge-label">Disk</div>
              <div class="gauge-circle">
                <svg viewBox="0 0 36 36" class="circular-chart">
                  <path class="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <path class="circle ${sys.disk_percent > 80 ? 'critical' : sys.disk_percent > 60 ? 'warning' : ''}"
                        stroke-dasharray="${sys.disk_percent}, 100"
                        d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                  <text x="18" y="20.35" class="percentage">${sys.disk_percent}%</text>
                </svg>
              </div>
              <div class="gauge-detail">${sys.disk_used_gb}GB / ${sys.disk_total_gb}GB</div>
            </div>
            ${tempGauge}
          </div>
          <div class="uptime">Uptime: ${formatUptime(sys.uptime)}</div>
        </div>
      `;
    }
  },

  'wifi-ap': {
    title: 'WiFi Access Point',
    icon: '📡',
    order: 2,
    detector: (status) => status.features.wifi_ap && status.data.wifi_ap !== null,
    render: (data) => {
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
        </div>
      `;
    }
  },

  'cameras': {
    title: 'Cameras',
    icon: '📷',
    order: 3,
    detector: (status) => status.features.cameras && status.data.cameras.length > 0,
    render: (data) => {
      const cameras = data.cameras;
      const onlineCount = cameras.filter(c => c.online).length;

      const cameraCards = cameras.map(cam => `
        <div class="camera-card ${cam.online ? 'online' : 'offline'}">
          <div class="camera-header">
            <h4>${cam.id}</h4>
            <span class="badge ${cam.online ? 'online' : 'offline'}">
              ${cam.online ? '●' : '○'}
            </span>
          </div>
          <div class="camera-type">${cam.type.toUpperCase()}</div>
          ${cam.position ? `<div class="camera-position">${cam.position}</div>` : ''}
          ${cam.online ? `
            ${cam.latest_image ? `
              <div class="camera-thumbnail">
                <img src="/api/images/${cam.id}/latest" alt="${cam.id}" />
              </div>
            ` : '<div class="camera-no-image">No images captured yet</div>'}
            <div class="camera-info">
              <small>Last: ${cam.last_capture || 'N/A'}</small>
              <small>Interval: ${cam.capture_interval}s</small>
            </div>
          ` : `
            <div class="camera-error">${cam.error || 'Disconnected'}</div>
            <div class="camera-address"><small>${cam.address}</small></div>
          `}
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
    order: 4,
    detector: (status) => status.features.storage && status.data.storage !== null,
    render: (data) => {
      const storage = data.storage;
      const pendingPercent = storage.total_images > 0
        ? Math.round((storage.pending_images / storage.total_images) * 100)
        : 0;

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
              <div class="metric-label">Pending Upload</div>
              <div class="metric-value ${storage.pending_images > 10 ? 'warning' : ''}">${storage.pending_images}</div>
            </div>
            <div class="metric-item">
              <div class="metric-label">Storage Used</div>
              <div class="metric-value">${storage.total_size_mb}MB</div>
            </div>
          </div>
          <div class="storage-bar">
            <div class="storage-bar-fill" style="width: ${pendingPercent}%"></div>
            <div class="storage-bar-label">${pendingPercent}% pending upload</div>
          </div>
        </div>
      `;
    }
  },

  'network': {
    title: 'Network',
    icon: '🌐',
    order: 5,
    detector: (status) => status.data.network !== null,
    render: (data) => {
      const network = data.network;
      const interfaces = Object.entries(network.interfaces || {}).map(([name, iface]) => `
        <div class="network-interface">
          <div class="interface-name">${name}</div>
          <div class="interface-ip">${iface.ip}</div>
          <div class="interface-type">${iface.type}</div>
        </div>
      `).join('');

      return `
        <div class="block">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="network-status">
            <div class="metric-item">
              <div class="metric-label">Upstream Internet</div>
              <div class="metric-value">
                <span class="badge ${network.upstream_online ? 'online' : 'offline'}">
                  ${network.upstream_online ? '● Online' : '○ Offline'}
                </span>
              </div>
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
    render: (data) => {
      // Logs will be fetched separately
      return `
        <div class="block wide">
          <h3><span class="icon">${this.icon}</span> ${this.title}</h3>
          <div class="log-viewer" id="log-viewer">
            <div class="log-loading">Loading logs...</div>
          </div>
        </div>
      `;
    }
  }
};

// Utility functions

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
  blockEl.innerHTML = blockConfig.render(data);
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

async function renderDashboard() {
  const status = await fetchStatus();
  if (!status) {
    document.getElementById('loading').innerHTML = `
      <div class="error-message">
        <h3>Failed to load status</h3>
        <p>Retrying in ${REFRESH_INTERVAL / 1000} seconds...</p>
      </div>
    `;
    return;
  }

  // Update header
  document.getElementById('node-id').textContent = `Node: ${status.node.id}`;
  document.getElementById('node-location').textContent = status.node.location;
  document.getElementById('version').textContent = status.node.version;
  document.getElementById('update-time').textContent = new Date().toLocaleTimeString();

  // Render blocks
  const container = document.getElementById('blocks-container');
  const loading = document.getElementById('loading');
  if (loading) loading.remove();

  // Clear existing blocks if this is a refresh
  if (statusData !== null) {
    container.innerHTML = '';
  }

  // Sort blocks by order
  const sortedBlocks = Object.entries(BLOCKS).sort((a, b) => a[1].order - b[1].order);

  sortedBlocks.forEach(([key, block]) => {
    if (block.detector(status)) {
      const blockEl = createBlock(block, status.data);
      container.appendChild(blockEl);
    }
  });

  statusData = status;

  // Fetch and update logs separately
  const logs = await fetchLogs();
  updateLogs(logs);
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', () => {
  renderDashboard();

  // Auto-refresh
  setInterval(renderDashboard, REFRESH_INTERVAL);
});
