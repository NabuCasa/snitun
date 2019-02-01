"""SniTun reference implementation."""
import asyncio
from typing import List

from .peer_manager import PeerManager
from .listener_sni import SNIProxy
from .listener_peer import PeerListener


class SniTunServer:

    def __init__(self,
                 fernet_keys: List[str],
                 sni_port=None,
                 sni_host=None,
                 peer_port=None,
                 peer_host=None):
        """Initialize SniTun Server."""
        peers = PeerManager(fernet_keys)
        self._list_sni = SNIProxy(peers, host=sni_host, port=sni_port)
        self._list_peer = PeerListener(peers, host=peer_host, port=peer_port)
        self._peers = peers

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
