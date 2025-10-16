const DEFAULT_HZ = 25;

export class KeyboardCtrlRepeater {
  constructor(options = {}) {
    this.hz = Number(options.hz) || DEFAULT_HZ;
    this.onDirection = options.onDirection;
    this.onInputChange = typeof options.onInputChange === 'function' ? options.onInputChange : null;
    this.intervalMs = Math.max(10, Math.round(1000 / this.hz));
    this.keys = new Set();
    this.timer = null;
    this._lastDirection = null;
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
    this._lastDirection = null;
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
    if (direction !== this._lastDirection) {
      this._lastDirection = direction;
      this._notifyInput(direction ? 'direction' : 'idle', null, direction);
      if (typeof this.onDirection === 'function') {
        this.onDirection(direction);
      }
    }
  }

  _currentDirection() {
    const up = this._isPressed('ArrowUp', 'KeyW');
    const down = this._isPressed('ArrowDown', 'KeyS');
    const left = this._isPressed('ArrowLeft', 'KeyA');
    const right = this._isPressed('ArrowRight', 'KeyD');

    if (up && !down) return 'UP';
    if (down && !up) return 'DOWN';
    if (left && !right) return 'LEFT';
    if (right && !left) return 'RIGHT';
    return null;
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

export default KeyboardCtrlRepeater;

