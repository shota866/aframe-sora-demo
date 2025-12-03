import mqtt from 'mqtt';
import { EventBus } from './control-client.js';

export class MQTTClientTransport {
  constructor({ url, topic, qos = 1, debug = false, username, password } = {}) {
    if (!url) throw new Error('MQTTClientTransport requires broker url (ws:// or wss://)');
    if (!topic) throw new Error('MQTTClientTransport requires ctrl topic');
    this.url = url;
    this.topic = topic;
    this.qos = qos;
    this.debug = !!debug;
    this.username = username;
    this.password = password;

    this._client = null;
    this._connected = false;
    this._events = new EventBus();

    this._onConnect = this._handleConnect.bind(this);
    this._onClose = this._handleClose.bind(this);
    this._onError = this._handleError.bind(this);
  }

  isReady() {
    return this._connected;
  }

  start() {
    if (this._client) return;
    const options = {
      reconnectPeriod: 2000,
      username: this.username,
      password: this.password,
    };
    console.info('[ctrl/mqtt] connecting', { url: this.url, topic: this.topic });
    this._client = mqtt.connect(this.url, options);
    this._client.on('connect', this._onConnect);
    this._client.on('close', this._onClose);
    this._client.on('error', this._onError);
  }

  stop() {
    if (!this._client) return;
    this._client.off('connect', this._onConnect);
    this._client.off('close', this._onClose);
    this._client.off('error', this._onError);
    this._client.end(true);
    this._client = null;
    this._connected = false;
  }

  sendCtrl(payload) {
    if (!this._client || !this.isReady()) return false;
    try {
      const text = typeof payload === 'string' ? payload : JSON.stringify(payload);
      this._client.publish(this.topic, text, { qos: this.qos });
      if (this.debug) console.debug('[ctrl/mqtt] publish', { topic: this.topic, payload: text });
      return true;
    } catch (err) {
      console.error('[ctrl/mqtt] publish failed', err);
      return false;
    }
  }

  on(event, handler) {
    this._events.on(event, handler);
  }

  off(event, handler) {
    this._events.off(event, handler);
  }

  _handleConnect() {
    this._connected = true;
    if (this.debug) console.info('[ctrl/mqtt] connected', this.url);
    this._events.emit('channel-open', { label: this.topic });
  }

  _handleClose() {
    const wasConnected = this._connected;
    this._connected = false;
    if (this.debug) console.warn('[ctrl/mqtt] disconnected');
    if (wasConnected) this._events.emit('channel-close', { label: this.topic });
  }

  _handleError(err) {
    console.error('[ctrl/mqtt] error', err);
  }
}
