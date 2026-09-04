"""Time-sortable identifiers that remain opaque at API boundaries."""

import secrets
import time
from uuid import UUID


def new_prefixed_id(prefix: str) -> str:
    """Return a prefixed UUIDv7-compatible identifier."""

    unix_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    value = unix_ms << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return f"{prefix}_{UUID(int=value)}"
