// js/components/car-drive.js
AFRAME.registerComponent('car-drive', {
  schema: {
    forwardSign: { default: +1 }, // +1=+Z前 / -1=−Z前（W/Sが逆ならここを変更）
    maxSpeed: { default: 25 }, // m/s
    accel: { default: 5 }, // m/s^2
    brake: { default: 7 }, // m/s^2
    coastDecel: { default: 0.0 }, // m/s^2（任意）
    yawRate: { default: 3.2 }, // rad/s（A左+, D右-）
    yawSlew: { default: 40 }, // rad/s^2（角速度の変化上限）
    deadbandV: { default: 0.05 }, // m/s
    deadbandW: { default: 0.02 }, // rad/s
    muRoll: { default: 0.5 }, // （床）転がり抵抗係数
    airLin: { default: 0.05 }, // （空気）線形項 [1/s]
    airQuad: { default: 0.02 }, // （空気）二乗項 [1/m]
  },

  init() {
    // 入力
    this.keys = {};
    this._keysKeyboard = {};
    this._keysGamepad = {};
    this._gamepadAxes = { x: 0, y: 0 };
    this._down = (e) => {
      const k = e.code;
      if (k === 'KeyW' || k === 'KeyA' || k === 'KeyS' || k === 'KeyD') {
        this._keysKeyboard[k] = true;
        this._updateCombinedKeys();
        e.preventDefault();
      }
    };
    this._up = (e) => {
      const k = e.code;
      if (k === 'KeyW' || k === 'KeyA' || k === 'KeyS' || k === 'KeyD') {
        this._keysKeyboard[k] = false;
        this._updateCombinedKeys();
        e.preventDefault();
      }
    };
    this._blur = () => {
      this._resetInputs();
    };
    this._vis = () => {
      if (document.hidden) this._blur();
    };
    this._attached = false;
    this._updateCombinedKeys();

    this._onGamepadInput = (e) => {
      const detail = e.detail || {};
      if (detail.connected === false) {
        this._keysGamepad = {};
        this._gamepadAxes = { x: 0, y: 0 };
      } else {
        this._keysGamepad = { ...(detail.buttons || {}) };
        const axes = detail.axes || {};
        const ax = typeof axes.x === 'number' ? axes.x : 0;
        const ay = typeof axes.y === 'number' ? axes.y : 0;
        this._gamepadAxes = { x: ax, y: ay };
      }
      this._updateCombinedKeys();
    };

    // 内部状態
    this._yaw = this.el.object3D.rotation.y; // 現在のヨー角[rad]
    this._omega = 0; // 角速度[rad/s]
    this._speed = 0; // 前後速度[m/s]

    // 作業用
    this._q = new THREE.Quaternion();
    this._fwd = new THREE.Vector3(0, 0, 1); // forwardSignで符号は後で切替

    const attach = () => this._attachListeners();
    const scene = this.el.sceneEl;
    if (scene?.hasLoaded) attach();
    else scene.addEventListener('loaded', attach, { once: true });
  },

  play() {
    this._attachListeners();
  },
  pause() {
    this._detachListeners();
  },
  remove() {
    this._detachListeners();
  },

  _resetInputs() {
    this._keysKeyboard = {};
    this._keysGamepad = {};
    this._gamepadAxes = { x: 0, y: 0 };
    this._updateCombinedKeys();
  },

  _updateCombinedKeys() {
    this.keys = {
      KeyW: this._isInputActive('KeyW'),
      KeyS: this._isInputActive('KeyS'),
      KeyA: this._isInputActive('KeyA'),
      KeyD: this._isInputActive('KeyD'),
    };
  },

  _isInputActive(code) {
    return !!(this._keysKeyboard[code] || this._keysGamepad[code]);
  },

  _attachListeners() {
    if (this._attached) return;
    window.addEventListener('keydown', this._down, true);
    window.addEventListener('keyup', this._up, true);
    window.addEventListener('blur', this._blur, true);
    document.addEventListener('visibilitychange', this._vis, true);
    this.el.sceneEl?.addEventListener('gamepad-input', this._onGamepadInput, false);
    this._attached = true;
  },
  _detachListeners() {
    if (!this._attached) return;
    window.removeEventListener('keydown', this._down, true);
    window.removeEventListener('keyup', this._up, true);
    window.removeEventListener('blur', this._blur, true);
    document.removeEventListener('visibilitychange', this._vis, true);
    this.el.sceneEl?.removeEventListener('gamepad-input', this._onGamepadInput, false);
    this._attached = false;
  },

  tick(t, dtms) {
    const body = this.el.body;
    if (!body) return;

    const dt = Math.min(dtms / 1000, 0.05);
    const P = this.data;
    const g = 9.8;

    this._updateCombinedKeys();
    const axes = this._gamepadAxes || { x: 0, y: 0 };
    const analogSteer = THREE.MathUtils.clamp(-axes.x, -1, 1);
    const analogThrottle = THREE.MathUtils.clamp(-axes.y, -1, 1);

    // 入力
    const w = this._isInputActive('KeyW');
    const s = this._isInputActive('KeyS');
    const a = this._isInputActive('KeyA');
    const d = this._isInputActive('KeyD');
    if (
      w ||
      s ||
      a ||
      d ||
      Math.abs(analogSteer) > 1e-3 ||
      Math.abs(analogThrottle) > 1e-3
    ) {
      body.wakeUp();
    }

    // ── 角速度：A左(+), D右(−) ──
    let steerInput = analogSteer;
    if (a && !d) steerInput = 1;
    else if (d && !a) steerInput = -1;
    else if (a && d) steerInput = 0;
    const omegaTarget = P.yawRate * THREE.MathUtils.clamp(steerInput, -1, 1);
    const slew = P.yawSlew * dt;
    const dOmega = THREE.MathUtils.clamp(omegaTarget - this._omega, -slew, +slew);
    this._omega += dOmega;
    if (Math.abs(this._omega) < P.deadbandW) this._omega = 0;

    // ヨー角の積分→姿勢
    this._yaw += this._omega * dt;
    this._q.setFromEuler(new THREE.Euler(0, this._yaw, 0, 'YXZ'));
    body.quaternion.set(this._q.x, this._q.y, this._q.z, this._q.w);

    // 物理の角速度は使わないので抑制
    body.angularVelocity.set(0, 0, 0);

    // ── 前後加速度：入力 ± 摩擦 ＋ 空気抵抗 ──
    let throttleInput = analogThrottle;
    if (w && !s) throttleInput = 1;
    else if (s && !w) throttleInput = -1;
    else if (w && s) throttleInput = 0;
    throttleInput = Math.abs(throttleInput) < 1e-3 ? 0 : THREE.MathUtils.clamp(throttleInput, -1, 1);

    let aCmd = 0;
    if (throttleInput > 0) aCmd = throttleInput * P.accel;
    else if (throttleInput < 0) aCmd = throttleInput * P.brake;

    const signV = Math.sign(this._speed) || 0;
    const aRoll = -signV * (P.muRoll * g);
    const aAir =
      -signV * (P.airLin * Math.abs(this._speed) + P.airQuad * (this._speed * this._speed));
    const aCoast =
      Math.abs(throttleInput) < 1e-3 && P.coastDecel > 0 ? -signV * P.coastDecel : 0;

    const aTotal = aCmd + aRoll + aAir + aCoast;

    this._speed += aTotal * dt;
    this._speed = THREE.MathUtils.clamp(this._speed, -P.maxSpeed, P.maxSpeed);
    if (Math.abs(this._speed) < P.deadbandV) this._speed = 0;

    // ── 前方ベクトル（水平） ──
    this._fwd.set(0, 0, P.forwardSign).applyQuaternion(this._q);
    this._fwd.y = 0;
    if (this._fwd.lengthSq() > 0) this._fwd.normalize();

    // ── 速度を“前後方向のみ”に設定（横滑りゼロ） ──
    const vy = body.velocity.y; // 垂直は物理任せ
    body.velocity.x = this._fwd.x * this._speed;
    body.velocity.z = this._fwd.z * this._speed;
    body.velocity.y = vy;
  },
});
