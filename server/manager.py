from __future__ import annotations

from typing import Iterable, Mapping, Optional

from .config import ServerConfig
from .main import main
from .services.conductor import Conductor


class ManagerNode(Conductor):
    """Compatibility wrapper exposing the legacy ManagerNode interface."""

    def __init__(
        self,
        signaling_urls: Iterable[str],
        channel_id: str,
        ctrl_label: str,
        state_label: str,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> None:
        config = ServerConfig(
            signaling_urls=list(signaling_urls),
            channel_id=channel_id,
            ctrl_label=ctrl_label,
            state_label=state_label,
            metadata=metadata,
        )
        super().__init__(config)


__all__ = ["ManagerNode", "main"]


if __name__ == "__main__":
    main()

