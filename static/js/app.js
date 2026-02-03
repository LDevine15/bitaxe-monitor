/**
 * Bitaxe Monitor - Main Application
 */

const REFRESH_INTERVAL = 10000; // 10 seconds
let refreshTimer;
let chartTimer;
let hashrateChart = null;
let selectedChartDevice = ''; // Empty = swarm, otherwise device_id
let selectedChartRange = 120; // Minutes: 120, 480, 1440, 4320
let minersList = []; // Cache of miners for dropdown

// =================================================================
// Utility Functions
// =================================================================

function formatHashrate(ghps) {
    if (ghps >= 1000) {
        return (ghps / 1000).toFixed(2) + ' TH/s';
    }
    return ghps.toFixed(1) + ' GH/s';
}

function formatUptime(hours) {
    if (hours >= 24) {
        const days = Math.floor(hours / 24);
        const remainingHours = Math.floor(hours % 24);
        return `${days}d ${remainingHours}h`;
    }
    return hours.toFixed(1) + 'h';
}

function getTempClass(temp, warn = 65, critical = 70) {
    if (temp >= critical) return 'critical';
    if (temp >= warn) return 'warn';
    return 'good';
}

function getTempBarColor(temp) {
    if (temp >= 70) return 'var(--accent-red)';
    if (temp >= 65) return 'var(--accent-yellow)';
    return 'var(--accent-green)';
}

function formatDifficulty(diff) {
    if (diff == null) return '--';
    if (diff >= 1e12) return (diff / 1e12).toFixed(2) + ' T';
    if (diff >= 1e9)  return (diff / 1e9).toFixed(2) + ' G';
    if (diff >= 1e6)  return (diff / 1e6).toFixed(2) + ' M';
    if (diff >= 1e3)  return (diff / 1e3).toFixed(2) + ' K';
    return Math.round(diff).toString();
}

function getRangeLabel(minutes) {
    if (minutes >= 1440) return (minutes / 1440) + 'd';
    return (minutes / 60) + 'h';
}

// =================================================================
// Chart
// =================================================================

async function updateHashrateChart() {
    try {
        // Choose endpoint based on device selection
        const endpoint = selectedChartDevice
            ? `/api/metrics/hashrate-trend/${encodeURIComponent(selectedChartDevice)}?minutes=${selectedChartRange}&buckets=60`
            : `/api/swarm/hashrate-trend?minutes=${selectedChartRange}&buckets=60`;

        const response = await fetch(endpoint);
        if (!response.ok) return;

        const { labels, data } = await response.json();
        if (!labels || !data) return;

        // Convert GH/s to TH/s
        const dataTHs = data.map(v => v ? v / 1000 : 0);

        // Calculate 2h average
        const validData = dataTHs.filter(v => v > 0);
        const avg = validData.length > 0
            ? validData.reduce((a, b) => a + b, 0) / validData.length
            : 0;
        const avgLine = dataTHs.map(() => avg);

        // Update title with device name, range, and average
        const deviceLabel = selectedChartDevice || 'Swarm';
        const rangeLabel = getRangeLabel(selectedChartRange);
        document.getElementById('chartTitle').textContent = `${deviceLabel} Hashrate (${rangeLabel}) — Avg: ${avg.toFixed(2)} TH/s`;

        const ctx = document.getElementById('hashrateChart').getContext('2d');

        // Determine chart label
        const chartLabel = selectedChartDevice ? `${selectedChartDevice} Hashrate` : 'Swarm Hashrate';

        if (hashrateChart) {
            // Update existing chart
            hashrateChart.data.labels = labels;
            hashrateChart.data.datasets[0].data = dataTHs;
            hashrateChart.data.datasets[0].label = chartLabel;
            hashrateChart.data.datasets[1].data = avgLine;
            hashrateChart.update('none');
        } else {
            // Create new chart
            hashrateChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: chartLabel,
                        data: dataTHs,
                        borderColor: '#58a6ff',
                        backgroundColor: 'rgba(88, 166, 255, 0.1)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 0,
                        borderWidth: 2
                    }, {
                        label: '2h Average',
                        data: avgLine,
                        borderColor: '#d29922',
                        borderWidth: 2,
                        borderDash: [6, 4],
                        pointRadius: 0,
                        fill: false
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255,255,255,0.1)' },
                            ticks: { color: '#8b949e', maxTicksLimit: 8 }
                        },
                        y: {
                            grid: { color: 'rgba(255,255,255,0.1)' },
                            ticks: {
                                color: '#8b949e',
                                callback: function(value) {
                                    return value.toFixed(2) + ' TH/s';
                                }
                            },
                            beginAtZero: false
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    }
                }
            });
        }
    } catch (error) {
        console.error('Chart error:', error);
    }
}

// =================================================================
// Miner Cards
// =================================================================

function createMinerCard(miner) {
    const card = document.createElement('div');
    card.className = `miner-card ${miner.online ? '' : 'offline'}`;
    if (miner.online) {
        card.style.cursor = 'pointer';
        card.onclick = () => openControlModal(miner);
    }

    if (!miner.online) {
        card.innerHTML = `
            <div class="miner-header">
                <span class="miner-name">${miner.name}</span>
                <span class="miner-status offline">Offline</span>
            </div>
            <div style="color: var(--text-secondary); text-align: center; padding: 20px;">
                No data available
            </div>
        `;
        return card;
    }

    const asicTempClass = getTempClass(miner.asic_temp);
    const vregTempClass = getTempClass(miner.vreg_temp, 70, 80);
    const tempPercent = Math.min((miner.asic_temp / 80) * 100, 100);
    const voltageClass = miner.input_voltage < 4.8 ? 'critical' : miner.input_voltage < 4.9 ? 'warn' : '';

    card.innerHTML = `
        <div class="miner-header">
            <span class="miner-name">${miner.name}</span>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span class="miner-status">Online</span>
                <span style="color: var(--text-secondary); font-size: 12px;" title="Click to configure">&#9881;</span>
            </div>
        </div>
        <div class="miner-stats">
            <div class="miner-stat">
                <span class="miner-stat-label">Hashrate</span>
                <span class="miner-stat-value">${formatHashrate(miner.hashrate)}</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">Efficiency</span>
                <span class="miner-stat-value">${miner.efficiency} J/TH</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">Frequency</span>
                <span class="miner-stat-value">${miner.frequency} MHz</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">Core Voltage</span>
                <span class="miner-stat-value">${miner.core_voltage} mV</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">Power</span>
                <span class="miner-stat-value">${miner.power}W</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">Input Voltage</span>
                <span class="miner-stat-value ${voltageClass}">${miner.input_voltage}V</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">ASIC Temp</span>
                <span class="miner-stat-value ${asicTempClass}">${miner.asic_temp}°C</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">VRM Temp</span>
                <span class="miner-stat-value ${vregTempClass}">${miner.vreg_temp}°C</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">Uptime</span>
                <span class="miner-stat-value">${formatUptime(miner.uptime_hours)}</span>
            </div>
            <div class="miner-stat">
                <span class="miner-stat-label">Fan</span>
                <span class="miner-stat-value">${miner.fan_speed}% (${miner.fan_rpm} RPM)</span>
            </div>
            <div class="temp-bar">
                <div class="temp-bar-label">
                    <span>Temperature</span>
                    <span>${miner.asic_temp}°C / 80°C</span>
                </div>
                <div class="temp-bar-track">
                    <div class="temp-bar-fill" style="width: ${tempPercent}%; background: ${getTempBarColor(miner.asic_temp)}"></div>
                </div>
            </div>
        </div>
    `;
    return card;
}

// =================================================================
// Data Fetching
// =================================================================

async function fetchData() {
    const refreshBtn = document.getElementById('refreshBtn');
    const statusIndicator = document.getElementById('statusIndicator');

    refreshBtn.disabled = true;
    refreshBtn.textContent = 'Refreshing...';

    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);

        const response = await fetch('/swarm', { signal: controller.signal });
        clearTimeout(timeout);

        if (!response.ok) throw new Error('API error');

        const data = await response.json();

        // Update swarm stats
        document.getElementById('totalHashrate').textContent = formatHashrate(data.total_hashrate);
        document.getElementById('activeMiners').textContent = `${data.active_count}/${data.total_count}`;
        document.getElementById('avgEfficiency').textContent = `${data.avg_efficiency} J/TH`;
        document.getElementById('totalPower').textContent = `${data.total_power}W`;
        document.getElementById('bestDiff').textContent = formatDifficulty(data.best_diff);

        // Update miner grid
        const grid = document.getElementById('minerGrid');
        grid.innerHTML = '';
        data.miners.forEach(miner => {
            grid.appendChild(createMinerCard(miner));
        });

        // Update device selector dropdown if miners list changed
        if (JSON.stringify(minersList.map(m => m.name)) !== JSON.stringify(data.miners.map(m => m.name))) {
            minersList = data.miners;
            populateDeviceSelector();
        }

        // Update status
        statusIndicator.className = 'status-indicator';
        document.getElementById('lastUpdate').textContent = `Updated: ${new Date().toLocaleTimeString()}`;

    } catch (error) {
        console.error('Fetch error:', error);
        document.getElementById('statusIndicator').className = 'status-indicator offline';
        document.getElementById('lastUpdate').textContent = 'Connection error';

        const grid = document.getElementById('minerGrid');
        grid.innerHTML = `
            <div class="error-message" style="grid-column: 1 / -1;">
                Failed to connect to API server. Make sure api_server.py is running.
            </div>
        `;
    } finally {
        refreshBtn.disabled = false;
        refreshBtn.textContent = 'Refresh';
    }
}

// =================================================================
// Device Selector
// =================================================================

function populateDeviceSelector() {
    const select = document.getElementById('chartDeviceSelect');
    const currentValue = select.value;

    // Clear existing options except the first (All Miners)
    select.innerHTML = '<option value="">All Miners (Swarm)</option>';

    // Add each miner
    minersList.forEach(miner => {
        const option = document.createElement('option');
        option.value = miner.name;
        option.textContent = miner.name;
        select.appendChild(option);
    });

    // Restore selection if it still exists
    if (minersList.some(m => m.name === currentValue)) {
        select.value = currentValue;
    }
}

function onDeviceSelectChange(event) {
    selectedChartDevice = event.target.value;
    updateHashrateChart();
}

function onRangeSelectChange(event) {
    selectedChartRange = parseInt(event.target.value);
    updateHashrateChart();
}

// =================================================================
// Initialization
// =================================================================

function initApp() {
    // Set up chart control handlers
    document.getElementById('chartDeviceSelect').addEventListener('change', onDeviceSelectChange);
    document.getElementById('chartRangeSelect').addEventListener('change', onRangeSelectChange);

    // Initial fetch
    fetchData();
    updateHashrateChart();

    // Auto-refresh (stats every 10s, chart every 30s)
    refreshTimer = setInterval(fetchData, REFRESH_INTERVAL);
    chartTimer = setInterval(updateHashrateChart, 30000);

    // Pause refresh when tab is not visible
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            clearInterval(refreshTimer);
            clearInterval(chartTimer);
        } else {
            fetchData();
            updateHashrateChart();
            refreshTimer = setInterval(fetchData, REFRESH_INTERVAL);
            chartTimer = setInterval(updateHashrateChart, 30000);
        }
    });
}

// Start app when DOM is ready
document.addEventListener('DOMContentLoaded', initApp);
