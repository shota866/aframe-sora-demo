import { CAR_HEIGHT, DEG_PER_RAD, POSITION_OFFSET, POSITION_SCALE } from '../app/constants.js';

export function applyServerState(carEl, state) {
  if (!carEl || !state) return;
  const x = Number(state.x);
  const y = Number(state.y);
  const theta = Number(state.theta);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return;

  const worldX = (x - POSITION_OFFSET) * POSITION_SCALE;
  const worldZ = -(y - POSITION_OFFSET) * POSITION_SCALE;
  const yawDeg = Number.isFinite(theta) ? 90 - theta * DEG_PER_RAD : 90;

  carEl.object3D.position.set(worldX, CAR_HEIGHT, worldZ);
  carEl.object3D.rotation.set(0, (yawDeg * Math.PI) / 180, 0);
  carEl.object3D.updateMatrixWorld(true);

  carEl.setAttribute('position', { x: worldX, y: CAR_HEIGHT, z: worldZ });
  carEl.setAttribute('rotation', { x: 0, y: yawDeg, z: 0 });
}

