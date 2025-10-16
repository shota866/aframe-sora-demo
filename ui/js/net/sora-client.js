import Sora from 'sora-js-sdk';

import { ConnectionManager } from './conn.js';
import { DataChannelManager } from './dc-manager.js';
import { EventHub } from './conn-state.js';

function normaliseUrlList(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.filter(Boolean);
  if (typeof raw === 'string') {
    return raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

export function createSoraClient(options) {
  return new SoraDataChannelClient(options);
}

class SoraDataChannelClient {
  constructor(options = {}) {
    const {
      signalingUrls,
      channelId,
      ctrlLabel,
      stateLabel,
      metadata = null,
      debug = false,
      sdk = null,
    } = options;

    if (!channelId) throw new Error('channelId is required');
    if (!ctrlLabel) throw new Error('ctrlLabel is required');
    if (!stateLabel) throw new Error('stateLabel is required');

    this.signalingUrls = normaliseUrlList(signalingUrls);
    if (this.signalingUrls.length === 0) {
      throw new Error('signalingUrls must not be empty');
    }

    this.channelId = channelId;
    this.ctrlLabel = ctrlLabel;
    this.stateLabel = stateLabel;
    this.metadata = metadata;
    this.debug = !!debug;
    this.sdk = sdk || (typeof window !== 'undefined' && window.Sora) || Sora;

    if (!this.sdk) {
      throw new Error('Sora JS SDK not available. Please install sora-js-sdk.');
    }
    if (typeof window !== 'undefined' && !window.Sora) {
      window.Sora = this.sdk;
    }

    this._session = null;
    this._connection = null;
    this._loopPromise = null;
    this._shouldRun = false;
    this._disconnectResolver = null;
    this._dummyStreamInfo = null;
    this._registeredChannels = new Map();

    this._events = new EventHub([
      'open',
      'close',
      'error',
      'state',
      'channel-open',
      'channel-close',
      'status',
      'heartbeat',
    ]);

    this._channels = new DataChannelManager(this);
    this._connectionManager = new ConnectionManager(this);

    this._onDisconnect = (event) => this._connectionManager.handleDisconnect(event);
    this._onTimeout = (event) => this._connectionManager.handleTimeout(event);
    this._onDataChannel = (event) => this._channels.handleDataChannel(event);
    this._onMessage = (event) => this._channels.handleMessage(event);
    this._onNotify = (event) => this._channels.handleNotify(event);
  }

  connect() {
    if (this._loopPromise) {
      if (this.debug) console.debug('[sora] connect() ignored (already running)');
      return;
    }
    this._shouldRun = true;
    this._loopPromise = this._connectionManager.runLoop();
  }

  start() {
    this.connect();
  }

  async disconnect() {
    this._shouldRun = false;
    if (this._session) {
      try {
        await this._session.disconnect();
      } catch (err) {
        if (this.debug) console.warn('[sora] disconnect error', err);
      }
      this._session = null;
    }
    if (this._loopPromise) {
      try {
        await this._loopPromise;
      } catch (err) {
        if (this.debug) console.warn('[sora] disconnect loop error', err);
      }
      this._loopPromise = null;
    }
    this._channels.clearStatsTimer();
  }

  async stop() {
    await this.disconnect();
  }

  isCtrlReady() {
    return this._channels.isCtrlReady();
  }

  isStateReady() {
    return this._channels.isStateReady();
  }

  sendCtrl(message) {
    if (!message || typeof message !== 'object') {
      message = { command: message ?? null };
    }
    if (!this._session || !this.isCtrlReady()) {
      if (this.debug) console.warn('[sora] drop ctrl message (channel not ready)');
      return false;
    }
    try {
      const payload = this._channels.encodeCtrlPayload(message);
      this._session.sendMessage(this.ctrlLabel, payload);
      this._channels.onCtrlSent();
      return true;
    } catch (err) {
      this._emit('error', err);
      return false;
    }
  }

  sendJson(label, payload) {
    if (!this._session) return false;
    try {
      const text = typeof payload === 'string' ? payload : JSON.stringify(payload);
      this._session.sendMessage(label, text);
      return true;
    } catch (err) {
      this._emit('error', err);
      return false;
    }
  }

  registerChannel(label, options = {}) {
    this._registeredChannels.set(label, { ...options });
  }

  on(event, handler) {
    return this._events.on(event, handler);
  }

  off(event, handler) {
    this._events.off(event, handler);
  }

  onOpen(handler) {
    return this.on('open', handler);
  }

  onClose(handler) {
    return this.on('close', handler);
  }

  onError(handler) {
    return this.on('error', handler);
  }

  onState(handler) {
    return this.on('state', handler);
  }

  _emit(event, payload) {
    this._events.emit(event, payload);
  }
}

