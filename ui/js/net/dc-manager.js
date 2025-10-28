import { formatLatency } from './format.js';

const encoder = new TextEncoder();

export class DataChannelManager {
  constructor(client) {
    this.client = client;
    this.ctrlReady = false;
    this.stateReady = false;
    this.ctrlChannel = null;
    this.stateChannel = null;
    this.sendCount = 0;
    this.recvCount = 0;
    this.lastCtrlSendAt = null;
    this.latencyMs = null;
    this.lastStatsLog = 0;
    this.statsTimer = null;
    this.ctrlSeq = 0;
  }

  resetForConnect() {
    this.ctrlReady = false;
    this.stateReady = false;
    this.ctrlChannel = null;
    this.stateChannel = null;
    this.sendCount = 0;
    this.recvCount = 0;
    this.latencyMs = null;
    this.lastCtrlSendAt = null;
    this.ctrlSeq = 0;
    this.clearStatsTimer();
  }

  isCtrlReady() {
    const ready = this.ctrlChannel?.readyState === 'open';
    this.ctrlReady = !!ready;
    return this.ctrlReady;
  }

  isStateReady() {
    const ready = this.stateChannel?.readyState === 'open';
    this.stateReady = !!ready;
    return this.stateReady;
  }

  handleDataChannel(event) {
    const descriptor = event?.datachannel || event;
    const label = descriptor?.label || event?.label;
    if (!label) {
      console.warn('[sora] datachannel event without label', event);
      return;
    }
    const channel = this._resolveRtcDataChannel(label, descriptor, event);
    if (!channel) {
      console.warn('[sora] could not resolve RTCDataChannel for label', label, descriptor);
      return;
    }
    this._attachHandlers(label, channel);
  }

  handleMessage(event) {
    const { label, data } = event || {};
    if (label !== this.client.stateLabel) return;
    if (!this.isStateReady()) {
      const live =
        this.stateChannel || this.client._session?.soraDataChannels?.[this.client.stateLabel];
      if (live?.readyState === 'open') {
        this._markChannelReady(this.client.stateLabel, live, true);
      }
    }

    let text;
    if (data instanceof ArrayBuffer) {
      text = new TextDecoder().decode(new Uint8Array(data));
    } else if (data instanceof Uint8Array) {
      text = new TextDecoder().decode(data);
    } else if (typeof data === 'string') {
      text = data;
    } else {
      return;
    }

    let payload;
    try {
      payload = JSON.parse(text);
    } catch (err) {
      console.warn('[sora] invalid JSON from state channel', err);
      return;
    }

    const typeLower = typeof payload.type === 'string' ? payload.type.toLowerCase() : null;
    if (typeLower === 'hb') {
      this.client._emit('heartbeat', { label, payload });
      return;
    }
    const legacyLower = typeof payload.t === 'string' ? payload.t.toLowerCase() : null;
    const isStatePayload = typeLower === 'state' || legacyLower === 'state';
    if (!isStatePayload) return;

    this.recvCount += 1;
    if (this.lastCtrlSendAt != null) {
      this.latencyMs = performance.now() - this.lastCtrlSendAt;
    }
    this.maybeLogStats();
    this.client._emit('state', payload);
    this.client._emit(`message:${label}`, payload);
  }

  handleNotify(event) {
    if (this.client.debug) console.debug('[sora] notify', event);
  }

  onCtrlSent() {
    this.sendCount += 1;
    this.lastCtrlSendAt = performance.now();
    this.maybeLogStats();
  }

  encodeCtrlPayload(rawMessage) {
    let payload;
    if (typeof rawMessage === 'string') {
      payload = { command: rawMessage };
    } else if (rawMessage && typeof rawMessage === 'object') {
      payload = { ...rawMessage };
    } else {
      payload = { command: rawMessage ?? null };
    }

    if (payload.command === undefined && payload.v !== undefined) {
      payload.command = payload.v;
    }

    const seq = this._nextCtrlSeq();
    const sentAtMs = Date.now();
    if (!payload.type && typeof payload.t === 'string') {
      payload.type = payload.t;
    }
    payload.type = typeof payload.type === 'string' ? payload.type : 'cmd';
    payload.seq = seq;
    payload.sent_at_ms = sentAtMs;
    delete payload.v;
    delete payload.t;
    delete payload.ts;

    return encoder.encode(JSON.stringify(payload));
  }

  startStatsTimer() {
    this.clearStatsTimer();
    this.statsTimer = setInterval(() => {
      const latency = formatLatency(this.latencyMs);
      console.info(
        `[sora] stats ctrl:${this.sendCount} state:${this.recvCount} latency:${latency}`,
      );
    }, 5000);
  }

  clearStatsTimer() {
    if (this.statsTimer) {
      clearInterval(this.statsTimer);
      this.statsTimer = null;
    }
  }

  maybeLogStats() {
    const now = performance.now();
    if (now - this.lastStatsLog < 1000) return;
    if (!this.client.debug && this.sendCount === 0 && this.recvCount === 0) return;
    this.lastStatsLog = now;
    const latency = formatLatency(this.latencyMs);
    console.info(
      `[sora] stats ctrl:${this.sendCount} state:${this.recvCount} latency:${latency}`,
    );
  }

  _markChannelReady(label, channel, open) {
    const isCtrl = label === this.client.ctrlLabel;
    const isState = label === this.client.stateLabel;
    if (!isCtrl && !isState) return;

    if (open) {
      if (isCtrl) {
        this.ctrlChannel = channel;
        this.ctrlReady = true;
      } else if (isState) {
        this.stateChannel = channel;
        this.stateReady = true;
      }
      this.client._emit('channel-open', { label });
      if (this.client.debug) console.info(`[sora] data channel open: ${label}`);
    } else {
      if (isCtrl && this.ctrlChannel === channel) {
        this.ctrlReady = false;
        this.ctrlChannel = null;
      }
      if (isState && this.stateChannel === channel) {
        this.stateReady = false;
        this.stateChannel = null;
      }
      this.client._emit('channel-close', { label });
      if (this.client.debug) console.warn(`[sora] data channel closed: ${label}`);
    }
  }

  _nextCtrlSeq() {
    this.ctrlSeq = (this.ctrlSeq + 1) % 0x80000000;
    return this.ctrlSeq;
  }

  _resolveRtcDataChannel(label, descriptor, rawEvent) {
    const candidates = [
      rawEvent?.channel,
      descriptor?.channel,
      descriptor,
      this.client._session?.soraDataChannels?.[label],
    ];
    for (const candidate of candidates) {
      if (
        candidate &&
        typeof candidate.readyState === 'string' &&
        typeof candidate.send === 'function'
      ) {
        return candidate;
      }
    }
    return null;
  }

  _attachHandlers(label, channel) {
    const isCtrl = label === this.client.ctrlLabel;
    const isState = label === this.client.stateLabel;
    if (!isCtrl && !isState) {
      if (this.client.debug) console.debug('[sora] ignoring unmanaged data channel', label);
      return;
    }
    if (channel.__aframeAttached) {
      if (channel.readyState === 'open') this._markChannelReady(label, channel, true);
      return;
    }
    Object.defineProperty(channel, '__aframeAttached', {
      value: true,
      configurable: true,
    });
    channel.binaryType = 'arraybuffer';

    const handleOpen = () => this._markChannelReady(label, channel, true);
    const handleClose = () => this._markChannelReady(label, channel, false);
    const handleError = (err) => {
      console.error('[sora] data channel error', label, err);
      this.client._emit('error', err);
    };

    this._bindChannelEvent(channel, 'open', handleOpen);
    this._bindChannelEvent(channel, 'close', handleClose);
    this._bindChannelEvent(channel, 'error', handleError);

    if (channel.readyState === 'open') {
      handleOpen();
    } else if (this.client.debug) {
      console.debug('[sora] data channel awaiting open', label, channel.readyState);
    }
  }

  _bindChannelEvent(channel, eventName, handler) {
    if (typeof channel.addEventListener === 'function') {
      channel.addEventListener(eventName, handler);
      return;
    }
    const prop = `on${eventName}`;
    const previous = channel[prop];
    channel[prop] = (event) => {
      if (typeof previous === 'function') {
        try {
          previous.call(channel, event);
        } catch (err) {
          console.error('[sora] data channel listener error', err);
        }
      }
      handler(event);
    };
  }
}
