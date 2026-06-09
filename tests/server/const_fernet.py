"""Const value for Fernet tests."""

import json
from typing import Any

from cryptography.fernet import Fernet, MultiFernet

from snitun import PROTOCOL_VERSION
from snitun.multiplexer.crypto import DEFAULT_CIPHER

FERNET_TOKENS = [
    "XIKL24X0Fu83UmPLmWkXOBvvqsLq41tz2LljwafDyZw=",
    "ep1FyYA6epwbFxrtEJ2dii5BGvTx5-xU1oUCrF61qMA=",
]


def create_peer_config(
    valid: int,
    hostname: str,
    aes_key: bytes,
    aes_iv: bytes,
    alias: list[str] | None = None,
    cipher: str = DEFAULT_CIPHER,
) -> bytes:
    """Create a fernet token."""
    fernet = MultiFernet([Fernet(key) for key in FERNET_TOKENS])

    payload: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "valid": valid,
        "hostname": hostname,
        "alias": alias or [],
        "aes_key": aes_key.hex(),
        "aes_iv": aes_iv.hex(),
    }
    if cipher != DEFAULT_CIPHER:
        payload["cipher"] = cipher

    return fernet.encrypt(json.dumps(payload).encode())
