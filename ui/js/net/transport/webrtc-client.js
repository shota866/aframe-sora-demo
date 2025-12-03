import { EventBus } from './control-client.js';

export class WebRTCClientTransport {
  constructor({ client, label, debug = false } = {}) {
    if (!client) throw new Error('WebRTCClientTransport requires a Sora client');
    if (!label) throw new Error('WebRTCClientTransport requires a ctrl label');
    this.client = client;
    this.label = label;
    this.debug = !!debug;
    this._open = false;
    this._events = new EventBus();

    this._onOpen = this._handleOpen.bind(this);
    this._onClose = this._handleClose.bind(this);

    this.client.on('channel-open', this._onOpen);
    this.client.on('channel-close', this._onClose);
  }

  isReady() {
    return this._open;
  }

  start() {
    // No-op: lifecycle is managed by the Sora client
  }

  stop() {
    this.client.off('channel-open', this._onOpen);
    this.client.off('channel-close', this._onClose);
  }

  sendCtrl(payload) {
    if (!this.isReady()) return false;
    return this.client.sendJson(this.label, payload);
  }

  on(event, handler) {
    this._events.on(event, handler);
  }

  off(event, handler) {
    this._events.off(event, handler);
  }

  _handleOpen(evt) {
    if (evt.label === this.label) {
      this._open = true;
      if (this.debug) console.info('[ctrl] channel open (webrtc)', evt);
      this._events.emit('channel-open', evt);
    }
  }

  _handleClose(evt) {
    if (evt.label === this.label) {
      this._open = false;
      if (this.debug) console.warn('[ctrl] channel closed (webrtc)', evt);
      this._events.emit('channel-close', evt);
    }
  }
}
