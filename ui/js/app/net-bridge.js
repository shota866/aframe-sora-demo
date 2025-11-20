import { CTRL_SEND_HZ } from './constants.js';
import { KeyboardCtrlRepeater } from './input/keyboard-repeater.js';
import { applyServerState } from '../scene/car-state.js';
import { configureCarForNet } from '../scene/car-setup.js';
import { createSoraClient } from '../net/sora-client.js';
import { VideoThumbnail } from '../net/video-thumb.js';

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

  const client = createSoraClient({
    signalingUrls: config.signalingUrls,
    channelId: config.channelId,
    ctrlLabel: config.ctrlLabel,
    stateLabel: config.stateLabel,
    metadata: config.metadata,
    debug: config.debug,
  });

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
    videoThumb.handleTrack(event);
  });

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
    videoThumb.clear();
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

  function handleDirection(directions) {
    const ready = client.isCtrlReady();
    const cmds = Array.isArray(directions) ? directions : directions ? [directions] : [];
    const commands = cmds.length ? cmds : ['IDLE'];
    for (const command of commands) {
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
    }
  }

  function sendEstop() {
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
      reason: ready
        ? ok
          ? 'emergency stop request'
          : 'sendCtrl returned false'
        : 'data channel not ready',
    });
  }

  return {
    start() {
      hud.setConnection('degraded', ['connecting']);
      keyRepeater.start();
      client.connect();
    },
    stop() {
      keyRepeater.stop();
      videoThumb.clear();
      return client.disconnect();
    },
    handleDirection,
    sendEstop,
    metrics,
    client,
  };
}
