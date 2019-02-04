"""AES helper functions."""
from typing import Tuple
import os


def generate_aes_keyset() -> Tuple[bytes]:
    """Generat AES key + IV for CBC."""
    return (os.urandom(32), os.urandom(16))
