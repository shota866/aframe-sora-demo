# A-Frame Manager Demo

Unified workspace containing the Web UI and Python manager used for Sora data channel experiments.

## Project layout

- `ui/` – A-Frame based web client.
- `server/` – Python manager and helper scripts.
- `rpi/` – Raspberry Pi state receiver and log viewer utilities.

## Getting started
```
- 実行手順
    - UI表示
        - ui直下でnpm run dev
    - managerサーバ立ち上げ
        - source .venv/bin/activate
        - python3 -m server.main／python3 -m server.main --log-level DEBUG（ログ出力多め）
    - ラズパイ(Ubuntu)ログ表示
        - ラズパイにsshログイン：ssh ssh tsunogayashouta@192.168.207.131(ssh tsunogayashouta@shotapi.local)
        - cd aframe-manager-demo2/
        - ROSを読み込む：source /opt/ros/jazzy/setup.bash
        - ROS_DOMAINを合わせる：export ROS_DOMAIN_ID=10
        - ラズパイ → Jetsonにcmd_velを送るノードを起動：python3 rpi/state_recv.py --publish-cmd-vel --cmd-vel-topic /cmd_vel

```
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

### RealSense → Sora video bridge

`rpi/realsense/image_to_sora.py` subscribes to `/camera/color/image_raw`, shrinks each frame (default 320x180 @ 15 fps), and sends it to the Sora channel as a small thumbnail stream. Install `python3-opencv`, `ros-${ROS_DISTRO}-cv-bridge`, and the Sora Python SDK on the Raspberry Pi, then run:

```
python3 -m rpi.realsense.image_to_sora \
  --signaling-url wss://example.signaling \
  --channel your-channel \
  --track-label camera-thumb
```

Set `SORA_SIGNALING_URLS` / `SORA_CHANNEL_ID` env vars (optionally via `.env`) instead of CLI flags if you prefer. Use `--ui-slot top-right` (default) so the Web UI can pin the thumbnail to the upper-right corner.
