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
    console.info('[video-thumb] accepted track', trackLabel);

    // もともとのストリーム処理
    let stream = this._currentStream || event.streams?.[0] || new MediaStream();
    if (!stream) {
      stream = new MediaStream();
    }
    if (!stream.getTracks().includes(event.track)) {
      stream.addTrack(event.track);
    }

    this._currentStream = stream;

    // ★ ① 同じ stream なら srcObject を再設定しない
    if (this.videoEl.srcObject !== stream) {
      this.videoEl.srcObject = stream;
    }

    this.videoEl.hidden = false;

    event.track.addEventListener('ended', () => {
      this._handleTrackEnded(event.track);
    });
    console.info('[video-thumb] before play, hasPlayedOnce =', this._hasPlayedOnce);

    // ★ ② play() は一度だけ実行
    if (!this._hasPlayedOnce) {
      const playResult = this.videoEl.play();
      console.info('[video-thumb] play() called, result =', playResult);

      if (playResult && typeof playResult.then === 'function') {
        // Promise を返してくるブラウザ用
        playResult
          .then(() => {
            console.info('[video-thumb] play started (promise resolved)');
            this._hasPlayedOnce = true;
          })
          .catch((err) => {
            console.warn('[video-thumb] autoplay failed (promise rejected)', err);
            this._hasPlayedOnce = false;
          });
      } else {
        // Promise を返さない古い/特殊なパターン用
        console.info('[video-thumb] play() did not return a promise; assuming started');
        this._hasPlayedOnce = true;
      }
      setTimeout(() => {
        console.info(
          '[video-thumb] video state',
          {
            paused: this.videoEl.paused,
            readyState: this.videoEl.readyState,
            videoWidth: this.videoEl.videoWidth,
            videoHeight: this.videoEl.videoHeight,
          },
        );
      }, 1000);

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
