"""Manage peer connections."""
from typing import List
import json

from cryptography.fernet import Fernet, MultiFernet

from .peer import Peer
from ..exceptions import SniTunInvalidPeer


class PeerManager:
    """Manage Peer connections."""

    def __init__(self, fernet_tokens: List[str]):
        """Initialize Peer Manager."""
        self._fernet = MultiFernet([Fernet(key) for key in fernet_tokens])
        self._peers = {}

    def register_peer(self, fernet_data: bytes) -> Peer:
        """Create a new peer from crypt config."""

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
