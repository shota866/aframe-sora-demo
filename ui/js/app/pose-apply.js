const DEG_PER_RAD = 180 / Math.PI;

export function createPoseApplier(carEl) {
  if (!carEl) {
    throw new Error('createPoseApplier requires a car entity');
  }
  const object3D = carEl.object3D;
  const euler = new THREE.Euler(0, 0, 0, 'YXZ');

  function apply(pose = {}, vel = {}) {
    const x = Number.isFinite(pose.x) ? pose.x : 0;
    const y = Number.isFinite(pose.y) ? pose.y : 0;
    const z = Number.isFinite(pose.z) ? pose.z : 0;
    const yaw = Number.isFinite(pose.yaw) ? pose.yaw : 0;

    object3D.position.set(x, y, z);
    euler.set(0, yaw, 0);
    object3D.setRotationFromEuler(euler);
    object3D.updateMatrixWorld(true);

    carEl.setAttribute('position', { x, y, z });
    carEl.setAttribute('rotation', { x: 0, y: yaw * DEG_PER_RAD, z: 0 });

    carEl.dataset.vx = Number.isFinite(vel.vx) ? vel.vx.toFixed(3) : '0';
    carEl.dataset.wz = Number.isFinite(vel.wz) ? vel.wz.toFixed(3) : '0';
  }

  return { apply };
}
