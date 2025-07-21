"""Utils for server handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import NotRequired, TypedDict

from cryptography.fernet import Fernet, MultiFernet

MAX_READ_SIZE = 4_096
MAX_BUFFER_SIZE = 1_024_000
PROTOCOL_VERSION = 1
DEFAULT_PROTOCOL_VERSION = 0


class TokenData(TypedDict):
    """Token data."""

    valid: float
    hostname: str
    aes_key: str
    aes_iv: str
    protocol_version: NotRequired[int]
    alias: list[str] | None


def generate_client_token(
    tokens: list[str],
    valid_delta: timedelta,
    hostname: str,
    aes_key: bytes,
    aes_iv: bytes,
) -> bytes:
    """Generate a token for client."""
    fernet = MultiFernet([Fernet(key) for key in tokens])
    valid = datetime.now(tz=UTC) + valid_delta

    return fernet.encrypt(
        json.dumps(
            {
                "valid": valid.timestamp(),
                "hostname": hostname,
                "aes_key": aes_key.hex(),
                "aes_iv": aes_iv.hex(),
                "protocol_version": PROTOCOL_VERSION,
            },
        ).encode(),
    )
