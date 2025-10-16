from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, List, Mapping, MutableMapping, Optional, Sequence


@dataclass(frozen=True)
class ServerConfig:
    signaling_urls: List[str]
    channel_id: str
    ctrl_label: str
    state_label: str
    metadata: Optional[Mapping[str, object]]


def _normalise_urls(raw: Sequence[str] | str | None) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        candidates = raw.split(",")
    else:
        candidates = list(raw)
    return [value.strip() for value in candidates if value and value.strip()]


def load_settings(
    args: object,
    env: MutableMapping[str, str] | Mapping[str, str] | None = None,
) -> ServerConfig:
    """Resolve configuration from CLI args and environment variables."""
    env = dict(env or os.environ)
    urls = env.get("VITE_SORA_SIGNALING_URLS") or env.get("SORA_SIGNALING_URL")
    signaling_urls = _normalise_urls(urls)
    if not signaling_urls:
        raise ValueError("SORA_SIGNALING_URL or VITE_SORA_SIGNALING_URLS must be set")

    channel_id = getattr(args, "room", None) or env.get("VITE_SORA_CHANNEL_ID") or "sora"
    ctrl_label = env.get("VITE_CTRL_LABEL", "#ctrl")
    state_label = env.get("SORA_STATE_LABEL", "#state")

    metadata_raw = env.get("SORA_METADATA")
    metadata: Optional[Mapping[str, object]]
    if metadata_raw:
        metadata = json.loads(metadata_raw)
    else:
        metadata = {}

    password = getattr(args, "password", None)
    if password:
        metadata = dict(metadata)
        metadata["password"] = password

    return ServerConfig(
        signaling_urls=signaling_urls,
        channel_id=channel_id,
        ctrl_label=ctrl_label,
        state_label=state_label,
        metadata=metadata or None,
    )

