'use strict';

const socket = io();

const typeCharts = {};
const typeDatasets = {};
const COLORS = ['#FFD005', '#e44c55', '#4ecdc4', '#a29bfe', '#fd79a8'];

// ------------------------------------------------------------
// Time filter state
// ------------------------------------------------------------
const TIME_FILTERS = {
    '15min':  { label: '15 min',  minutes: 15,  points: 30 },
    '1h':     { label: '1 hour',  minutes: 60,  points: 60 },
    '6h':     { label: '6 hours', minutes: 360, points: 120 },
    '24h':    { label: '24 hours',minutes: 1440,points: 240 },
};
let currentTimeFilter = '1h';   // default

// ------------------------------------------------------------
// Alarm state per sensor – { sensor_id: "high" | "low" | null }
// ------------------------------------------------------------
const sensorAlarmState = {};

// ------------------------------------------------------------
// Utility functions
// ------------------------------------------------------------
function getColor(index) {
    return COLORS[index % COLORS.length];
}

function updateClock() {
    const now = new Date();
    document.getElementById('current-time').textContent =
        now.toLocaleTimeString('pt-PT', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ------------------------------------------------------------
// Alarm badge counter
// ------------------------------------------------------------
function updateAlarmCounter() {
    const activeAlarms = Object.values(sensorAlarmState).filter(s => s !== null).length;
    const badge = document.getElementById('alarm-badge');
    const count = document.getElementById('alarm-count');
    if (activeAlarms > 0) {
        badge.classList.add('visible');
        count.textContent = activeAlarms;
    } else {
        badge.classList.remove('visible');
        count.textContent = '0';
    }
}

function setSensorAlarm(sensorId, alarmType) {
    sensorAlarmState[sensorId] = alarmType;
    const card = document.getElementById(`card-${sensorId}`);
    if (!card) return;

    card.classList.remove('alarm-high', 'alarm-low');
    if (alarmType === 'high') {
        card.classList.add('alarm-high');
    } else if (alarmType === 'low') {
        card.classList.add('alarm-low');
    }
    updateAlarmCounter();
}

// ------------------------------------------------------------
// Time filter buttons
// ------------------------------------------------------------
function createTimeFilterButtons() {
    const container = document.getElementById('time-filter-container');
    if (!container) return;

    Object.entries(TIME_FILTERS).forEach(([key, filter]) => {
        const btn = document.createElement('button');
        btn.className = 'time-filter-btn';
        btn.textContent = filter.label;
        btn.dataset.filter = key;
        if (key === currentTimeFilter) btn.classList.add('active');

        btn.addEventListener('click', () => {
            // Update active state
            document.querySelectorAll('.time-filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTimeFilter = key;
            // Reload all type histories with the new time window
            reloadAllHistories();
        });

        container.appendChild(btn);
    });
}

async function reloadAllHistories() {
    const filter = TIME_FILTERS[currentTimeFilter];
    const limit = filter.points;

    for (const [type, datasets] of Object.entries(typeDatasets)) {
        for (const sensorId of Object.keys(datasets)) {
            try {
                const resp = await fetch(`/api/history?sensor_id=${sensorId}&limit=${limit}`);
                if (!resp.ok) continue;
                const data = await resp.json();
                typeDatasets[type][sensorId].data = data.map(d => ({
                    x: new Date(d.timestamp),
                    y: d.value,
                }));
            } catch (err) {
                console.error(`Error reloading history for ${sensorId}:`, err);
            }
        }
        updateTypeChart(type);
    }
}

// ------------------------------------------------------------
// 1. Busca sensores e renderiza cartões (primeira carga)
// ------------------------------------------------------------
async function fetchSensors() {
    try {
        const resp = await fetch('/api/sensors');
        if (!resp.ok) throw new Error('Failed to fetch sensors');
        const sensors = await resp.json();

        renderSensorCards(sensors);
        return sensors;
    } catch (err) {
        console.error('Error fetching sensors:', err);
        return [];
    }
}

function renderSensorCards(sensors) {
    const container1 = document.getElementById('sensors-container-1');
    const container2 = document.getElementById('sensors-container-2');
    container1.innerHTML = '';
    container2.innerHTML = '';

    const group1 = sensors.filter(s => s.sensor_id.endsWith('-001'));
    const group2 = sensors.filter(s => s.sensor_id.endsWith('-002'));

    const renderCard = (sensor) => {
        const card = document.createElement('div');
        card.className = `sensor-card ${sensor.online ? 'online' : 'offline'}`;
        card.id = `card-${sensor.sensor_id}`;
        const lastSeen = sensor.last_seen
            ? new Date(sensor.last_seen).toLocaleTimeString('pt-PT')
            : 'N/A';

        card.innerHTML = `
            <div class="sensor-header">
                <span>${sensor.sensor_id}</span>
                <span class="status-dot" title="${sensor.online ? 'Online' : 'Offline'}"></span>
            </div>
            <div class="sensor-value">${sensor.value !== null ? sensor.value : '--'}</div>
            <div class="sensor-unit">${sensor.unit} (${sensor.type})</div>
            <div class="sensor-time">Last seen: ${lastSeen}</div>
            <div class="sensor-last-alarm" id="last-alarm-${sensor.sensor_id}"></div>
        `;
        return card;
    };

    group1.forEach(s => container1.appendChild(renderCard(s)));
    group2.forEach(s => container2.appendChild(renderCard(s)));
}

async function fetchEvents() {
    try {
        const resp = await fetch('/api/events?limit=20');
        if (!resp.ok) return;
        const events = await resp.json();

        const container = document.getElementById('event-log-container');
        if (events.length === 0) {
            container.innerHTML = '<p class="event-empty">No events recorded yet.</p>';
            return;
        }

        let html = '';
        events.forEach(event => {
            const time = new Date(event.timestamp).toLocaleTimeString('pt-PT');
            let iconClass = 'info';
            if (event.type === 'sensor_offline') iconClass = 'offline';
            else if (event.type.includes('critical')) iconClass = 'critical';
            else if (event.type.includes('warning')) iconClass = 'warning';

            html += `
                <div class="event-item">
                    <span class="event-timestamp">${time}</span>
                    <span class="event-icon ${iconClass}"></span>
                    <span class="event-message">${event.message}</span>
                </div>
            `;
        });
        container.innerHTML = html;
    } catch (err) {
        console.error('Error fetching events:', err);
    }
}

// ------------------------------------------------------------
// 2. WebSocket handlers
// ------------------------------------------------------------
socket.on('sensor_update', (data) => {
    // Atualiza o cartão do sensor
    const card = document.getElementById(`card-${data.sensor_id}`);
    if (card) {
        const valueEl = card.querySelector('.sensor-value');
        const timeEl = card.querySelector('.sensor-time');
        const timestamp = new Date(data.timestamp).toLocaleTimeString('pt-PT');
        if (valueEl) valueEl.textContent = data.value;
        if (timeEl) timeEl.textContent = `Last seen: ${timestamp}`;
    }

    // Atualiza dados para o gráfico
    if (!typeDatasets[data.type]) typeDatasets[data.type] = {};
    if (!typeDatasets[data.type][data.sensor_id]) {
        typeDatasets[data.type][data.sensor_id] = { color: getColor(0), data: [] };
    }
    const dataset = typeDatasets[data.type][data.sensor_id];
    dataset.data.push({ x: new Date(data.timestamp), y: data.value });
    if (dataset.data.length > TIME_FILTERS[currentTimeFilter].points) {
        dataset.data.shift();
    }
    updateTypeChart(data.type);
});

socket.on('sensor_heartbeat', (data) => {
    const card = document.getElementById(`card-${data.sensor_id}`);
    if (card) {
        card.classList.remove('offline');
        card.classList.add('online');
        const dot = card.querySelector('.status-dot');
        if (dot) dot.title = 'Online';
    }
});

socket.on('new_event', (data) => {
    // Adiciona ao Event Log
    const container = document.getElementById('event-log-container');
    const time = new Date(data.timestamp).toLocaleTimeString('pt-PT');

    let iconClass = 'info';
    if (data.criticality === 'critical') iconClass = 'critical';
    else if (data.criticality === 'warning') iconClass = 'warning';
    else if (data.type === 'sensor_offline') iconClass = 'offline';

    const emptyMsg = container.querySelector('.event-empty');
    if (emptyMsg) emptyMsg.remove();

    const eventItem = document.createElement('div');
    eventItem.className = 'event-item';
    eventItem.innerHTML = `
        <span class="event-timestamp">${time}</span>
        <span class="event-icon ${iconClass}"></span>
        <span class="event-message">${data.message}</span>
    `;
    container.insertBefore(eventItem, container.firstChild);

    while (container.children.length > 20) {
        container.removeChild(container.lastChild);
    }

    // Atualiza estado visual do cartão
    if (data.type === 'high_value') {
        setSensorAlarm(data.sensor_id, 'high');
    } else if (data.type === 'low_value') {
        setSensorAlarm(data.sensor_id, 'low');
    } else if (data.type === 'high_value_clear' || data.type === 'low_value_clear') {
        setSensorAlarm(data.sensor_id, null);
    }

    // Atualiza "last alarm" no cartão
    const lastAlarmEl = document.getElementById(`last-alarm-${data.sensor_id}`);
    if (lastAlarmEl) {
        lastAlarmEl.textContent = data.message;
        lastAlarmEl.style.display = 'block';
        if (data.type.includes('clear')) {
            setTimeout(() => { lastAlarmEl.style.display = 'none'; }, 5000);
        }
    }
});

// ------------------------------------------------------------
// 3. Gráficos por tipo (criados apenas na inicialização)
// ------------------------------------------------------------
function createTypeCharts(types) {
    const container = document.getElementById('type-trends-container');
    container.innerHTML = '';

    for (const [type, sensors] of Object.entries(types)) {
        const card = document.createElement('div');
        card.className = 'type-trend-card';
        card.id = `type-trend-${type}`;
        card.innerHTML = `
            <h3>${type.toUpperCase()} Trends</h3>
            <div class="chart-wrapper">
                <canvas id="chart-${type}"></canvas>
            </div>
        `;
        container.appendChild(card);

        if (!typeDatasets[type]) typeDatasets[type] = {};

        const datasets = sensors.map((sensor, index) => {
            const color = getColor(index);
            if (!typeDatasets[type][sensor.sensor_id]) {
                typeDatasets[type][sensor.sensor_id] = { color, data: [] };
            }
            return {
                label: sensor.sensor_id,
                data: [],
                borderColor: color,
                backgroundColor: 'transparent',
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 2,
            };
        });

        const ctx = document.getElementById(`chart-${type}`).getContext('2d');
        typeCharts[type] = new Chart(ctx, {
            type: 'line',
            data: { labels: [], datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: {
                            color: '#cccccc',
                            font: { family: 'Inter', size: 10 },
                            usePointStyle: true,
                            boxWidth: 8,
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { display: false },
                        grid: { display: false }
                    },
                    y: {
                        ticks: {
                            color: '#aaaaaa',
                            font: { family: 'Inter', size: 9 },
                            maxTicksLimit: 5,
                        },
                        grid: { color: '#2a2a2a' },
                    }
                }
            }
        });
    }
}

async function loadTypeHistories(types) {
    const limit = TIME_FILTERS[currentTimeFilter].points;
    for (const [type, sensors] of Object.entries(types)) {
        for (const sensor of sensors) {
            try {
                const resp = await fetch(`/api/history?sensor_id=${sensor.sensor_id}&limit=${limit}`);
                if (!resp.ok) continue;
                const data = await resp.json();
                typeDatasets[type][sensor.sensor_id].data = data.map(d => ({
                    x: new Date(d.timestamp),
                    y: d.value,
                }));
            } catch (err) {
                console.error(`Error loading history for ${sensor.sensor_id}:`, err);
            }
        }
        updateTypeChart(type);
    }
}

function updateTypeChart(type) {
    const chart = typeCharts[type];
    if (!chart || !typeDatasets[type]) return;

    const allData = Object.values(typeDatasets[type]);
    const labels = allData[0]?.data.map(d => d.x.toLocaleTimeString('pt-PT')) || [];

    let minVal = Infinity;
    let maxVal = -Infinity;
    allData.forEach(dataset => {
        dataset.data.forEach(point => {
            if (point.y < minVal) minVal = point.y;
            if (point.y > maxVal) maxVal = point.y;
        });
    });

    if (minVal === Infinity || maxVal === -Infinity) return;

    const marginTop = (maxVal - minVal) * 0.30;
    const marginBottom = (maxVal - minVal) * 0.10;
    let dataMin = minVal - marginBottom;
    let dataMax = maxVal + marginTop;

    if (dataMax - dataMin < 4) {
        const center = (dataMin + dataMax) / 2;
        dataMin = center - 2;
        dataMax = center + 2;
    }

    let step = (dataMax - dataMin) / 4;
    step = Math.ceil(step);
    if (step < 1) step = 1;

    const yMin = Math.floor(dataMin / step) * step;
    const yMax = yMin + step * 4;

    chart.options.scales.y.min = yMin;
    chart.options.scales.y.max = yMax;
    chart.options.scales.y.ticks = {
        stepSize: step,
        callback: function(value) { return value; },
        maxTicksLimit: 5,
        color: '#aaaaaa',
        font: { family: 'Inter', size: 9 }
    };

    chart.data.labels = labels;
    chart.data.datasets.forEach(ds => {
        ds.data = typeDatasets[type][ds.label]?.data.map(d => d.y) || [];
    });
    chart.update();
}

// ------------------------------------------------------------
// 4. Verificação periódica de sensores offline
// ------------------------------------------------------------
setInterval(async () => {
    try {
        const resp = await fetch('/api/sensors');
        if (!resp.ok) return;
        const sensors = await resp.json();
        sensors.forEach(sensor => {
            const card = document.getElementById(`card-${sensor.sensor_id}`);
            if (card) {
                if (!sensor.online) {
                    card.classList.remove('online');
                    card.classList.add('offline');
                    const dot = card.querySelector('.status-dot');
                    if (dot) dot.title = 'Offline';
                }
            }
        });
    } catch (err) {
        console.error('Error checking offline sensors:', err);
    }
}, 15000);

// ------------------------------------------------------------
// 5. Export button
// ------------------------------------------------------------
async function populateExportDropdown() {
    const resp = await fetch('/api/sensors');
    if (!resp.ok) return;
    const sensors = await resp.json();
    const select = document.getElementById('export-sensor-select');
    if (!select) return;
    sensors.forEach(sensor => {
        const option = document.createElement('option');
        option.value = sensor.sensor_id;
        option.textContent = sensor.sensor_id;
        select.appendChild(option);
    });
}

document.getElementById('btn-export-csv')?.addEventListener('click', () => {
    const sensorId = document.getElementById('export-sensor-select')?.value;
    const url = new URL('/api/report/csv', window.location.origin);
    if (sensorId) url.searchParams.set('sensor_id', sensorId);
    url.searchParams.set('limit', 5000);
    window.open(url, '_blank');
});

// ------------------------------------------------------------
// INICIALIZAÇÃO
// ------------------------------------------------------------
updateClock();
setInterval(updateClock, 1000);

(async function init() {
    // Create time filter buttons
    createTimeFilterButtons();

    // Populate export dropdown
    await populateExportDropdown();

    const sensors = await fetchSensors();
    if (sensors.length === 0) return;

    const types = {};
    sensors.forEach(s => {
        if (!types[s.type]) types[s.type] = [];
        types[s.type].push(s);
    });

    createTypeCharts(types);
    await loadTypeHistories(types);
    fetchEvents();
})();