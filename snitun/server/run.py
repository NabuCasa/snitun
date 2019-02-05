"""SniTun reference implementation."""
import asyncio
from typing import List

from .peer_manager import PeerManager
from .listener_sni import SNIProxy
from .listener_peer import PeerListener


class SniTunServer:
    """SniTunServer helper class."""

    def __init__(self,
                 fernet_keys: List[str],
                 sni_port=None,
                 sni_host=None,
                 peer_port=None,
                 peer_host=None):
        """Initialize SniTun Server."""
        self._peers = PeerManager(fernet_keys)
        self._list_sni = SNIProxy(self._peers, host=sni_host, port=sni_port)
        self._list_peer = PeerListener(
            self._peers, host=peer_host, port=peer_port)

    @property
    def peers(self) -> PeerManager:
        """Return peer manager."""
        return self._peers

    def start(self):
        """Run server.

        Return coroutine.
        """
        return asyncio.wait([self._list_peer.start(), self._list_sni.start()])

    def stop(self):
        """Stop server.

        Return coroutine.
        """
        return asyncio.wait([self._list_peer.stop(), self._list_sni.stop()])
