function formatNumber(value, digits = 2) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(digits) : 'n/a';
}

export function createControlLogger() {
  let lastDirection = [];
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
        const dirList = Array.isArray(direction) ? direction : direction ? [direction] : [];
        const changed =
          dirList.length !== lastDirection.length ||
          dirList.some((value, idx) => value !== lastDirection[idx]);
        if (changed) {
          console.info(`[ctrl/input] direction -> ${dirList.join('+') || 'none'}`);
          lastDirection = dirList;
        }
      } else if (type === 'idle') {
        if (lastDirection.length) {
          console.info('[ctrl/input] direction cleared (no active command)');
          lastDirection = [];
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
      const pose = state?.pose || {};
      const velocity = state?.velocity || {};
      const posX = formatNumber(pose.x);
      const posY = formatNumber(pose.y);
      const heading = formatNumber(pose.heading, 3);
      const linear = formatNumber(velocity.linear);
      const angular = formatNumber(velocity.angular, 3);
      const lastCtrlSeq = state?.last_ctrl?.seq ?? 'n/a';
      console.debug(
        `[ctrl/state] recv #${metrics.stateCount} latency=${latencyText} pos=(${posX}, ${posY}) heading=${heading} vel=(lin:${linear}, ang:${angular}) last_ctrl_seq=${lastCtrlSeq}`,
      );
    },

    estop(source) {
      console.warn(`[ctrl/estop] triggered by ${source || 'unknown source'}`);
    },
  };
}
