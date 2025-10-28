const DEFAULT_HZ = 25;

export class KeyboardCtrlRepeater {
  constructor(options = {}) {
    this.hz = Number(options.hz) || DEFAULT_HZ;
    this.onDirection = options.onDirection;
    this.onInputChange = typeof options.onInputChange === 'function' ? options.onInputChange : null;
    this.intervalMs = Math.max(10, Math.round(1000 / this.hz));
    this.repeatMs = Math.max(10, Number(options.repeatMs) || 120);
    this.keys = new Set();
    this.timer = null;
    this._lastDirection = [];
    this._lastSendDirection = [];
    this._lastSendAt = 0;
    this._handleKeyDown = this._handleKeyDown.bind(this);
    this._handleKeyUp = this._handleKeyUp.bind(this);
  }

  start() {
    if (this.timer !== null) return;
    window.addEventListener('keydown', this._handleKeyDown);
    window.addEventListener('keyup', this._handleKeyUp);
    this.timer = window.setInterval(() => this._tick(), this.intervalMs);
  }

  stop() {
    if (this.timer !== null) {
      window.clearInterval(this.timer);
      this.timer = null;
    }
    this._lastDirection = [];
    this._lastSendDirection = [];
    this._lastSendAt = 0;
    window.removeEventListener('keydown', this._handleKeyDown);
    window.removeEventListener('keyup', this._handleKeyUp);
  }

  _handleKeyDown(event) {
    if (event.repeat) return;
    this.keys.add(event.code);
    this._notifyInput('keydown', event.code);
  }

  _handleKeyUp(event) {
    this.keys.delete(event.code);
    this._notifyInput('keyup', event.code);
  }

  _tick() {
    const direction = this._currentDirection();
    const now =
      typeof performance !== 'undefined' && typeof performance.now === 'function'
        ? performance.now()
        : Date.now();
    const directionChanged = !directionsEqual(direction, this._lastDirection);
    if (directionChanged) {
      this._lastDirection = direction;
      this._notifyInput(direction.length ? 'direction' : 'idle', null, direction);
      if (typeof this.onDirection === 'function') {
        this.onDirection(direction);
        this._lastSendDirection = direction;
        this._lastSendAt = now;
      }
      if (direction.length === 0) {
        this._lastSendDirection = [];
      }
    } else if (
      direction.length &&
      typeof this.onDirection === 'function' &&
      (!directionsEqual(direction, this._lastSendDirection) || now - this._lastSendAt >= this.repeatMs)
    ) {
      this.onDirection(direction);
      this._lastSendDirection = direction;
      this._lastSendAt = now;
    }
  }

  _currentDirection() {
    const directions = [];
    if (this._isPressed('ArrowUp', 'KeyW') && !this._isPressed('ArrowDown', 'KeyS')) {
      directions.push('UP');
    }
    if (this._isPressed('ArrowDown', 'KeyS') && !this._isPressed('ArrowUp', 'KeyW')) {
      directions.push('DOWN');
    }
    if (this._isPressed('ArrowLeft', 'KeyA') && !this._isPressed('ArrowRight', 'KeyD')) {
      directions.push('LEFT');
    }
    if (this._isPressed('ArrowRight', 'KeyD') && !this._isPressed('ArrowLeft', 'KeyA')) {
      directions.push('RIGHT');
    }
    return directions;
  }

  _isPressed(...codes) {
    return codes.some((code) => this.keys.has(code));
  }

  _notifyInput(type, key = null, directionOverride) {
    if (!this.onInputChange) return;
    const direction =
      directionOverride !== undefined ? directionOverride : this._currentDirection();
    const keys = Array.from(this.keys).sort();
    this.onInputChange({ type, key, direction, keys });
  }
}

function directionsEqual(a = [], b = []) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

export default KeyboardCtrlRepeater;
