"""Manage peer connections."""
import asyncio
from datetime import datetime
import json
import logging
from typing import Callable, List, Optional
from enum import Enum

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ..exceptions import SniTunInvalidPeer
from .peer import Peer

_LOGGER = logging.getLogger(__name__)


class PeerManagerEvent(str, Enum):
    """Peer Manager event flags."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class PeerManager:
    """Manage Peer connections."""

    def __init__(
        self,
        fernet_tokens: List[str],
        throttling: Optional[int] = None,
        event_callback: Optional[Callable[[Peer, PeerManagerEvent], None]] = None,
    ):
        """Initialize Peer Manager."""
        self._fernet = MultiFernet([Fernet(key) for key in fernet_tokens])
        self._loop = asyncio.get_event_loop()
        self._throttling = throttling
        self._event_callback = event_callback
        self._peers = {}

    @property
    def connections(self) -> int:
        """Return count of connected devices."""
        return len(self._peers)

    def create_peer(self, fernet_data: bytes) -> Peer:
        """Create a new peer from crypt config."""
        try:
            data = self._fernet.decrypt(fernet_data).decode()
            config = json.loads(data)
        except (InvalidToken, json.JSONDecodeError) as err:
            _LOGGER.warning("Invalid fernet token")
            raise SniTunInvalidPeer() from err

        # Check if token is valid
        valid = datetime.utcfromtimestamp(config["valid"])
        if valid < datetime.utcnow():
            _LOGGER.warning("Token was expired")
            raise SniTunInvalidPeer()

        # Extract configuration
        hostname = config["hostname"]
        aes_key = bytes.fromhex(config["aes_key"])
        aes_iv = bytes.fromhex(config["aes_iv"])

        return Peer(hostname, valid, aes_key, aes_iv, throttling=self._throttling)

    def add_peer(self, peer: Peer) -> None:
        """Register peer to internal hostname list."""
        if self.peer_available(peer.hostname):
            _LOGGER.warning("Found stale peer connection")
            self._peers[peer.hostname].multiplexer.shutdown()

        _LOGGER.debug("New peer connection: %s", peer.hostname)
        self._peers[peer.hostname] = peer

        if self._event_callback:
            self._loop.call_soon(self._event_callback, peer, PeerManagerEvent.CONNECTED)

    def remove_peer(self, peer: Peer) -> None:
        """Remove peer from list."""
        if self._peers.get(peer.hostname) != peer:
            return
        _LOGGER.debug("Close peer connection: %s", peer.hostname)
        self._peers.pop(peer.hostname)

        if self._event_callback:
            self._loop.call_soon(
                self._event_callback, peer, PeerManagerEvent.DISCONNECTED
            )

    def peer_available(self, hostname: str) -> bool:
        """Check if peer available and return True or False."""
        if hostname in self._peers:
            return self._peers[hostname].is_ready
        return False

    def get_peer(self, hostname: str) -> Optional[Peer]:
        """Get peer."""
        return self._peers.get(hostname)
