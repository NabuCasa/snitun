"""Test crypto module for transport."""

from collections.abc import Callable
import os

from cryptography.exceptions import UnsupportedAlgorithm
import pytest

from snitun.exceptions import MultiplexerTransportDecrypt, MultiplexerTransportError
from snitun.multiplexer import crypto as crypto_module
from snitun.multiplexer.crypto import (
    CIPHER_CBC,
    CIPHER_GCM,
    CIPHER_GCM_SIV,
    DEFAULT_CIPHER,
    CBCCryptoTransport,
    CryptoTransport,
    GCMCryptoTransport,
    GCMSIVCryptoTransport,
    create_crypto_transport,
    gcm_siv_supported,
)

# AEAD transport builders that share the nonce || ciphertext || tag framing.
# GCM and GCM-SIV differ in their constructor (GCM needs a direction), so each
# builder hides that behind a uniform key -> transport callable.
AEAD_BUILDERS: list[Callable[[bytes], CryptoTransport]] = [
    lambda key: GCMCryptoTransport(key, is_initiator=True),
    GCMSIVCryptoTransport,
]


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
    assert crypto.overhead == 0


@pytest.mark.parametrize("build", AEAD_BUILDERS)
def test_aead_round_trip(build: Callable[[bytes], CryptoTransport]) -> None:
    """An AEAD transport round-trips many messages."""
    key = os.urandom(32)
    encrypt_side = build(key)
    decrypt_side = build(key)

    for _ in range(10):
        test_data = os.urandom(32)
        assert decrypt_side.decrypt(encrypt_side.encrypt(test_data)) == test_data


@pytest.mark.parametrize("build", AEAD_BUILDERS)
def test_aead_overhead(build: Callable[[bytes], CryptoTransport]) -> None:
    """AEAD ciphers prepend a 12-byte nonce and append a 16-byte tag."""
    crypto = build(os.urandom(32))
    assert crypto.overhead == 28

    encrypted = crypto.encrypt(os.urandom(32))
    assert len(encrypted) == 32 + 28


@pytest.mark.parametrize("build", AEAD_BUILDERS)
def test_aead_fresh_nonce_per_call(build: Callable[[bytes], CryptoTransport]) -> None:
    """Encrypting the same plaintext twice yields different output."""
    crypto = build(os.urandom(32))
    data = b"same plaintext input value 32byt"
    assert crypto.encrypt(data) != crypto.encrypt(data)


@pytest.mark.parametrize("build", AEAD_BUILDERS)
def test_aead_detects_tampering(build: Callable[[bytes], CryptoTransport]) -> None:
    """Flipping any byte of the frame fails the tag check."""
    key = os.urandom(32)
    crypto = build(key)
    encrypted = bytearray(crypto.encrypt(os.urandom(32)))

    for index in range(len(encrypted)):
        tampered = bytearray(encrypted)
        tampered[index] ^= 0x01
        with pytest.raises(MultiplexerTransportDecrypt):
            build(key).decrypt(bytes(tampered))


@pytest.mark.parametrize("build", AEAD_BUILDERS)
def test_aead_rejects_short_frame(build: Callable[[bytes], CryptoTransport]) -> None:
    """A truncated frame fails cleanly with a decrypt error."""
    crypto = build(os.urandom(32))
    # Shorter than the tag (empty ciphertext) -> InvalidTag.
    with pytest.raises(MultiplexerTransportDecrypt):
        crypto.decrypt(os.urandom(12))
    # Shorter than a valid nonce -> ValueError, also surfaced as a decrypt error.
    with pytest.raises(MultiplexerTransportDecrypt):
        crypto.decrypt(b"x")


def test_gcm_siv_supported() -> None:
    """The runtime used for the test suite provides AES-GCM-SIV."""
    assert gcm_siv_supported() is True


def test_gcm_siv_supported_false_without_openssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe reports False when OpenSSL cannot provide AES-GCM-SIV."""

    def _raise(_key: bytes) -> None:
        raise UnsupportedAlgorithm("no gcm-siv")

    monkeypatch.setattr(crypto_module, "AESGCMSIV", _raise)
    # Bypass the cache to exercise the probe directly.
    assert gcm_siv_supported.__wrapped__() is False


def test_factory_selects_cipher() -> None:
    """The factory returns the implementation for the requested cipher."""
    key = os.urandom(32)
    iv = os.urandom(16)

    assert isinstance(
        create_crypto_transport(CIPHER_CBC, key, iv, is_initiator=True),
        CBCCryptoTransport,
    )
    assert isinstance(
        create_crypto_transport(CIPHER_GCM, key, iv, is_initiator=True),
        GCMCryptoTransport,
    )
    assert isinstance(
        create_crypto_transport(CIPHER_GCM_SIV, key, iv, is_initiator=True),
        GCMSIVCryptoTransport,
    )
    # Unknown / default cipher falls back to CBC.
    assert isinstance(
        create_crypto_transport(DEFAULT_CIPHER, key, iv, is_initiator=True),
        CBCCryptoTransport,
    )


def test_factory_gcm_siv_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The factory raises a clear error when the runtime lacks AES-GCM-SIV."""
    monkeypatch.setattr(crypto_module, "gcm_siv_supported", lambda: False)
    with pytest.raises(MultiplexerTransportError, match="AES-GCM-SIV"):
        create_crypto_transport(
            CIPHER_GCM_SIV,
            os.urandom(32),
            os.urandom(16),
            is_initiator=True,
        )


def test_gcm_counter_nonce_is_deterministic_and_increments() -> None:
    """GCM emits prefix || counter nonces that advance by one per unit."""
    crypto = GCMCryptoTransport(os.urandom(32), is_initiator=True)
    first = crypto.encrypt(b"")[:12]
    second = crypto.encrypt(b"")[:12]

    # Initiator prefix is 0; counter starts at 0 and increments.
    assert first == (0).to_bytes(4, "big") + (0).to_bytes(8, "big")
    assert second == (0).to_bytes(4, "big") + (1).to_bytes(8, "big")


def test_gcm_initiator_and_responder_nonces_are_disjoint() -> None:
    """The two directions never share a nonce, even with the same key.

    This is the critical safety property: both ends use one key, so a shared
    nonce would be catastrophic for GCM. The direction prefix keeps the two
    counter ranges disjoint.
    """
    key = os.urandom(32)
    initiator = GCMCryptoTransport(key, is_initiator=True)
    responder = GCMCryptoTransport(key, is_initiator=False)

    initiator_nonces = {initiator.encrypt(b"")[:12] for _ in range(1000)}
    responder_nonces = {responder.encrypt(b"")[:12] for _ in range(1000)}

    assert initiator_nonces.isdisjoint(responder_nonces)


def test_gcm_round_trip_between_opposite_roles() -> None:
    """An initiator and a responder GCM transport decrypt each other."""
    key = os.urandom(32)
    initiator = GCMCryptoTransport(key, is_initiator=True)
    responder = GCMCryptoTransport(key, is_initiator=False)

    for _ in range(10):
        payload = os.urandom(32)
        assert responder.decrypt(initiator.encrypt(payload)) == payload
        assert initiator.decrypt(responder.encrypt(payload)) == payload


def test_gcm_counter_exhaustion_raises() -> None:
    """GCM refuses to wrap its counter rather than repeat a nonce."""
    crypto = GCMCryptoTransport(os.urandom(32), is_initiator=True)
    # Jump to the last valid counter value.
    crypto._counter = crypto_module._GCM_MAX_COUNTER
    crypto.encrypt(b"")  # consumes the final nonce
    with pytest.raises(MultiplexerTransportError, match="counter exhausted"):
        crypto.encrypt(b"")
