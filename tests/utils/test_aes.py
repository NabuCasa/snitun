"""Test aes generator function."""

from snitun.multiplexer.crypto import CryptoTransport
from snitun.utils import aes


def test_aes_function() -> None:
    """Test crypto with generated keys."""
    key, iv = aes.generate_aes_keyset()
    assert CryptoTransport(key, iv)


def test_unique_aes() -> None:
    """Test unique aes function."""
    keyset_1 = aes.generate_aes_keyset()
    keyset_2 = aes.generate_aes_keyset()
    assert keyset_1 != keyset_2
