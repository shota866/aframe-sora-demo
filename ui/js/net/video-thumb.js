const DEFAULT_ELEMENT_ID = 'cameraThumb';
const DEFAULT_TRACK_LABEL = 'camera-thumb';

function ensureVideoElement(elementId) {
  let el = document.getElementById(elementId);
  if (el && el.tagName.toLowerCase() === 'video') {
    return el;
  }
  el = document.createElement('video');
  el.id = elementId;
  document.body.appendChild(el);
  return el;
}

export class VideoThumbnail {
  constructor({
    elementId = DEFAULT_ELEMENT_ID,
    trackLabel = DEFAULT_TRACK_LABEL,
    autoCreate = true,
  } = {}) {
    this.trackLabel = trackLabel;
    this.videoEl = autoCreate ? ensureVideoElement(elementId) : document.getElementById(elementId);
    if (!this.videoEl) {
      throw new Error(`Video element #${elementId} not found and autoCreate=false`);
    }
    this.videoEl.autoplay = true;
    this.videoEl.muted = true;
    this.videoEl.playsInline = true;
    this.videoEl.hidden = true;
    this._currentStream = null;
  }

  handleTrack(event) {
    if (!event || !event.track || event.track.kind !== 'video') return false;
    const trackLabel = event.track.label || event.track.id || '';
    if (this.trackLabel && trackLabel !== this.trackLabel) return false;

    let stream = (event.streams && event.streams[0]) || this._currentStream;
    if (!stream) {
      stream = new MediaStream();
    }
    if (!stream.getTracks().includes(event.track)) {
      stream.addTrack(event.track);
    }

    this._currentStream = stream;
    this.videoEl.srcObject = stream;
    this.videoEl.hidden = false;
    event.track.addEventListener('ended', () => {
      this._handleTrackEnded(event.track);
    });
    const playPromise = this.videoEl.play();
    if (playPromise?.catch) {
      playPromise.catch((err) => console.warn('[video-thumb] autoplay failed', err));
    }
    return true;
  }

  clear() {
    if (this.videoEl) {
      this.videoEl.pause();
      this.videoEl.srcObject = null;
      this.videoEl.hidden = true;
    }
    this._currentStream = null;
  }

  _handleTrackEnded(track) {
    if (!this._currentStream) return;
    const tracks = this._currentStream.getTracks();
    tracks.forEach((existing) => {
      if (existing === track) {
        this._currentStream.removeTrack(existing);
      }
    });
    if (this._currentStream.getTracks().length === 0) {
      this.clear();
    }
  }
}
