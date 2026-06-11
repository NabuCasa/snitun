"""Encrypt or Decrypt multiplexer transport data."""

from abc import ABC, abstractmethod
from functools import cache
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

# AES-GCM builds the 96-bit nonce as a 32-bit direction prefix followed by a
# 64-bit per-frame counter. The two endpoints share one key, so each MUST own a
# distinct prefix or their counters would emit identical nonces - catastrophic
# for GCM. The counter guarantees uniqueness within a session without the
# birthday risk of random nonces.
_GCM_PREFIX_SIZE = 4
_GCM_COUNTER_SIZE = _GCM_NONCE_SIZE - _GCM_PREFIX_SIZE
_GCM_MAX_COUNTER = (1 << (_GCM_COUNTER_SIZE * 8)) - 1


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

    Each call to :meth:`encrypt` is an independent AEAD unit with its nonce
    prepended. The nonce is not secret, so it travels on the wire and
    :meth:`decrypt` is identical for every subclass and needs no counter state.
    Subclasses supply the concrete AEAD primitive and the nonce source.
    """

    __slots__ = ["_aead"]

    _aead: AESGCM | AESGCMSIV

    @property
    def overhead(self) -> int:
        """Return the extra bytes added to each encrypted unit on the wire."""
        return _GCM_NONCE_SIZE + _GCM_TAG_SIZE

    def _next_nonce(self) -> bytes:
        """Return the nonce for the next encrypted unit."""
        raise NotImplementedError

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data for the transport."""
        nonce = self._next_nonce()
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

    The nonce is a deterministic ``direction_prefix(4) || counter(8)``, so it is
    guaranteed unique within a session without the birthday risk of a random
    96-bit nonce. AES-GCM is catastrophic on nonce reuse, so this requires a
    fresh key per session: reusing a key across reconnects restarts the counter
    and repeats nonces. When a key can outlive a connection, prefer
    :class:`GCMSIVCryptoTransport`, which is nonce-misuse resistant.

    The two endpoints share one key, so ``is_initiator`` MUST differ between
    them (the client initiates, the server responds) to keep their counter
    nonces in disjoint ranges.
    """

    __slots__ = ["_counter", "_prefix"]

    def __init__(self, key: bytes, is_initiator: bool) -> None:
        """Initialize crypto data."""
        self._aead = AESGCM(key)
        self._prefix = (0 if is_initiator else 1).to_bytes(_GCM_PREFIX_SIZE, "big")
        self._counter = 0

    def _next_nonce(self) -> bytes:
        """Return the next ``prefix || counter`` nonce."""
        if self._counter > _GCM_MAX_COUNTER:
            # Wrapping the counter under a reused key would repeat a nonce,
            # which is catastrophic for GCM. Refuse rather than reuse.
            raise MultiplexerTransportError("AES-GCM nonce counter exhausted")
        nonce = self._prefix + self._counter.to_bytes(_GCM_COUNTER_SIZE, "big")
        self._counter += 1
        return nonce


class GCMSIVCryptoTransport(_AEADCryptoTransport):
    """Encrypt/Decrypt Transport flow with AES-GCM-SIV (authenticated).

    Unlike plain AES-GCM, AES-GCM-SIV (RFC 8452) is nonce-misuse resistant: a
    repeated nonce only reveals whether two units were identical instead of
    leaking the authentication key. That resistance lets it keep a stateless
    fresh random nonce per unit and stay the safer choice when a key can outlive
    a single connection (e.g. reused across reconnects).

    Requires OpenSSL 3.0+; :func:`create_crypto_transport` falls back to a clear
    error when the runtime cannot provide it.
    """

    __slots__ = ()

    def __init__(self, key: bytes) -> None:
        """Initialize crypto data."""
        self._aead = AESGCMSIV(key)

    def _next_nonce(self) -> bytes:
        """Return a fresh random nonce (safe under GCM-SIV misuse resistance)."""
        return os.urandom(_GCM_NONCE_SIZE)


@cache
def gcm_siv_supported() -> bool:
    """Return True if the runtime's OpenSSL provides AES-GCM-SIV.

    The result is cached: OpenSSL support cannot change within a process.
    """
    try:
        AESGCMSIV(b"\x00" * 32)
    except UnsupportedAlgorithm:
        return False
    return True


def create_crypto_transport(
    cipher: str,
    key: bytes,
    iv: bytes,
    *,
    is_initiator: bool,
) -> CryptoTransport:
    """Create a crypto transport for the requested cipher.

    ``is_initiator`` selects the AES-GCM counter-nonce direction prefix and MUST
    differ between the two endpoints (the client initiates, the server
    responds). It is ignored by the CBC and GCM-SIV ciphers.
    """
    if cipher == CIPHER_GCM_SIV:
        if not gcm_siv_supported():
            raise MultiplexerTransportError(
                "AES-GCM-SIV is not supported by this runtime; "
                "OpenSSL 3.0+ is required",
            )
        return GCMSIVCryptoTransport(key)
    if cipher == CIPHER_GCM:
        return GCMCryptoTransport(key, is_initiator)
    return CBCCryptoTransport(key, iv)
