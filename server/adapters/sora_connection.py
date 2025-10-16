from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from sora_sdk import Sora, SoraConnection, SoraSignalingErrorCode


@dataclass(frozen=True)
class SoraConnectionConfig:
    signaling_urls: list[str]
    channel_id: str
    ctrl_label: str
    state_label: str
    metadata: Optional[Mapping[str, object]]


@dataclass(frozen=True)
class SoraEventHandlers:
    on_set_offer: Callable[[SoraConnection, str], None]
    on_notify: Callable[[SoraConnection, str], None]
    on_data_channel: Callable[[SoraConnection, str], None]
    on_message: Callable[[SoraConnection, str, bytes], None]
    on_disconnect: Callable[[SoraConnection, SoraSignalingErrorCode, str], None]


def create_connection(
    sora: Sora,
    config: SoraConnectionConfig,
    handlers: SoraEventHandlers,
) -> SoraConnection:
    """Create and configure a Sora connection with pre-wired event handlers."""
    conn = sora.create_connection(
        signaling_urls=config.signaling_urls,
        role="sendrecv",
        channel_id=config.channel_id,
        metadata=config.metadata,
        audio=False,
        video=True,
        data_channel_signaling=True,
        data_channels=[
            {"label": config.ctrl_label, "direction": "recvonly", "ordered": True},
            {"label": config.state_label, "direction": "sendonly", "ordered": True},
        ],
    )

    def _wrap_set_offer(raw: str, *, ref=conn) -> None:
        handlers.on_set_offer(ref, raw)

    def _wrap_notify(raw: str, *, ref=conn) -> None:
        handlers.on_notify(ref, raw)

    def _wrap_data_channel(label: str, *, ref=conn) -> None:
        handlers.on_data_channel(ref, label)

    def _wrap_message(label: str, data: bytes, *, ref=conn) -> None:
        handlers.on_message(ref, label, data)

    def _wrap_disconnect(code: SoraSignalingErrorCode, msg: str, *, ref=conn) -> None:
        handlers.on_disconnect(ref, code, msg)

    conn.on_set_offer = _wrap_set_offer
    conn.on_notify = _wrap_notify
    conn.on_data_channel = _wrap_data_channel
    conn.on_message = _wrap_message
    conn.on_disconnect = _wrap_disconnect
    return conn


__all__ = ["SoraConnectionConfig", "SoraEventHandlers", "create_connection"]

