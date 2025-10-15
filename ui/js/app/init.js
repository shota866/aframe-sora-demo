import { createSoraClient } from '../net/sora-client.js';

const CTRL_SEND_HZ = 25;
const POSITION_SCALE = 0.02;
const POSITION_OFFSET = 240;
const CAR_HEIGHT = 0.6;
const DEG_PER_RAD = 180 / Math.PI;

const DEFAULT_CONFIG = {
  signalingUrls: ["wss://sora2.uclab.jp/signaling"],
  channelId: 'aframe-demo',
  ctrlLabel: '#ctrl',
  stateLabel: '#state',
  metadata: null,
  debug: false,
  mode: 'net',
};

const META_ENV = import.meta?.env ?? {};
// console.log(import.meta.env);
const ENV_CONFIG = DEFAULT_CONFIG;
// const ENV_CONFIG = {
//   signalingUrls: META_ENV.VITE_SORA_SIGNALING_URLS,
//   channelId: META_ENV.VITE_SORA_CHANNEL_ID,
//   ctrlLabel: META_ENV.VITE_CTRL_LABEL,
//   stateLabel: META_ENV.VITE_STATE_LABEL,
//   metadata: META_ENV.VITE_SORA_METADATA,
//   debug: META_ENV.VITE_SORA_DEBUG === '1' || META_ENV.VITE_SORA_DEBUG === 'true',
// };

function parseArray(input) {
  if (!input) return [];
  if (Array.isArray(input)) return input.filter(Boolean);
  if (typeof input === 'string') {
    return input
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
  }
  return [];
}

function parseMaybeJson(value) {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch (err) {
    console.warn('[init] failed to parse JSON value', value, err);
    return value;
  }
}

function resolveConfig() {
  const globalConfig = typeof window !== 'undefined' ? window.NET_CONFIG || {} : {};
  const bodyConfig = document.body?.dataset?.netConfig
    ? parseMaybeJson(document.body.dataset.netConfig)
    : {};
  const search = new URLSearchParams(window.location.search);
  const queryConfig = {};
  if (search.has('room')) queryConfig.channelId = search.get('room');
  if (search.has('ctrl')) queryConfig.ctrlLabel = search.get('ctrl');
  if (search.has('state')) queryConfig.stateLabel = search.get('state');
  if (search.has('debug')) queryConfig.debug = search.get('debug') !== '0';
  if (search.has('local')) queryConfig.mode = search.get('local') === '1' ? 'local' : 'net';

  const merged = Object.assign({}, DEFAULT_CONFIG, ENV_CONFIG, bodyConfig, globalConfig, queryConfig);
  merged.signalingUrls = parseArray(merged.signalingUrls || merged.signalingUrl);
  merged.channelId = merged.channelId || merged.room || merged.channel;
  merged.metadata = parseMaybeJson(merged.metadata);
  merged.localMode = String(merged.mode || '').toLowerCase() === 'local';
  return merged;
}

class KeyboardCtrlRepeater {
  constructor(options = {}) {
    this.hz = Number(options.hz) || CTRL_SEND_HZ;
    this.onDirection = options.onDirection;
    this.onInputChange = typeof options.onInputChange === 'function' ? options.onInputChange : null;
    this.intervalMs = Math.max(10, Math.round(1000 / this.hz));
    this.keys = new Set();
    this.timer = null;
    this._lastDirection = null;
    this._handleKeyDown = this._handleKeyDown.bind(this);
    this._handleKeyUp = this._handleKeyUp.bind(this);
  }

  start() {
    if (this.timer !== null) return;
    window.addEventListener('keydown', this._handleKeyDown);
    window.addEventListener('keyup', this._handleKeyUp);
    this.timer = window.setInterval(() => this._tick(), this.intervalMs);
  }

  stop() {
    if (this.timer !== null) {
      window.clearInterval(this.timer);
      this.timer = null;
    }
    this._lastDirection = null;
    window.removeEventListener('keydown', this._handleKeyDown);
    window.removeEventListener('keyup', this._handleKeyUp);
  }

  _handleKeyDown(event) {
    if (event.repeat) return;
    this.keys.add(event.code);
    this._notifyInput('keydown', event.code);
  }

  _handleKeyUp(event) {
    this.keys.delete(event.code);
    this._notifyInput('keyup', event.code);
  }

  _tick() {
    const direction = this._currentDirection();
    if (direction !== this._lastDirection) {
      this._lastDirection = direction;
      this._notifyInput(direction ? 'direction' : 'idle', null, direction);
      if (typeof this.onDirection === 'function') {
        this.onDirection(direction);
      }
    }
  }

  _currentDirection() {
    const up = this._isPressed('ArrowUp', 'KeyW');
    const down = this._isPressed('ArrowDown', 'KeyS');
    const left = this._isPressed('ArrowLeft', 'KeyA');
    const right = this._isPressed('ArrowRight', 'KeyD');

    if (up && !down) return 'UP';
    if (down && !up) return 'DOWN';
    if (left && !right) return 'LEFT';
    if (right && !left) return 'RIGHT';
    return null;
  }

  _isPressed(...codes) {
    return codes.some((code) => this.keys.has(code));
  }

  _notifyInput(type, key = null, directionOverride) {
    if (!this.onInputChange) return;
    const direction =
      directionOverride !== undefined ? directionOverride : this._currentDirection();
    const keys = Array.from(this.keys).sort();
    this.onInputChange({ type, key, direction, keys });
  }
}

function configureCarForNet(carEl) {
  if (!carEl) return;
  carEl.removeAttribute('car-drive');
  carEl.removeAttribute('dynamic-body');
  const dyn = carEl.components?.['dynamic-body'];
  if (dyn && dyn.el) {
    dyn.el.removeAttribute('dynamic-body');
  }
}

function applyServerState(carEl, state) {
  if (!carEl || !state) return;
  const x = Number(state.x);
  const y = Number(state.y);
  const theta = Number(state.theta);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return;

  const worldX = (x - POSITION_OFFSET) * POSITION_SCALE;
  const worldZ = -(y - POSITION_OFFSET) * POSITION_SCALE;
  const yawDeg = Number.isFinite(theta) ? 90 - theta * DEG_PER_RAD : 90;

  carEl.object3D.position.set(worldX, CAR_HEIGHT, worldZ);
  carEl.object3D.rotation.set(0, (yawDeg * Math.PI) / 180, 0);
  carEl.object3D.updateMatrixWorld(true);

  carEl.setAttribute('position', { x: worldX, y: CAR_HEIGHT, z: worldZ });
  carEl.setAttribute('rotation', { x: 0, y: yawDeg, z: 0 });
}

function createHud() {
  const labelEl = document.getElementById('netStatusLabel');
  const detailEl = document.getElementById('netStatusDetail');
  const metricsEl = document.getElementById('netMetrics');
  const poseEl = document.getElementById('poseInfo');

  function setConnection(level, details) {
    if (!labelEl) return;
    labelEl.dataset.level = level === 'connected' ? 'connected' : level === 'degraded' ? 'degraded' : 'disconnected';
    labelEl.textContent = level.toUpperCase();
    if (detailEl) {
      if (Array.isArray(details)) detailEl.textContent = details.join(' | ');
      else detailEl.textContent = details || '';
    }
  }

  function setMetrics({ ctrlCount, stateCount, latencyMs }) {
    if (!metricsEl) return;
    const latencyText = latencyMs == null ? 'n/a' : `${latencyMs.toFixed(1)}ms`;
    metricsEl.innerHTML = `
      <div>#ctrl sent: ${ctrlCount}</div>
      <div>#state recv: ${stateCount}</div>
      <div>latency: ${latencyText}</div>
    `;
  }

  function setPose(state) {
    if (!poseEl || !state) return;
    const x = Number(state.x);
    const y = Number(state.y);
    const theta = Number(state.theta);
    const safe = (value, digits = 1) =>
      Number.isFinite(value) ? value.toFixed(digits) : 'n/a';
    poseEl.textContent = `pos: ${safe(x)} ${safe(y)} | theta: ${safe(theta, 3)}`;
  }

  return { setConnection, setMetrics, setPose };
}

function formatNumber(value, digits = 2) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : 'n/a';
}

function createControlLogger() {
  let lastDirection = null;
  let lastStateLog = 0;
  let lastSend = { command: null, time: 0 };

  const now = () =>
    typeof performance !== 'undefined' && typeof performance.now === 'function'
      ? performance.now()
      : Date.now();

  const formatKeys = (keys) => (keys && keys.length ? keys.join(', ') : 'none');

  return {
    input(event) {
      if (!event) return;
      const { type, key, keys, direction } = event;
      const active = formatKeys(keys);
      if (type === 'keydown') {
        console.info(`[ctrl/input] keydown ${key} (active: ${active})`);
      } else if (type === 'keyup') {
        console.info(`[ctrl/input] keyup ${key} (active: ${active})`);
      } else if (type === 'direction') {
        if (direction !== lastDirection) {
          console.info(`[ctrl/input] direction -> ${direction}`);
          lastDirection = direction;
        }
      } else if (type === 'idle') {
        if (lastDirection !== null) {
          console.info('[ctrl/input] direction cleared (no active command)');
          lastDirection = null;
        }
      }
    },

    commandSend({ command, ok, ready, count, reason }) {
      const status = ready ? 'channel ready' : 'channel not ready';
      if (!ok) {
        const extra = reason ? `, ${reason}` : '';
        console.warn(`[ctrl/send] failed to send "${command}" (${status}${extra})`);
        return;
      }
      const t = now();
      if (command !== lastSend.command || t - lastSend.time > 800) {
        console.info(`[ctrl/send] sent "${command}" (#${count}, ${status})`);
        lastSend = { command, time: t };
      } else if (t - lastSend.time > 250) {
        console.debug(`[ctrl/send] sent "${command}" (#${count})`);
        lastSend.time = t;
      }
    },

    state({ metrics, state }) {
      if (!metrics) return;
      const t = now();
      const shouldLog = metrics.stateCount <= 3 || t - lastStateLog > 500;
      if (!shouldLog) return;
      lastStateLog = t;
      const latencyText =
        metrics.latencyMs == null ? 'n/a' : `${metrics.latencyMs.toFixed(1)}ms`;
      const posX = formatNumber(state?.x);
      const posY = formatNumber(state?.y);
      const theta = formatNumber(state?.theta, 3);
      console.debug(
        `[ctrl/state] recv #${metrics.stateCount} latency=${latencyText} pos=(${posX}, ${posY}) theta=${theta}`
      );
    },

    estop(source) {
      console.warn(`[ctrl/estop] triggered by ${source || 'unknown source'}`);
    },
  };
}

document.addEventListener('DOMContentLoaded', () => {
  const config = resolveConfig();
  console.log(config)
  const hud = createHud();
  const controlLog = createControlLogger();
  const carEl = document.getElementById('car');
  if (!carEl) {
    console.error('[init] car entity (#car) not found');
    return;
  }

  const metrics = {
    ctrlCount: 0,
    stateCount: 0,
    latencyMs: null,
    lastCtrlAt: null,
  };

  hud.setConnection('disconnected', ['waiting']);
  hud.setMetrics(metrics);

  if (config.localMode) {
    hud.setConnection('degraded', ['local mode enabled']);
    return;
  }

  if (!config.signalingUrls.length) {
    hud.setConnection('disconnected', ['No signaling URL set']);
    return;
  }

  config.channelId = config.channelId || 'sora';
  config.ctrlLabel = config.ctrlLabel || '#ctrl';
  config.stateLabel = config.stateLabel || '#state';

  configureCarForNet(carEl);

  const client = createSoraClient({
    signalingUrls: config.signalingUrls,
    channelId: config.channelId,
    ctrlLabel: config.ctrlLabel,
    stateLabel: config.stateLabel,
    metadata: config.metadata,
    debug: config.debug,
  });

  const keyRepeater = new KeyboardCtrlRepeater({
    hz: CTRL_SEND_HZ,
    onInputChange: (event) => controlLog.input(event),
    onDirection: (direction) => {
      const ready = client.isCtrlReady();
      const command = direction ?? 'IDLE';
      const ok = client.sendCtrl({ command });
      if (ok) {
        metrics.ctrlCount += 1;
        metrics.lastCtrlAt = performance.now();
        hud.setMetrics(metrics);
      }
      controlLog.commandSend({
        command,
        ok,
        ready,
        count: metrics.ctrlCount,
        reason: ready ? (ok ? null : 'sendCtrl returned false') : 'data channel not ready',
      });
    },
  });
  keyRepeater.start();

  client.onOpen(() => {
    metrics.ctrlCount = 0;
    metrics.stateCount = 0;
    metrics.latencyMs = null;
    metrics.lastCtrlAt = null;
    hud.setConnection('connected', [
      `channel: ${config.channelId}`,
      `ctrl: ${config.ctrlLabel}`,
      `state: ${config.stateLabel}`,
    ]);
    hud.setMetrics(metrics);
  });

  client.onClose(() => {
    hud.setConnection('disconnected', ['connection closed']);
  });

  client.onError((err) => {
    const message = err?.message || String(err);
    hud.setConnection('degraded', [`error: ${message}`]);
  });

  client.onState((state) => {
    metrics.stateCount += 1;
    if (metrics.lastCtrlAt != null) {
      metrics.latencyMs = performance.now() - metrics.lastCtrlAt;
    }
    hud.setMetrics(metrics);
    hud.setPose(state);
    applyServerState(carEl, state);
    controlLog.state({ metrics, state });
  });

  const startClient = () => {
    hud.setConnection('degraded', ['connecting']);
    client.connect();
  };

  const sceneEl = document.querySelector('a-scene');
  if (sceneEl) {
    if (sceneEl.hasLoaded) startClient();
    else sceneEl.addEventListener('loaded', startClient, { once: true });
  } else {
    startClient();
  }

  window.addEventListener('app:estop', () => {
    controlLog.estop('button');
    const ready = client.isCtrlReady();
    const ok = client.sendCtrl({ type: 'estop', source: 'ui' });
    if (ok) {
      metrics.ctrlCount += 1;
      metrics.lastCtrlAt = performance.now();
      hud.setMetrics(metrics);
    }
    controlLog.commandSend({
      command: 'ESTOP',
      ok,
      ready,
      count: metrics.ctrlCount,
      reason: ready ? (ok ? 'emergency stop request' : 'sendCtrl returned false') : 'data channel not ready',
    });
  });

  window.addEventListener('beforeunload', () => {
    keyRepeater.stop();
    client.disconnect();
  });
});
