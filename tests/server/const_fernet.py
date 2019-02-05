"""Const value for Fernet tests."""
import json

from cryptography.fernet import Fernet, MultiFernet

FERNET_TOKENS = [
    "XIKL24X0Fu83UmPLmWkXOBvvqsLq41tz2LljwafDyZw=",
    "ep1FyYA6epwbFxrtEJ2dii5BGvTx5-xU1oUCrF61qMA="
]


def create_peer_config(valid: int, hostname: str, aes_key: bytes,
                       aes_iv: bytes) -> bytes:
    """Create a fernet token."""
    fernet = MultiFernet([Fernet(key) for key in FERNET_TOKENS])

    return fernet.encrypt(
        json.dumps({
            "valid": valid,
            "hostname": hostname,
            "aes_key": aes_key.hex(),
            "aes_iv": aes_iv.hex(),
        }).encode())
