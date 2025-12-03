// Lightweight event helper used by transports
class EventBus {
  constructor() {
    this._handlers = new Map();
  }

  on(event, handler) {
    if (!event || typeof handler !== 'function') return;
    const list = this._handlers.get(event) || [];
    list.push(handler);
    this._handlers.set(event, list);
  }

  off(event, handler) {
    const list = this._handlers.get(event);
    if (!list) return;
    this._handlers.set(
      event,
      list.filter((h) => h !== handler),
    );
  }

  emit(event, payload) {
    const list = this._handlers.get(event);
    if (!list) return;
    for (const handler of list) {
      try {
        handler(payload);
      } catch (err) {
        console.error('[transport] event handler failed', err);
      }
    }
  }
}

export { EventBus };
