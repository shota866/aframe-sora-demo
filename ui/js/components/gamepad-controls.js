// js/components/gamepad-controls.js
AFRAME.registerComponent('gamepad-controls', {
  schema: {
    gamepadIndex: { default: -1 }, // -1: auto-select first available pad
    axisDeadzone: { default: 0.15 },
    buttonThreshold: { default: 0.08 },
    emitRaw: { default: false },
  },

  init() {
    this._activeIndex = null;
    this._hadGamepad = false;
    this._deadzone = this._deadzone.bind(this);
    this._connected = this._connected.bind(this);
    this._disconnected = this._disconnected.bind(this);
    window.addEventListener('gamepadconnected', this._connected);
    window.addEventListener('gamepaddisconnected', this._disconnected);
  },

  remove() {
    window.removeEventListener('gamepadconnected', this._connected);
    window.removeEventListener('gamepaddisconnected', this._disconnected);
  },

  tick() {
    const gamepad = this._getGamepad();
    if (!gamepad) {
      if (this._hadGamepad) {
        this.el.emit(
          'gamepad-input',
          {
            connected: false,
            index: null,
            id: null,
            axes: { x: 0, y: 0 },
            buttons: { KeyW: false, KeyS: false, KeyA: false, KeyD: false },
          },
          false
        );
        this._hadGamepad = false;
      }
      return;
    }
    this._hadGamepad = true;

    const axes = gamepad.axes || [];
    const [rawX = 0, rawY = 0] = axes;

    const x = this._deadzone(rawX);
    const y = this._deadzone(rawY);
    const buttonThreshold = Math.max(0, this.data.buttonThreshold);

    const buttons = {
      KeyW: rawY < -buttonThreshold,
      KeyS: rawY > buttonThreshold,
      KeyA: rawX < -buttonThreshold,
      KeyD: rawX > buttonThreshold,
    };

    const detail = {
      connected: true,
      index: gamepad.index,
      id: gamepad.id,
      axes: { x, y },
      buttons,
    };
    if (this.data.emitRaw) {
      detail.raw = {
        axes: [...axes],
        buttons: gamepad.buttons.map((btn) => ({ pressed: btn.pressed, value: btn.value })),
      };
    }

    this.el.emit('gamepad-input', detail, false);
  },

  _deadzone(value) {
    const dz = this.data.axisDeadzone;
    if (Math.abs(value) < dz) return 0;
    const sign = Math.sign(value);
    const magnitude = (Math.abs(value) - dz) / (1 - dz);
    return THREE.MathUtils.clamp(sign * magnitude, -1, 1);
  },

  _connected(event) {
    if (this._activeIndex == null) {
      this._activeIndex = event.gamepad.index;
    }
  },

  _disconnected(event) {
    if (this._activeIndex === event.gamepad.index) {
      this._activeIndex = null;
    }
  },

  _getGamepad() {
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    if (!pads) return null;

    if (this.data.gamepadIndex >= 0) {
      return pads[this.data.gamepadIndex] || null;
    }

    if (this._activeIndex != null && pads[this._activeIndex]) {
      return pads[this._activeIndex];
    }

    for (const pad of pads) {
      if (pad) {
        this._activeIndex = pad.index;
        return pad;
      }
    }

    return null;
  },
});
