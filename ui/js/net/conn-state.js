export class EventHub {
  constructor(events = []) {
    this._listeners = new Map();
    events.forEach((event) => this._listeners.set(event, new Set()));
  }

  on(event, handler) {
    if (typeof handler !== 'function') return () => {};
    const bucket = this._getBucket(event);
    bucket.add(handler);
    return () => bucket.delete(handler);
  }

  off(event, handler) {
    const bucket = this._listeners.get(event);
    if (!bucket) return;
    bucket.delete(handler);
  }

  emit(event, payload) {
    const bucket = this._listeners.get(event);
    if (!bucket) return;
    for (const handler of bucket) {
      try {
        handler(payload);
      } catch (err) {
        console.error('[net] listener error', event, err);
      }
    }
  }

  _getBucket(event) {
    if (!this._listeners.has(event)) {
      this._listeners.set(event, new Set());
    }
    return this._listeners.get(event);
  }
}

