function formatNumber(value, digits = 2) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : 'n/a';
}

export function createControlLogger() {
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
        `[ctrl/state] recv #${metrics.stateCount} latency=${latencyText} pos=(${posX}, ${posY}) theta=${theta}`,
      );
    },

    estop(source) {
      console.warn(`[ctrl/estop] triggered by ${source || 'unknown source'}`);
    },
  };
}

