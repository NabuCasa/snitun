"""Utils for server handling."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from cryptography.fernet import Fernet, MultiFernet


def generate_client_token(
    tokens: list[str],
    valid_delta: timedelta,
    hostname: str,
    aes_key: bytes,
    aes_iv: bytes,
)-> bytes:
    """Generate a token for client."""
    fernet = MultiFernet([Fernet(key) for key in tokens])
    valid = datetime.now(tz=timezone.utc) + valid_delta

    return fernet.encrypt(
        json.dumps(
            {
                "valid": valid.timestamp(),
                "hostname": hostname,
                "aes_key": aes_key.hex(),
                "aes_iv": aes_iv.hex(),
            },
        ).encode(),
    )
