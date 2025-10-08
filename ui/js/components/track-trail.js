import 'aframe';

const AFRAME = window.AFRAME;
const THREE = AFRAME?.THREE;

if (!AFRAME || !THREE) {
  console.error('[track-trail] A-Frame not ready.');
} else if (!AFRAME.components['track-car']) {
  AFRAME.registerComponent('track-car', {
    schema: {
      target: { type: 'selector', default: '#car' },
      distanceThreshold: { type: 'number', default: 0.5 },
      boxWidth: { type: 'number', default: 0.9 },
      boxDepth: { type: 'number', default: 0.2 },
      boxHeight: { type: 'number', default: 0.05 },
      boxColor: { type: 'color', default: '#FF5733' },
    },

    init: function () {
      this.car = this.data.target;
      this.lastPosition = new THREE.Vector3(Infinity, Infinity, Infinity);
      this._currentPosition = new THREE.Vector3();

      if (!this.car) {
        console.error('[track-trail] target car not found.');
      }
    },

    update: function () {
      this.car = this.data.target;
    },

    tick: function () {
      if (!this.car) return;

      this.car.object3D.getWorldPosition(this._currentPosition);

      if (this.lastPosition.distanceTo(this._currentPosition) > this.data.distanceThreshold) {
        const segment = document.createElement('a-box');
        segment.setAttribute('position', {
          x: this._currentPosition.x,
          y: this.data.boxHeight / 2,
          z: this._currentPosition.z,
        });
        segment.setAttribute('rotation', {
          x: 0,
          y: this.car.getAttribute('rotation').y,
          z: 0,
        });
        segment.setAttribute('width', this.data.boxWidth);
        segment.setAttribute('depth', this.data.boxDepth);
        segment.setAttribute('height', this.data.boxHeight);
        segment.setAttribute('color', this.data.boxColor);
        this.el.appendChild(segment);
        this.lastPosition.copy(this._currentPosition);
      }
    },
  });
}
