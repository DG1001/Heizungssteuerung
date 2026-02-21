import mqtt from 'mqtt';
import {
  Chart,
  TimeScale,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import 'chartjs-adapter-date-fns';
import annotationPlugin from 'chartjs-plugin-annotation';
import zoomPlugin from 'chartjs-plugin-zoom';

import { initDB, saveMeasurement, loadRecent, pruneOld } from './db.js';

// ── Register Chart.js components ──────────────────────────────────────────────
Chart.register(
  TimeScale,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
  Legend,
  Filler,
  annotationPlugin,
  zoomPlugin,
);

// ── Config from .env ──────────────────────────────────────────────────────────
// Connect via same-origin proxy so wss:// works even if the broker has no TLS.
// Vite forwards /mqtt-proxy → VITE_MQTT_URL server-side (no mixed-content issue).
const _proto   = location.protocol === 'https:' ? 'wss' : 'ws';
const MQTT_URL = `${_proto}://${location.host}/mqtt-proxy`;
const MQTT_USER  = import.meta.env.VITE_MQTT_USER  || '';
const MQTT_PASS  = import.meta.env.VITE_MQTT_PASS  || '';
const MQTT_TOPIC = import.meta.env.VITE_MQTT_TOPIC || 'heizung/esp32';

const TOPIC_STATUS   = `${MQTT_TOPIC}/status`;
const TOPIC_SET_TEMP = `${MQTT_TOPIC}/set/target_temp`;

const MS_48H = 48 * 60 * 60 * 1000;
const MS_72H = 72 * 60 * 60 * 1000;

// ── Application state ─────────────────────────────────────────────────────────
let currentData = []; // { ts, temp, hum, heating }
let targetTemp  = null;
let activeHours = 12;
let chart       = null;
let mqttClient  = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const elBadge     = document.getElementById('mqtt-badge');
const elTemp      = document.getElementById('val-temp');
const elTarget    = document.getElementById('val-target');
const elHum       = document.getElementById('val-hum');
const elHeating   = document.getElementById('val-heating');
const elTargetIn  = document.getElementById('target-input');
const elTargetBtn = document.getElementById('target-btn');
const elResetBtn  = document.getElementById('zoom-reset-btn');
const zoomBtns    = document.querySelectorAll('.zoom-btn');

// ── Custom plugin: heating background rectangles ──────────────────────────────
const heatingBgPlugin = {
  id: 'heatingBg',
  beforeDatasetsDraw(chartInstance) {
    if (!currentData.length) return;

    const { ctx, chartArea, scales } = chartInstance;
    const xScale = scales.x;
    const { top, bottom } = chartArea;

    ctx.save();
    ctx.fillStyle = 'rgba(233, 69, 60, 0.12)';

    let segStart = null;

    for (let i = 0; i < currentData.length; i++) {
      const pt = currentData[i];
      const next = currentData[i + 1];

      if (pt.heating && segStart === null) {
        segStart = pt.ts;
      }

      if (segStart !== null && (!pt.heating || !next)) {
        const segEnd = pt.ts;
        const x1 = xScale.getPixelForValue(segStart);
        const x2 = xScale.getPixelForValue(segEnd);
        const clampedX1 = Math.max(x1, chartArea.left);
        const clampedX2 = Math.min(x2, chartArea.right);
        if (clampedX2 > clampedX1) {
          ctx.fillRect(clampedX1, top, clampedX2 - clampedX1, bottom - top);
        }
        segStart = null;
      }
    }

    ctx.restore();
  },
};

Chart.register(heatingBgPlugin);

// ── Chart init ────────────────────────────────────────────────────────────────
function buildChart() {
  const canvas = document.getElementById('main-chart');
  const ctx = canvas.getContext('2d');

  chart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [
        {
          label: 'Temperatur (°C)',
          data: [],
          borderColor: '#e94560',
          backgroundColor: 'rgba(233, 69, 96, 0.08)',
          fill: false,
          tension: 0.3,
          pointRadius: 2,
          pointHoverRadius: 5,
          yAxisID: 'yTemp',
          parsing: { xAxisKey: 'ts', yAxisKey: 'temp' },
        },
        {
          label: 'Luftfeuchtigkeit (%)',
          data: [],
          borderColor: '#4fc3f7',
          backgroundColor: 'rgba(79, 195, 247, 0.08)',
          fill: false,
          tension: 0.3,
          pointRadius: 2,
          pointHoverRadius: 5,
          yAxisID: 'yHum',
          parsing: { xAxisKey: 'ts', yAxisKey: 'hum' },
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      scales: {
        x: {
          type: 'time',
          time: {
            tooltipFormat: 'dd.MM. HH:mm',
            displayFormats: {
              minute: 'HH:mm',
              hour: 'HH:mm',
              day: 'dd.MM.',
            },
          },
          ticks: { color: '#9e9e9e', maxRotation: 0 },
          grid: { color: 'rgba(255,255,255,0.05)' },
        },
        yTemp: {
          type: 'linear',
          position: 'left',
          ticks: { color: '#e94560', callback: (v) => `${v}°C` },
          grid: { color: 'rgba(255,255,255,0.05)' },
          title: { display: true, text: 'Temperatur (°C)', color: '#e94560' },
        },
        yHum: {
          type: 'linear',
          position: 'right',
          min: 0,
          max: 100,
          ticks: { color: '#4fc3f7', callback: (v) => `${v}%` },
          grid: { drawOnChartArea: false },
          title: { display: true, text: 'Luftfeuchtigkeit (%)', color: '#4fc3f7' },
        },
      },
      plugins: {
        legend: {
          labels: { color: '#e0e0e0' },
        },
        tooltip: {
          callbacks: {
            afterBody(tooltipItems) {
              const idx = tooltipItems[0]?.dataIndex;
              if (idx == null || !currentData[idx]) return '';
              return `Heizung: ${currentData[idx].heating ? 'AN' : 'AUS'}`;
            },
          },
        },
        annotation: {
          annotations: {
            targetLine: {
              type: 'line',
              yMin: targetTemp,
              yMax: targetTemp,
              yScaleID: 'yTemp',
              borderColor: '#ffd54f',
              borderWidth: 2,
              borderDash: [8, 4],
              label: {
                display: true,
                content: `Ziel: ${targetTemp ?? '–'}°C`,
                color: '#ffd54f',
                backgroundColor: 'rgba(0,0,0,0.5)',
                position: 'start',
                font: { size: 11 },
              },
            },
          },
        },
        zoom: {
          pan: {
            enabled: true,
            mode: 'x',
          },
          zoom: {
            wheel: { enabled: true },
            pinch: { enabled: true },
            mode: 'x',
          },
        },
      },
    },
  });

  applyTimeRange(activeHours);
}

// ── Chart update ──────────────────────────────────────────────────────────────
function updateChart() {
  if (!chart) return;

  chart.data.datasets[0].data = currentData;
  chart.data.datasets[1].data = currentData;
  updateTargetAnnotation();
  chart.update('none');
}

function updateTargetAnnotation() {
  if (!chart) return;
  const ann = chart.options.plugins.annotation.annotations.targetLine;
  ann.yMin = targetTemp;
  ann.yMax = targetTemp;
  ann.label.content = `Ziel: ${targetTemp != null ? targetTemp.toFixed(1) : '–'}°C`;
}

function applyTimeRange(hours) {
  if (!chart) return;
  activeHours = hours;
  const now = Date.now();
  const minTs = now - hours * 60 * 60 * 1000;
  chart.zoomScale('x', { min: minTs, max: now }, 'none');
  chart.update('none');

  zoomBtns.forEach((btn) => {
    btn.classList.toggle('active', Number(btn.dataset.hours) === hours);
  });
}

// ── Status bar ────────────────────────────────────────────────────────────────
function updateStatusBar(msg) {
  elTemp.textContent    = msg.current_temp != null ? `${msg.current_temp.toFixed(1)} °C` : '–';
  elHum.textContent     = msg.current_hum  != null ? `${msg.current_hum.toFixed(1)} %`  : '–';
  elHeating.textContent = msg.heating ? 'AN' : 'AUS';
  elHeating.className   = `value ${msg.heating ? 'on' : 'off'}`;

  if (msg.target_temp != null) {
    targetTemp = msg.target_temp;
    elTarget.textContent = `${targetTemp.toFixed(1)} °C`;
    elTargetIn.value = targetTemp.toFixed(1);
    updateTargetAnnotation();
  }
}

// ── MQTT ──────────────────────────────────────────────────────────────────────
function connectMQTT() {
  setBadge('connecting');

  const opts = {
    protocolVersion: 4,
    reconnectPeriod: 5000,
    connectTimeout: 15000,
  };
  if (MQTT_USER) opts.username = MQTT_USER;
  if (MQTT_PASS) opts.password = MQTT_PASS;

  mqttClient = mqtt.connect(MQTT_URL, opts);

  mqttClient.on('connect', () => {
    setBadge('connected');
    setControlsEnabled(true);
    mqttClient.subscribe(TOPIC_STATUS, { qos: 0 });
  });

  mqttClient.on('disconnect', () => {
    setBadge('disconnected');
    setControlsEnabled(false);
  });

  mqttClient.on('offline', () => {
    setBadge('disconnected');
    setControlsEnabled(false);
  });

  mqttClient.on('error', (err) => {
    console.error('MQTT error:', err);
    setBadge('disconnected');
    setControlsEnabled(false);
  });

  mqttClient.on('message', async (topic, payload) => {
    if (topic !== TOPIC_STATUS) return;

    let msg;
    try {
      msg = JSON.parse(payload.toString());
    } catch (e) {
      console.warn('Invalid JSON from MQTT:', e);
      return;
    }

    updateStatusBar(msg);

    if (msg.current_temp == null || msg.current_hum == null) return;

    const record = {
      ts:      Date.now(),
      temp:    msg.current_temp,
      hum:     msg.current_hum,
      heating: !!msg.heating,
    };

    currentData.push(record);

    // Save to IndexedDB and prune
    try {
      await saveMeasurement(record);
      const cutoff = Date.now() - MS_72H;
      await pruneOld(cutoff);
      // Also prune in-memory
      currentData = currentData.filter((r) => r.ts >= cutoff);
    } catch (e) {
      console.warn('DB error:', e);
    }

    updateChart();
  });
}

function setBadge(state) {
  const labels = {
    connected:    'MQTT: Verbunden',
    disconnected: 'MQTT: Getrennt',
    connecting:   'MQTT: Verbinde …',
  };
  elBadge.textContent = labels[state] || state;
  elBadge.className   = `badge badge-${state}`;
}

function setControlsEnabled(on) {
  elTargetIn.disabled  = !on;
  elTargetBtn.disabled = !on;
}

// ── Controls ──────────────────────────────────────────────────────────────────
elTargetBtn.addEventListener('click', () => {
  const val = parseFloat(elTargetIn.value);
  if (isNaN(val) || !mqttClient?.connected) return;
  mqttClient.publish(TOPIC_SET_TEMP, String(val), { qos: 0 });
});

elTargetIn.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') elTargetBtn.click();
});

zoomBtns.forEach((btn) => {
  btn.addEventListener('click', () => applyTimeRange(Number(btn.dataset.hours)));
});

elResetBtn.addEventListener('click', () => applyTimeRange(activeHours));

// ── Bootstrap ─────────────────────────────────────────────────────────────────
async function main() {
  // Init IndexedDB
  try {
    await initDB();

    const since48h = Date.now() - MS_48H;
    const stored   = await loadRecent(since48h);
    // Sort ascending by ts
    stored.sort((a, b) => a.ts - b.ts);
    currentData = stored;
  } catch (e) {
    console.warn('IndexedDB not available:', e);
    currentData = [];
  }

  buildChart();
  updateChart();
  connectMQTT();
}

main();
