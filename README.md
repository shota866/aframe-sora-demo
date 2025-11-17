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
        - ラズパイにsshログイン：
            - ssh tsunogayashouta@shotapi.local
            - (ssh tsunogayashouta@192.168.197.146)
            - ログインできない時はmac側でssh-keygen -R shotapi.local打つといける
        - Ros2の環境を読み込む:source /opt/ros/jazzy/setup.bash
        - 仮想環境を有効化：source ~/venv-sora-ros/bin/activate
        - cd aframe-manager-demo2/
        - python3 rpi/state_recv.py --log-level INFO（遅延ログを出したい場合：python3 -m rpi.state_recv --log-level INFO 2>&1 | tee /tmp/state-recv.log）
            - python3 rpi/state_recv.py \
                --log-level INFO \
                --publish-cmd-vel \
                --max-linear-speed 0.3 \
                --max-angular-speed -0.3 \
                2>&1 | tee /tmp/state-recv.log

            - tail -F /tmp/state-recv.log | rg --line-buffered 'TIMELINE'(遅延内容を別ターミナルで抜き出す)
    - ROSノード立ち上げ
        - source ~/venv-sora/bin/activate
        - cd aframe-manager-demo2/
        - python3 rpi/state_recv.py --publish-cmd-vel
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
