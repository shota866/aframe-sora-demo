const DEFAULT_CONFIG = {
  signalingUrls: ['wss://sora2.uclab.jp/signaling'],
  channelId: 'aframe-demo',
  ctrlLabel: '#ctrl',
  stateLabel: '#state',
  metadata: null,
  debug: false,
  mode: 'net',
};

const META_ENV = import.meta?.env ?? {};

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
    console.warn('[config] failed to parse JSON value', value, err);
    return value;
  }
}

export function resolveConfig() {
  const envConfig = DEFAULT_CONFIG;
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

  const merged = Object.assign({}, DEFAULT_CONFIG, envConfig, bodyConfig, globalConfig, queryConfig);
  merged.signalingUrls = parseArray(merged.signalingUrls || merged.signalingUrl);
  merged.channelId = merged.channelId || merged.room || merged.channel;
  merged.metadata = parseMaybeJson(merged.metadata);
  merged.localMode = String(merged.mode || '').toLowerCase() === 'local';
  return merged;
}

export { DEFAULT_CONFIG, META_ENV };

