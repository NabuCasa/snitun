"""SniTun reference implementation."""
import asyncio
from typing import List

from .peer_manager import PeerManager
from .listener_sni import SNIProxy
from .listener_peer import PeerListener


async def snitun_server(fernet_keys: List[str],
                        sni_port=None,
                        sni_host=None,
                        peer_port=None,
                        peer_host=None):
    """Runner for SniTun server."""
    peers = PeerManager(fernet_keys)
    list_sni = SNIProxy(peers, host=sni_host, port=sni_port)
    list_peer = PeerListener(peers, host=peer_host, port=peer_port)

    # Start listener
    await asyncio.wait([list_peer.start(), list_sni.start()])

    # Return coro for stop SniTun server
    return asyncio.wait([list_peer.stop(), list_sni.stop()])
