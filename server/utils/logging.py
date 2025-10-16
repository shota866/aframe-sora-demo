from __future__ import annotations

import logging
from typing import Optional


def setup_logging(level: int | str = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )


__all__ = ["setup_logging"]

