# A-Frame Manager Demo

Unified workspace containing the Web UI and Python manager used for Sora data channel experiments.

## Project layout

- `ui/` – A-Frame based web client.
- `server/` – Python manager and helper scripts.
- `rpi/` – Raspberry Pi state receiver and log viewer utilities.

## Getting started

### Web UI

```
cd ui
npm install
npm run start
```

The `start` script launches a simple static server on http://localhost:8000. Use `npm run lint` to check formatting with Prettier.

### Manager

```
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
python server/manager.py --help
```

### Raspberry Pi tooling

```
# on the Raspberry Pi
cd rpi
npm install sora-js-sdk wrtc dotenv
SORA_STATE_LOG=1 node state-recv.js
```

The receiver prints interpolated frames and, when `SORA_STATE_LOG=1` or `SORA_STATE_LOG_PATH` is set, appends raw `#state` payloads to `state.log`. To follow the log in a readable format:

```
node rpi/state-log-viewer.js --history 20
```

To forward manager-side state updates (either from stdin JSON lines or a built-in demo trajectory) use:

```
python server/rpi_state_publisher.py --stdin
```

Add `--demo` to emit a circular trajectory when no external payloads are queued, or pipe your own JSON objects matching the existing `#state` schema.
