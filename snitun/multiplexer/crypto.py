"""Encrypt or Decrypt multiplexer transport data."""

from abc import ABC, abstractmethod
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..exceptions import MultiplexerTransportDecrypt

CIPHER_CBC = "aes-cbc"
CIPHER_GCM = "aes-gcm"
DEFAULT_CIPHER = CIPHER_CBC

# AES-GCM uses a 96-bit (12 byte) nonce and appends a 128-bit (16 byte) tag.
_GCM_NONCE_SIZE = 12
_GCM_TAG_SIZE = 16


class CryptoTransport(ABC):
    """Abstract base for multiplexer transport encryption.

    A transport encrypts/decrypts the multiplexer frame header (and, on
    protocol version >= 2, the source IP carried in NEW messages). Each
    implementation reports how many bytes it adds to an encrypted unit on the
    wire so the multiplexer can frame reads without knowing the cipher.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def header_overhead(self) -> int:
        """Return the extra bytes added to an encrypted header on the wire."""

    @property
    @abstractmethod
    def data_tag_overhead(self) -> int:
        """Return the extra bytes added to an encrypted data unit on the wire."""

    @abstractmethod
    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data for the transport."""

    @abstractmethod
    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data from the transport.

        Raise :class:`MultiplexerTransportDecrypt` if an authenticated cipher
        detects tampering.
        """


class CBCCryptoTransport(CryptoTransport):
    """Encrypt/Decrypt Transport flow with AES-CBC.

    This is the default, unauthenticated cipher. The cipher state is a single
    stateful CBC stream, so every message chains off the previous ciphertext.
    """

    __slots__ = ["_cipher", "_decryptor", "_encryptor"]

    def __init__(self, key: bytes, iv: bytes) -> None:
        """Initialize crypto data."""
        self._cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend(),
        )
        self._encryptor = self._cipher.encryptor()
        self._decryptor = self._cipher.decryptor()

    @property
    def header_overhead(self) -> int:
        """Return the extra bytes added to an encrypted header on the wire."""
        return 0

    @property
    def data_tag_overhead(self) -> int:
        """Return the extra bytes added to an encrypted data unit on the wire."""
        return 0

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data for the transport."""
        return self._encryptor.update(data)

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data from the transport.

        CBC is not authenticated, so this never raises and the ciphertext is
        always accepted.
        """
        return self._decryptor.update(data)


class GCMCryptoTransport(CryptoTransport):
    """Encrypt/Decrypt Transport flow with AES-GCM (authenticated).

    Each call to :meth:`encrypt` is an independent AEAD unit framed as
    ``nonce(12) || ciphertext || tag(16)``. The nonce is a fresh random value
    per unit, so the transport is stateless and the two connection directions
    (which share one key) never reuse a nonce.
    """

    __slots__ = ["_aesgcm"]

    def __init__(self, key: bytes) -> None:
        """Initialize crypto data."""
        self._aesgcm = AESGCM(key)

    @property
    def header_overhead(self) -> int:
        """Return the extra bytes added to an encrypted header on the wire."""
        return _GCM_NONCE_SIZE + _GCM_TAG_SIZE

    @property
    def data_tag_overhead(self) -> int:
        """Return the extra bytes added to an encrypted data unit on the wire."""
        return _GCM_NONCE_SIZE + _GCM_TAG_SIZE

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data for the transport."""
        nonce = os.urandom(_GCM_NONCE_SIZE)
        return nonce + self._aesgcm.encrypt(nonce, data, None)

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data from the transport."""
        nonce, ciphertext = data[:_GCM_NONCE_SIZE], data[_GCM_NONCE_SIZE:]
        try:
            return self._aesgcm.decrypt(nonce, ciphertext, None)
        except InvalidTag:
            raise MultiplexerTransportDecrypt from None


def create_crypto_transport(cipher: str, key: bytes, iv: bytes) -> CryptoTransport:
    """Create a crypto transport for the requested cipher."""
    if cipher == CIPHER_GCM:
        return GCMCryptoTransport(key)
    return CBCCryptoTransport(key, iv)
