from __future__ import annotations

import json
import logging
import threading
from typing import Optional

from . import ControlServerTransport, CtrlCallback

LOGGER = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - runtime dependency only
    mqtt = None  # type: ignore[assignment]


class MQTTServerTransport(ControlServerTransport):
    """MQTT-based ctrl receiver (UI -> RPi) using the strategy interface."""

    def __init__(
        self,
        *,
        broker_host: str,
        broker_port: int = 1883,
        ctrl_topic: str = "aframe/ctrl",
        username: Optional[str] = None,
        password: Optional[str] = None,
        keepalive: int = 60,
        qos: int = 1,
        connect_timeout: float = 10.0,
        reconnect_min_delay: int = 1,
        reconnect_max_delay: int = 30,
    ) -> None:
        if mqtt is None:
            raise RuntimeError("paho-mqtt must be installed to use MQTT transport")

        self.broker_host = broker_host
        self.broker_port = broker_port
        self.ctrl_topic = ctrl_topic
        self.keepalive = keepalive
        self.qos = qos
        self.connect_timeout = connect_timeout

        self._client = mqtt.Client()
        if username or password:
            self._client.username_pw_set(username, password)
        self._client.reconnect_delay_set(reconnect_min_delay, reconnect_max_delay)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        self._ctrl_callback: Optional[CtrlCallback] = None
        self._connected = threading.Event()
        self._closed = threading.Event()
        self._lock = threading.Lock()

    def on_ctrl(self, callback: CtrlCallback) -> None:
        self._ctrl_callback = callback

    def connect(self) -> None:
        LOGGER.info(
            "connecting to MQTT broker: host=%s port=%s topic=%s",
            self.broker_host,
            self.broker_port,
            self.ctrl_topic,
        )

        self._client.connect(self.broker_host, self.broker_port, keepalive=self.keepalive)
        self._client.loop_start()

        if not self._connected.wait(timeout=self.connect_timeout):
            raise TimeoutError("MQTT connection timeout")

    def close(self) -> None:
        with self._lock:
            if self._closed.is_set():
                return
            self._closed.set()

        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            LOGGER.debug("MQTT disconnect raised", exc_info=True)

    def is_closed(self) -> bool:
        return self._closed.is_set()

    # ------------------------------------------------------------------ Callbacks
    def _on_connect(self, client, _userdata, flags, rc):  # noqa: ANN001
        if rc != 0:
            LOGGER.error("MQTT connect failed: rc=%s flags=%s", rc, flags)
            return

        LOGGER.info("MQTT connected: rc=%s flags=%s", rc, flags)
        self._connected.set()
        try:
            client.subscribe(self.ctrl_topic, qos=self.qos)
        except Exception:  # noqa: BLE001
            LOGGER.exception("failed to subscribe to ctrl topic")

    def _on_disconnect(self, _client, _userdata, rc):  # noqa: ANN001
        LOGGER.info("MQTT disconnected: rc=%s", rc)
        if rc != 0:
            LOGGER.warning("MQTT unexpected disconnect; client will try to reconnect")
        else:
            self._closed.set()

    def _on_message(self, _client, _userdata, msg):  # noqa: ANN001
        try:
            text = msg.payload.decode("utf-8")
            LOGGER.info("MQTT ctrl: topic=%s payload=%s", msg.topic, text)
            data = json.loads(text)
            self._ctrl_callback(data)
        except Exception:  # noqa: BLE001
            LOGGER.warning("MQTT ctrl message not utf-8; dropping topic=%s", msg.topic)
            return

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            LOGGER.warning("MQTT ctrl invalid JSON; dropping: %s", text)
            return

        callback = self._ctrl_callback
        if callback is None:
            LOGGER.debug("MQTT ctrl received but no callback registered: %s", payload)
            return

        try:
            callback(payload)
        except Exception:  # noqa: BLE001
            LOGGER.exception("ctrl callback raised")
