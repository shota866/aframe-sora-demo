function formatDetail(details) {
  if (Array.isArray(details)) return details.join(' | ');
  return details || '';
}

export function createHud() {
  const labelEl = document.getElementById('netStatusLabel');
  const detailEl = document.getElementById('netStatusDetail');
  const metricsEl = document.getElementById('netMetrics');
  const poseEl = document.getElementById('poseInfo');

  function setConnection(level, details) {
    if (!labelEl) return;
    const status =
      level === 'connected' ? 'connected' : level === 'degraded' ? 'degraded' : 'disconnected';
    if (window?.NET_DEBUG) {
      console.info('[hud] setConnection', { level, details, status });
    }
    labelEl.dataset.level = status;
    labelEl.textContent = status.toUpperCase();
    if (detailEl) detailEl.textContent = formatDetail(details);
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
    const pose = state.pose || {};
    const x = Number(pose.x);
    const y = Number(pose.y);
    const heading = Number(pose.heading);
    const safe = (value, digits = 1) =>
      Number.isFinite(value) ? value.toFixed(digits) : 'n/a';
    poseEl.textContent = `pos: ${safe(x)} ${safe(y)} | heading: ${safe(heading, 3)}`;
  }

  return { setConnection, setMetrics, setPose };
}
