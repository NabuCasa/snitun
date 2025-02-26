"""Encrypt or Decrypt multiplexer transport data."""

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..exceptions import MultiplexerTransportDecrypt


class CryptoTransport:
    """Encrypt/Decrypt Transport flow."""

    __slots__ = (
        "_cipher",
        "_decrypt_buffer",
        "_decryptor",
        "_encrypt_buffer",
        "_encryptor",
    )

    def __init__(self, key: bytes, iv: bytes) -> None:
        """Initialize crypto data."""
        self._cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend(),
        )
        self._encryptor = self._cipher.encryptor()
        self._decryptor = self._cipher.decryptor()
        self._encrypt_buffer = bytearray(48)
        self._decrypt_buffer = bytearray(48)

    def encrypt(self, data: bytes) -> bytearray:
        """Encrypt data from transport."""
        data_len = self._encryptor.update_into(data, self._encrypt_buffer)
        return self._encrypt_buffer[:data_len]

    def decrypt(self, data: bytes) -> bytearray:
        """Decrypt data from transport."""
        try:
            data_len = self._decryptor.update_into(data, self._decrypt_buffer)
        except InvalidTag:
            raise MultiplexerTransportDecrypt from None
        return self._decrypt_buffer[:data_len]
