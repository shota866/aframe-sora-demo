import { resolveConfig } from './config.js';
import { createHud } from './ui/hud.js';
import { createControlLogger } from './ui/control-logger.js';
import { createNetBridge } from './net-bridge.js';

document.addEventListener('DOMContentLoaded', () => {
  const config = resolveConfig();
  const hud = createHud();
  const controlLog = createControlLogger();
  const carEl = document.getElementById('car');

  if (!carEl) {
    console.error('[bootstrap] car entity (#car) not found');
    return;
  }

  hud.setConnection('disconnected', ['waiting']);
  hud.setMetrics({ ctrlCount: 0, stateCount: 0, latencyMs: null });

  if (config.localMode) {
    hud.setConnection('degraded', ['local mode enabled']);
    return;
  }

  if (!Array.isArray(config.signalingUrls) || config.signalingUrls.length === 0) {
    hud.setConnection('disconnected', ['No signaling URL set']);
    return;
  }

  config.channelId = config.channelId || 'sora';
  config.ctrlLabel = config.ctrlLabel || 'ctrl';
  config.stateLabel = config.stateLabel || 'state';

  const bridge = createNetBridge({ config, hud, controlLog, carEl });
  hud.setMetrics(bridge.metrics);

  const sceneEl = document.querySelector('a-scene');
  const startBridge = () => bridge.start();
  if (sceneEl) {
    if (sceneEl.hasLoaded) startBridge();
    else sceneEl.addEventListener('loaded', startBridge, { once: true });
  } else {
    startBridge();
  }

  window.addEventListener('app:estop', () => bridge.sendEstop());
  window.addEventListener('beforeunload', () => {
    bridge.stop();
  });
});

