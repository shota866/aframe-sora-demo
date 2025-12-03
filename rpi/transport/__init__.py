from __future__ import annotations

from typing import Callable, Protocol

CtrlPayload = dict
CtrlCallback = Callable[[CtrlPayload], None]


class ControlServerTransport(Protocol):
    """Strategy interface for receiving ctrl payloads on the RPi side."""

    def on_ctrl(self, callback: CtrlCallback) -> None:
        """Register callback invoked with decoded ctrl payloads."""
        ...

    def connect(self) -> None:
        """Establish underlying transport connection and start receiving."""
        ...

    def close(self) -> None:
        """Tear down the transport connection."""
        ...

    def is_closed(self) -> bool:
        """Return True if the transport has permanently shut down."""
        ...


__all__ = [
    "ControlServerTransport",
    "CtrlCallback",
    "CtrlPayload",
]
