"""Encrypt or Decrypt multiplexer transport data."""

from abc import ABC, abstractmethod
import os

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESGCMSIV

from ..exceptions import MultiplexerTransportDecrypt, MultiplexerTransportError

CIPHER_CBC = "aes-cbc"
CIPHER_GCM = "aes-gcm"
CIPHER_GCM_SIV = "aes-gcm-siv"
DEFAULT_CIPHER = CIPHER_CBC

# Both AEAD ciphers use a 96-bit (12 byte) nonce and append a 128-bit (16 byte)
# tag, so they share the same on-wire framing and overhead.
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
    def overhead(self) -> int:
        """Return the extra bytes added to each encrypted unit on the wire."""

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
    def overhead(self) -> int:
        """Return the extra bytes added to each encrypted unit on the wire."""
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


class _AEADCryptoTransport(CryptoTransport):
    """Shared base for AEAD transports framed as ``nonce || ciphertext || tag``.

    Each call to :meth:`encrypt` is an independent AEAD unit with a fresh random
    96-bit nonce prepended, so the transport is stateless. Subclasses only have
    to supply the concrete AEAD primitive.
    """

    __slots__ = ["_aead"]

    _aead: AESGCM | AESGCMSIV

    @property
    def overhead(self) -> int:
        """Return the extra bytes added to each encrypted unit on the wire."""
        return _GCM_NONCE_SIZE + _GCM_TAG_SIZE

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data for the transport."""
        nonce = os.urandom(_GCM_NONCE_SIZE)
        return nonce + self._aead.encrypt(nonce, data, None)

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data from the transport."""
        nonce, ciphertext = data[:_GCM_NONCE_SIZE], data[_GCM_NONCE_SIZE:]
        try:
            return self._aead.decrypt(nonce, ciphertext, None)
        except (InvalidTag, ValueError):
            # InvalidTag: bad tag/tampering. ValueError: a frame too short to
            # hold a valid nonce. Both mean the unit cannot be trusted.
            raise MultiplexerTransportDecrypt from None


class GCMCryptoTransport(_AEADCryptoTransport):
    """Encrypt/Decrypt Transport flow with AES-GCM (authenticated).

    The fresh random nonce per unit keeps the two connection directions (which
    share one key) collision-free only up to the birthday bound of a 96-bit
    nonce (~2**32 units per key). AES-GCM is catastrophic on nonce reuse, so
    this cipher is only safe when the key is fresh per session. When a key can
    persist across reconnects, prefer :class:`GCMSIVCryptoTransport`, which is
    nonce-misuse resistant.
    """

    __slots__ = ()

    def __init__(self, key: bytes) -> None:
        """Initialize crypto data."""
        self._aead = AESGCM(key)


class GCMSIVCryptoTransport(_AEADCryptoTransport):
    """Encrypt/Decrypt Transport flow with AES-GCM-SIV (authenticated).

    Unlike plain AES-GCM, AES-GCM-SIV (RFC 8452) is nonce-misuse resistant: a
    repeated nonce only reveals whether two units were identical instead of
    leaking the authentication key. This makes it the safer choice when a key
    can outlive a single connection (e.g. reused across reconnects).

    Requires OpenSSL 3.0+; :func:`create_crypto_transport` falls back to a clear
    error when the runtime cannot provide it.
    """

    __slots__ = ()

    def __init__(self, key: bytes) -> None:
        """Initialize crypto data."""
        self._aead = AESGCMSIV(key)


def gcm_siv_supported() -> bool:
    """Return True if the runtime's OpenSSL provides AES-GCM-SIV."""
    try:
        AESGCMSIV(b"\x00" * 32)
    except UnsupportedAlgorithm:
        return False
    return True


def create_crypto_transport(cipher: str, key: bytes, iv: bytes) -> CryptoTransport:
    """Create a crypto transport for the requested cipher."""
    if cipher == CIPHER_GCM_SIV:
        if not gcm_siv_supported():
            raise MultiplexerTransportError(
                "AES-GCM-SIV is not supported by this runtime; "
                "OpenSSL 3.0+ is required",
            )
        return GCMSIVCryptoTransport(key)
    if cipher == CIPHER_GCM:
        return GCMCryptoTransport(key)
    return CBCCryptoTransport(key, iv)
