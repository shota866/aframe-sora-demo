import Sora from 'sora-js-sdk';

const encoder = new TextEncoder();
const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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

function formatLatency(latencyMs) {
  if (latencyMs == null || Number.isNaN(latencyMs)) return 'n/a';
  return `${latencyMs.toFixed(1)}ms`;
}

export function createSoraClient(options) {
  console.log('createSoraClient options', options);
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
    this.sdk = options.sdk || (typeof window !== 'undefined' && window.Sora) || Sora;

    this.readyState = 'open';

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

    this._ctrlReady = false;
    this._stateReady = false;
    this._ctrlChannel = null;
    this._stateChannel = null;

    this._sendCount = 0;
    this._recvCount = 0;
    this._lastStatsLog = 0;
    this._statsTimer = null;
    this._lastCtrlSendAt = null;
    this._latencyMs = null;
    this._dummyStreamInfo = null;
    this._ctrlSeq = 0;

    this._listeners = {
      open: new Set(),
      close: new Set(),
      error: new Set(),
      state: new Set(),
    };

    this._onDisconnect = this._handleDisconnect.bind(this);
    this._onDataChannel = this._handleDataChannel.bind(this);
    this._onMessage = this._handleMessage.bind(this);
    this._onNotify = this._handleNotify.bind(this);
    this._onTimeout = this._handleTimeout.bind(this);
    console.log("constructor end")
  }

  connect() {
    if (this._loopPromise) {
      if (this.debug) console.debug('[sora] connect() ignored (already running)');
      return;
    }
    this._shouldRun = true;
    this._loopPromise = this._runLoop();
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
    this._clearStatsTimer();
  }

  isCtrlReady() {
    const ready = this._ctrlChannel?.readyState === 'open';
    this._ctrlReady = !!ready;
    return this._ctrlReady;
  }

  isStateReady() {
    const ready = this._stateChannel?.readyState === 'open';
    this._stateReady = !!ready;
    return this._stateReady;
  }

  sendCtrl(message) {
    if (!message || typeof message !== 'object') {
      message = { command: message ?? null };
    }
    const ready = this.isCtrlReady();
    if (!this._session || !ready) {
      if (this.debug) console.warn('[sora] drop ctrl message (channel not ready)');
      return false;
    }
    try {
      const payload = this._encodeCtrlPayload(message);
      this._session.sendMessage(this.ctrlLabel, payload);
      this._sendCount += 1;
      this._lastCtrlSendAt = performance.now();
      this._maybeLogStats();
      return true;
    } catch (err) {
      this._emit('error', err);
      return false;
    }
  }

  onOpen(handler) {
    return this._addListener('open', handler);
  }

  onClose(handler) {
    return this._addListener('close', handler);
  }

  onError(handler) {
    return this._addListener('error', handler);
  }

  onState(handler) {
    return this._addListener('state', handler);
  }

  _addListener(event, handler) {
    if (typeof handler !== 'function') return () => {};
    const bucket = this._listeners[event];
    bucket.add(handler);
    return () => bucket.delete(handler);
  }

  _emit(event, payload) {
    const bucket = this._listeners[event];
    if (!bucket) return;
    for (const handler of bucket) {
      try {
        handler(payload);
      } catch (err) {
        console.error('[sora] listener error', event, err);
      }
    }
  }

  async _runLoop() {
    let attempt = 0;
    while (this._shouldRun && attempt < 3) {
      attempt += 1;
      try {
        await this._connectOnce(attempt);
        attempt = 0;
      } catch (err) {
        if (!this._shouldRun) break;
        this._emit('error', err);
        const index = Math.min(attempt - 1, BACKOFF_MS.length - 1);
        const waitMs = BACKOFF_MS[index];
        console.warn(`[sora] reconnecting in ${waitMs}ms`, err);
        await sleep(waitMs);
      }
    }
    this._loopPromise = null;
  }

  //soraサーバへ実際にコネクションを張り、データチャネルやイベントをセットして通信を開始し、切断まで待つ
  async _connectOnce(attempt) {
    console.info(`[sora] connecting (attempt ${attempt})`);
    this._ctrlReady = false;
    this._stateReady = false;
    this._clearStatsTimer();
    this._sendCount = 0;
    this._recvCount = 0;
    this._latencyMs = null;
    this._lastCtrlSendAt = null;
    this._ctrlSeq = 0;

    const connection = this.sdk.connection(this.signalingUrls, this.debug);
    this._connection = connection;

    const stream = this._ensureDummyVideoStream();

    const dataChannels = [
      { label: this.ctrlLabel, direction: 'sendonly', ordered: true },
      { label: this.stateLabel, direction: 'recvonly', ordered: true },
    ];

    const options = {
      audio: false,
      video: true,
      multistream: true,
      spotlight: false,
      dataChannelSignaling: true,
      dataChannels,
    };

    const session = connection.sendrecv(this.channelId, this.metadata, options);
    this._session = session;

    session.on('disconnect', this._onDisconnect);
    session.on('timeout', this._onTimeout);
    console.info('[sora] registering datachannel listener');
    session.on('datachannel', this._onDataChannel);//sora SDKのsessionからdatachannnelというイベントが届いたときthis._onDataChannelを読んでください。というイベントリスナー登録
    session.on('message', this._onMessage);
    session.on('notify', this._onNotify);

    try {
      if (stream) {
        await session.connect(stream);
      } else {
        await session.connect();
      }
    } catch (err) {
      this._unwireSession(session);
      this._session = null;
      throw err;
    }

    console.info('[sora] Sora connected');
    this._startStatsTimer();
    this._emit('open', { ctrl: this.ctrlLabel, state: this.stateLabel });

    await new Promise((resolve) => {
      this._disconnectResolver = resolve;
    });
    this._disconnectResolver = null;

    this._clearStatsTimer();
    this._emit('close');
    this._unwireSession(session);
    this._session = null;

    if (!this._shouldRun) return;
    throw new Error('disconnected');
  }

  _ensureDummyVideoStream() {
    if (typeof document === 'undefined' || typeof window === 'undefined') return null;
    const info = this._dummyStreamInfo;
    if (info) {
      const tracks = info.stream?.getVideoTracks?.() || [];
      if (tracks.length && tracks.every((track) => track.readyState === 'live')) {
        return info.stream;
      }
      if (info.timer) window.clearInterval(info.timer);
      tracks.forEach((track) => track.stop());
    }

    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.fillStyle = '#ff0000';
    ctx.fillRect(0, 0, 1, 1);
    const stream = canvas.captureStream(1);
    const timer = window.setInterval(() => {
      ctx.fillRect(0, 0, 1, 1);
    }, 1000);
    this._dummyStreamInfo = { canvas, ctx, stream, timer };
    return stream;
  }

  _unwireSession(session) {
    try {
      session.on('disconnect', null);
      session.on('timeout', null);
      session.on('datachannel', null);
      session.on('message', null);
      session.on('notify', null);
    } catch (err) {
      if (this.debug) console.warn('[sora] unwire error', err);
    }
  }

  _handleDisconnect(event) {
    if (this.debug) console.debug('[sora] disconnect', event);
    if (this._disconnectResolver) {
      this._disconnectResolver();
      this._disconnectResolver = null;
    }
  }

  _handleTimeout(event) {
    console.warn('[sora] timeout', event);
  }
  // soraサーバからデータチャネルが確立されたときに呼ばれる
  _handleDataChannel(event) {
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
    this._attachDataChannelHandlers(label, channel);
  }

  _resolveRtcDataChannel(label, descriptor, rawEvent) {
    const candidates = [
      rawEvent?.channel,
      descriptor?.channel,
      descriptor,
      this._session?.soraDataChannels?.[label],
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

  _attachDataChannelHandlers(label, channel) {
    const isCtrl = label === this.ctrlLabel;
    const isState = label === this.stateLabel;
    if (!isCtrl && !isState) {
      if (this.debug) console.debug('[sora] ignoring unmanaged data channel', label);
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
      this._emit('error', err);
    };

    this._bindChannelEvent(channel, 'open', handleOpen);
    this._bindChannelEvent(channel, 'close', handleClose);
    this._bindChannelEvent(channel, 'error', handleError);

    if (channel.readyState === 'open') {
      handleOpen();
    } else if (this.debug) {
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

  _markChannelReady(label, channel, open) {
    const isCtrl = label === this.ctrlLabel;
    const isState = label === this.stateLabel;
    if (!isCtrl && !isState) return;

    if (open) {
      if (isCtrl) {
        this._ctrlChannel = channel;
        this._ctrlReady = true;
      } else if (isState) {
        this._stateChannel = channel;
        this._stateReady = true;
      }
      console.info(`[sora] data channel open: ${label}`);
    } else {
      if (isCtrl && this._ctrlChannel === channel) {
        this._ctrlReady = false;
        this._ctrlChannel = null;
      }
      if (isState && this._stateChannel === channel) {
        this._stateReady = false;
        this._stateChannel = null;
      }
      console.warn(`[sora] data channel closed: ${label}`);
    }
  }

  //#stateデータチャネルの受信入口で、チャネルの準備完了(ready)を検出、マークするための処理
  _handleMessage(event) {
    const { label, data } = event || {};
    if (label !== this.stateLabel) return;//#state以外は捨てるフィルタ
    if (!this._stateReady) {
      const live = this._stateChannel || this._session?.soraDataChannels?.[this.stateLabel];
      if (live?.readyState === 'open') {
        this._markChannelReady(this.stateLabel, live, true);
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

    const isStatePayload =
      (typeof payload.type === 'string' && payload.type.toLowerCase() === 'state') ||
      (typeof payload.t === 'string' && payload.t.toLowerCase() === 'state');
    if (!isStatePayload) return;
    this._recvCount += 1;
    if (this._lastCtrlSendAt != null) {
      this._latencyMs = performance.now() - this._lastCtrlSendAt;
    }
    this._maybeLogStats();
    this._emit('state', payload);
  }

  _handleNotify(event) {
    if (this.debug) console.debug('[sora] notify', event);
  }

  _maybeLogStats() {
    const now = performance.now();
    if (now - this._lastStatsLog < 1000) return;
    if (!this.debug && this._sendCount === 0 && this._recvCount === 0) return;
    this._lastStatsLog = now;
    const latency = formatLatency(this._latencyMs);
    console.info(`[sora] stats #ctrl:${this._sendCount} #state:${this._recvCount} latency:${latency}`);
  }

  _startStatsTimer() {
    this._clearStatsTimer();
    this._statsTimer = setInterval(() => {
      const latency = formatLatency(this._latencyMs);
      console.info(`[sora] stats #ctrl:${this._sendCount} #state:${this._recvCount} latency:${latency}`);
    }, 5000);
  }

  _clearStatsTimer() {
    if (this._statsTimer) {
      clearInterval(this._statsTimer);
      this._statsTimer = null;
    }
  }

  _nextCtrlSeq() {
    this._ctrlSeq = (this._ctrlSeq + 1) % 0x80000000;
    return this._ctrlSeq;
  }

  _encodeCtrlPayload(rawMessage) {
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
    const ts = Date.now();
    if (!payload.type && typeof payload.t === 'string') {
      payload.type = payload.t;
    }
    payload.type = typeof payload.type === 'string' ? payload.type : 'cmd';
    payload.seq = seq;
    payload.ts = ts;
    delete payload.v;
    delete payload.t;

    return encoder.encode(JSON.stringify(payload));
  }
}
