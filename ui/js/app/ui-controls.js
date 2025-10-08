// js/app/ui-controls.js
(function () {
  function onSceneLoaded(cb) {
    const sceneEl = document.querySelector('a-scene');
    if (!sceneEl) return;
    if (sceneEl.hasLoaded) cb(sceneEl);
    else sceneEl.addEventListener('loaded', () => cb(sceneEl), { once: true });
  }

  // 1) Canvas フォーカス
  function setupCanvasFocus() {
    onSceneLoaded((sceneEl) => {
      const canvas = sceneEl.canvas;
      if (!canvas) return;
      canvas.setAttribute('tabindex', '0');
      canvas.addEventListener('click', () => canvas.focus());
      setTimeout(() => canvas.focus(), 0);
    });
  }

  // 2) E-Stop（速度/角速度を即ゼロ）
  function setupEStop() {
    const btn = document.getElementById('eStopButton');
    if (!btn) return;
    const carEl = document.getElementById('car');
    btn.addEventListener('click', (e) => {
      window.dispatchEvent(new CustomEvent('app:estop'));
      const body = carEl?.components['dynamic-body']?.body;
      if (body) {
        body.velocity.set(0, 0, 0);
        body.angularVelocity.set(0, 0, 0);
      } else {
        console.warn('[E-Stop] dynamic-body not ready yet.');
      }
      e.target.blur();
    });
  }

  // 3) カメラ切り替え（Cキー）
  function setupCameraToggle() {
    window.addEventListener(
      'keydown',
      (e) => {
        if (e.code !== 'KeyC') return;
        const chase = document.getElementById('chasecam');
        const debug = document.getElementById('debugcam');
        if (!chase || !debug) return;

        const useDebug = !debug.getAttribute('camera')?.active;
        debug.setAttribute('camera', 'active:' + useDebug);
        chase.setAttribute('camera', 'active:' + !useDebug);
        console.log('camera:', useDebug ? 'debug' : 'chase');
      },
      true
    );
  }

  // 4) CSV保存（#dlLog がある場合のみ有効。window.__diag をCSV化）
  function setupCsvSave() {
    const btn = document.getElementById('dlLog');
    if (!btn) return; // ボタンがないなら何もしない

    btn.addEventListener('click', () => {
      const rows = window.__diag;
      if (!rows || !Array.isArray(rows) || rows.length === 0) {
        alert('保存できるログが見つかりません（window.__diag が空）');
        return;
      }
      const csv = rows.map((r) => r.join(',')).join('\n');
      const blob = new Blob([csv], { type: 'text/csv' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'diag.csv';
      a.click();
    });
  }

  // 初期化
  document.addEventListener('DOMContentLoaded', () => {
    setupCanvasFocus();
    setupEStop();
    setupCameraToggle();
    setupCsvSave(); // ボタンが無ければ自動的に無効
  });
})();
