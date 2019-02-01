"""Test runner of SniTun Server."""
import asyncio

from snitun.server.run import SniTunServer

from .const_fernet import FERNET_TOKENS


async def test_snitun_runner():
    """Test SniTun Server runner object."""
    server = SniTunServer(
        FERNET_TOKENS, peer_host="localhost", sni_host="Localhost")

    await server.start()

    await asyncio.sleep(0.1)

    await server.stop()
