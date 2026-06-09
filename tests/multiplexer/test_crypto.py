"""Test crypto module for transport."""

import os

import pytest

from snitun.exceptions import MultiplexerTransportDecrypt
from snitun.multiplexer.crypto import (
    CIPHER_CBC,
    CIPHER_GCM,
    DEFAULT_CIPHER,
    CBCCryptoTransport,
    GCMCryptoTransport,
    create_crypto_transport,
)


def test_setup_crypto_transport() -> None:
    """Test crypto transport setup."""
    key = os.urandom(32)
    iv = os.urandom(16)
    crypto = CBCCryptoTransport(key, iv)

    for _ in range(1, 10):
        test_data = os.urandom(32)
        assert crypto.decrypt(crypto.encrypt(test_data)) == test_data


def test_cbc_split_encrypt_matches_combined() -> None:
    """For CBC, encrypting in two calls matches one combined call.

    This invariant keeps the wire format unchanged now that _write_message
    encrypts the header and the NEW data as separate calls.
    """
    key = os.urandom(32)
    iv = os.urandom(16)
    header = os.urandom(32)
    data = os.urandom(48)

    split = CBCCryptoTransport(key, iv)
    combined = CBCCryptoTransport(key, iv)
    assert (
        split.encrypt(header) + split.encrypt(data)
        == combined.encrypt(header + data)
    )


def test_cbc_overhead() -> None:
    """CBC adds no overhead on the wire."""
    crypto = CBCCryptoTransport(os.urandom(32), os.urandom(16))
    assert crypto.header_overhead == 0
    assert crypto.data_tag_overhead == 0


def test_gcm_round_trip() -> None:
    """A GCM transport round-trips many messages."""
    key = os.urandom(32)
    encrypt_side = GCMCryptoTransport(key)
    decrypt_side = GCMCryptoTransport(key)

    for _ in range(10):
        test_data = os.urandom(32)
        assert decrypt_side.decrypt(encrypt_side.encrypt(test_data)) == test_data


def test_gcm_overhead() -> None:
    """GCM prepends a 12-byte nonce and appends a 16-byte tag."""
    crypto = GCMCryptoTransport(os.urandom(32))
    assert crypto.header_overhead == 28
    assert crypto.data_tag_overhead == 28

    encrypted = crypto.encrypt(os.urandom(32))
    assert len(encrypted) == 32 + 28


def test_gcm_fresh_nonce_per_call() -> None:
    """Encrypting the same plaintext twice yields different output."""
    crypto = GCMCryptoTransport(os.urandom(32))
    data = b"same plaintext input value 32byt"
    assert crypto.encrypt(data) != crypto.encrypt(data)


def test_gcm_detects_tampering() -> None:
    """Flipping any byte of the frame fails the tag check."""
    key = os.urandom(32)
    crypto = GCMCryptoTransport(key)
    encrypted = bytearray(crypto.encrypt(os.urandom(32)))

    for index in range(len(encrypted)):
        tampered = bytearray(encrypted)
        tampered[index] ^= 0x01
        with pytest.raises(MultiplexerTransportDecrypt):
            GCMCryptoTransport(key).decrypt(bytes(tampered))


def test_gcm_rejects_short_frame() -> None:
    """A truncated frame fails cleanly with a decrypt error."""
    crypto = GCMCryptoTransport(os.urandom(32))
    with pytest.raises(MultiplexerTransportDecrypt):
        crypto.decrypt(b"too-short")


def test_factory_selects_cipher() -> None:
    """The factory returns the implementation for the requested cipher."""
    key = os.urandom(32)
    iv = os.urandom(16)

    assert isinstance(create_crypto_transport(CIPHER_CBC, key, iv), CBCCryptoTransport)
    assert isinstance(create_crypto_transport(CIPHER_GCM, key, iv), GCMCryptoTransport)
    # Unknown / default cipher falls back to CBC.
    assert isinstance(
        create_crypto_transport(DEFAULT_CIPHER, key, iv),
        CBCCryptoTransport,
    )
