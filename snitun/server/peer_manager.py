"""Manage peer connections."""
from datetime import datetime
import json
import logging
from typing import List, Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ..exceptions import SniTunInvalidPeer
from .peer import Peer

_LOGGER = logging.getLogger(__name__)


class PeerManager:
    """Manage Peer connections."""

    def __init__(self, fernet_tokens: List[str], throttling: Optional[int] = None):
        """Initialize Peer Manager."""
        self._fernet = MultiFernet([Fernet(key) for key in fernet_tokens])
        self._throttling = throttling
        self._peers = {}

    @property
    def connections(self):
        """Return count of connected devices."""
        return len(self._peers)

    def register_peer(self, fernet_data: bytes) -> Peer:
        """Create a new peer from crypt config."""
        try:
            data = self._fernet.decrypt(fernet_data).decode()
            config = json.loads(data)
        except (InvalidToken, json.JSONDecodeError):
            _LOGGER.warning("Invalid fernet token")
            raise SniTunInvalidPeer()

        # Check if token is valid
        valid = datetime.utcfromtimestamp(config["valid"])
        if valid < datetime.utcnow():
            _LOGGER.warning("Token was expired")
            raise SniTunInvalidPeer()

        # Extract configuration
        hostname = config["hostname"]
        aes_key = bytes.fromhex(config["aes_key"])
        aes_iv = bytes.fromhex(config["aes_iv"])

        peer = self._peers[hostname] = Peer(
            hostname, valid, aes_key, aes_iv, throttling=self._throttling
        )
        return peer

    def remove_peer(self, peer: Peer):
        """Remove peer from list."""
        self._peers.pop(peer.hostname, None)

    def peer_available(self, hostname: str) -> bool:
        """Check if peer available and return True or False."""
        if hostname in self._peers:
            return self._peers[hostname].is_ready
        return False

    def get_peer(self, hostname: str) -> Peer:
        """Get peer."""
        return self._peers.get(hostname)
