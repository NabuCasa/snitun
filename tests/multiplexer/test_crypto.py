"""Test crypto module for transport."""

import os

from snitun.multiplexer.crypto import CryptoTransport


def test_setup_crypto_transport():
    """Test crypto transport setup."""
    key = os.urandom(32)
    iv = os.urandom(16)
    crypto = CryptoTransport(key, iv)

    for _ in range(1, 10):
        test_data = os.urandom(32)
        assert crypto.decrypt(crypto.encrypt(test_data)) == test_data
