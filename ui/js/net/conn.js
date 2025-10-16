const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class ConnectionManager {
  constructor(client) {
    this.client = client;
  }

  async runLoop() {
    let attempt = 0;
    const { client } = this;
    while (client._shouldRun && attempt < 3) {
      attempt += 1;
      try {
        await this.connectOnce(attempt);
        attempt = 0;
      } catch (err) {
        if (!client._shouldRun) break;
        client._emit('error', err);
        client._emit('status', { state: 'reconnecting', channels: {} });
        const index = Math.min(attempt - 1, BACKOFF_MS.length - 1);
        const waitMs = BACKOFF_MS[index];
        console.warn(`[sora] reconnecting in ${waitMs}ms`, err);
        await sleep(waitMs);
      }
    }
    client._loopPromise = null;
  }

  async connectOnce(attempt) {
    const client = this.client;
    console.info(`[sora] connecting (attempt ${attempt})`);
    client._channels.resetForConnect();

    const connection = client.sdk.connection(client.signalingUrls, client.debug);
    client._connection = connection;

    const stream = this._ensureDummyVideoStream();

    const dataChannels = [
      { label: client.ctrlLabel, direction: 'sendonly', ordered: true },
      { label: client.stateLabel, direction: 'recvonly', ordered: true },
    ];

    const options = {
      audio: false,
      video: true,
      multistream: true,
      spotlight: false,
      dataChannelSignaling: true,
      dataChannels,
    };

    const session = connection.sendrecv(client.channelId, client.metadata, options);
    client._session = session;

    session.on('disconnect', client._onDisconnect);
    session.on('timeout', client._onTimeout);
    session.on('datachannel', client._onDataChannel);
    session.on('message', client._onMessage);
    session.on('notify', client._onNotify);

    try {
      if (stream) {
        await session.connect(stream);
      } else {
        await session.connect();
      }
    } catch (err) {
      this._unwireSession(session);
      client._session = null;
      throw err;
    }

    console.info('[sora] Sora connected');
    client._channels.startStatsTimer();
    client._emit('open', { ctrl: client.ctrlLabel, state: client.stateLabel });
    client._emit('status', { state: 'connected', channels: {} });

    await new Promise((resolve) => {
      client._disconnectResolver = resolve;
    });
    client._disconnectResolver = null;

    client._channels.clearStatsTimer();
    client._emit('close');
    client._emit('status', { state: 'stopped', channels: {} });
    this._unwireSession(session);
    client._session = null;

    if (!client._shouldRun) return;
    throw new Error('disconnected');
  }

  handleDisconnect(event) {
    if (this.client.debug) console.debug('[sora] disconnect', event);
    if (this.client._disconnectResolver) {
      this.client._disconnectResolver();
      this.client._disconnectResolver = null;
    }
    this.client._emit('status', { state: 'error', channels: {} });
  }

  handleTimeout(event) {
    console.warn('[sora] timeout', event);
    this.client._emit('status', { state: 'timeout', channels: {} });
  }

  _ensureDummyVideoStream() {
    if (typeof document === 'undefined' || typeof window === 'undefined') return null;
    const info = this.client._dummyStreamInfo;
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
    this.client._dummyStreamInfo = { canvas, ctx, stream, timer };
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
      if (this.client.debug) console.warn('[sora] unwire error', err);
    }
  }
}
