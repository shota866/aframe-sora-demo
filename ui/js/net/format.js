export function formatLatency(latencyMs) {
  if (latencyMs == null || Number.isNaN(latencyMs)) return 'n/a';
  return `${latencyMs.toFixed(1)}ms`;
}

