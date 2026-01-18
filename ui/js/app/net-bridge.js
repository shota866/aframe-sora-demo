import { CTRL_SEND_HZ } from './constants.js';
import { KeyboardCtrlRepeater } from './input/keyboard-repeater.js';
import { applyServerState } from '../scene/car-state.js';
import { configureCarForNet } from '../scene/car-setup.js';
import { createSoraClient } from '../net/sora-client.js';
import { VideoThumbnail } from '../net/video-thumb.js';
import { MQTTClientTransport } from '../net/transport/mqtt-client.js';

export function createNetBridge({ config, hud, controlLog, carEl }) {
  if (!hud) throw new Error('HUD instance required');
  if (!controlLog) throw new Error('Control logger required');
  if (!carEl) throw new Error('Car element (#car) not found');

  const metrics = {
    ctrlCount: 0,
    stateCount: 0,
    latencyMs: null,
    lastCtrlAt: null,
  };

  const ctrlTransportChoice = String(config.ctrlTransport || 'webrtc').toLowerCase();

  const client = createSoraClient({
    signalingUrls: config.signalingUrls,
    channelId: config.channelId,
    ctrlLabel: config.ctrlLabel,
    stateLabel: config.stateLabel,
    metadata: config.metadata,
    debug: config.debug,
  });

  const mqttTransport =
    ctrlTransportChoice === 'mqtt'
      ? new MQTTClientTransport({
          url: config.mqttUrl || config.mqttWsUrl || config.mqtt,
          topic: config.mqttCtrlTopic || 'aframe/ctrl',
          qos: Number(config.mqttCtrlQos || 1),
          username: config.mqttUsername,
          password: config.mqttPassword,
          debug: config.debug,
        })
      : null;

  if (mqttTransport) {
    console.info('[net] MQTT ctrl selected', {
      url: config.mqttUrl || config.mqttWsUrl || config.mqtt,
      topic: config.mqttCtrlTopic || 'aframe/ctrl',
    });
  }

  client.on('channel-open', ({ label }) => {
    console.info(`[net] data channel open: ${label}`);
  });

  client.on('channel-close', ({ label }) => {
    console.warn(`[net] data channel closed: ${label}`);
  });

  client.on('status', (info) => {
    const state = info?.state || 'unknown';
    const channels = info?.channels || {};
    console.info('[net] client status update', { state, channels });
  });

  const keyRepeater = new KeyboardCtrlRepeater({
    hz: CTRL_SEND_HZ,
    onInputChange: (event) => controlLog.input(event),
    onDirection: (directions) => handleDirection(directions),
  });

  configureCarForNet(carEl);

  const videoThumb = new VideoThumbnail({
    elementId: config.cameraElementId || 'cameraThumb',
    trackLabel: config.cameraTrackLabel || 'camera-thumb',
  });

  client.onTrack((event) => {
    console.info('[net] track event', event?.track?.label, event);
    videoThumb.handleTrack(event);
  });

  client.onOpen(() => {
    metrics.ctrlCount = 0;
    metrics.stateCount = 0;
    metrics.latencyMs = null;
    metrics.lastCtrlAt = null;
    if (!mqttTransport) {
      hud.setConnection('connected', [
        `channel: ${config.channelId}`,
        `ctrl: ${config.ctrlLabel}`,
        `state: ${config.stateLabel}`,
      ]);
    }
    hud.setMetrics(metrics);
  });

  client.onClose(() => {
    videoThumb.clear();
    if (!mqttTransport) hud.setConnection('disconnected', ['connection closed']);
  });

  client.onError((err) => {
    if (mqttTransport) return; // prefer MQTT status when using MQTT ctrl
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
    // applyServerState(carEl, state);
    controlLog.state({ metrics, state });
  });

  if (mqttTransport) {
    mqttTransport.on('channel-open', ({ label }) => {
      console.info('[net] MQTT ctrl connected', label);
      hud.setConnection('connected', [`mqtt ctrl: ${label}`]);
    });
    mqttTransport.on('channel-close', ({ label }) => {
      console.warn('[net] MQTT ctrl disconnected', label);
      hud.setConnection('degraded', ['ctrl mqtt disconnected']);
    });
    mqttTransport.on('error', (err) => {
      console.error('[net] MQTT ctrl error', err);
      hud.setConnection('degraded', ['ctrl mqtt error']);
    });
  }

  function ctrlSend(raw) {
    const payload = typeof raw === 'string' ? { command: raw } : raw;
    const isMqtt = ctrlTransportChoice === 'mqtt';
    const ready = isMqtt
      ? mqttTransport?.isReady?.() || false
      : client.isCtrlReady();
    const ok = isMqtt ? mqttTransport?.sendCtrl(payload) || false : client.sendCtrl(payload);
    if (ok) {
      metrics.ctrlCount += 1;
      metrics.lastCtrlAt = performance.now();
      hud.setMetrics(metrics);
    }
    controlLog.commandSend({
      command: payload?.command || payload?.type || 'UNKNOWN',
      ok,
      ready,
      count: metrics.ctrlCount,
      reason: ready
        ? ok
          ? isMqtt
            ? 'mqtt publish ok'
            : 'sendCtrl ok'
          : isMqtt
            ? 'mqtt publish failed'
            : 'sendCtrl returned false'
        : 'ctrl transport not ready',
    });
    if (isMqtt) {
      console.info('[ctrl/mqtt] publish attempt', {
        ok,
        ready,
        topic: mqttTransport?.topic,
        url: mqttTransport?.url,
        payload,
      });
    } else if (config.debug) {
      console.debug('[ctrl/webrtc] send attempt', { ok, ready, payload });
    }
    return ok;
  }

  function handleDirection(directions) {
    const cmds = Array.isArray(directions) ? directions : directions ? [directions] : [];
    const commands = cmds.length ? cmds : ['IDLE'];
    for (const command of commands) {
      ctrlSend({ command });
    }
  }

  function sendEstop() {
    controlLog.estop('button');
    ctrlSend({ type: 'estop', source: 'ui', command: 'ESTOP', estop: true });
  }

  return {
    start() {
      hud.setConnection('degraded', ['connecting']);
      keyRepeater.start();
      if (mqttTransport) {
        mqttTransport.start();
      }
      client.connect();
    },
    stop() {
      keyRepeater.stop();
      videoThumb.clear();
      if (mqttTransport) mqttTransport.stop();
      return client.disconnect();
    },
    handleDirection,
    sendEstop,
    metrics,
    client,
  };
}
