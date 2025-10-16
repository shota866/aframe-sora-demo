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
    const x = Number(state.x);
    const y = Number(state.y);
    const theta = Number(state.theta);
    const safe = (value, digits = 1) =>
      Number.isFinite(value) ? value.toFixed(digits) : 'n/a';
    poseEl.textContent = `pos: ${safe(x)} ${safe(y)} | theta: ${safe(theta, 3)}`;
  }

  return { setConnection, setMetrics, setPose };
}

