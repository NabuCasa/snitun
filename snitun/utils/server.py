"""Utils for server handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any, NotRequired, TypedDict

from cryptography.fernet import Fernet, MultiFernet

from ..multiplexer.crypto import DEFAULT_CIPHER

MAX_READ_SIZE = 4_096
MAX_BUFFER_SIZE = 1_024_000
PROTOCOL_VERSION = 2
DEFAULT_PROTOCOL_VERSION = 0


class TokenData(TypedDict):
    """Token data."""

    valid: float
    hostname: str
    aes_key: str
    aes_iv: str
    protocol_version: NotRequired[int]
    cipher: NotRequired[str]
    alias: list[str] | None


def generate_client_token(
    tokens: list[str],
    valid_delta: timedelta,
    hostname: str,
    aes_key: bytes,
    aes_iv: bytes,
    cipher: str = DEFAULT_CIPHER,
) -> bytes:
    """Generate a token for client."""
    fernet = MultiFernet([Fernet(key) for key in tokens])
    valid = datetime.now(tz=UTC) + valid_delta

    payload: dict[str, Any] = {
        "valid": valid.timestamp(),
        "hostname": hostname,
        "aes_key": aes_key.hex(),
        "aes_iv": aes_iv.hex(),
        "protocol_version": PROTOCOL_VERSION,
    }
    # Only include cipher when it differs from the default so existing
    # tokens stay byte-for-byte identical.
    if cipher != DEFAULT_CIPHER:
        payload["cipher"] = cipher

    return fernet.encrypt(json.dumps(payload).encode())
