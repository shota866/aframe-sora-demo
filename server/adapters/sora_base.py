from __future__ import annotations

from typing import Optional

from sora_sdk import Sora


def create_sora_instance(existing: Optional[Sora] = None) -> Sora:
    """Return a Sora SDK instance, creating one if necessary."""
    return existing or Sora()


__all__ = ["create_sora_instance"]

