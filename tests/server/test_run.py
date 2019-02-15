"""Test runner of SniTun Server."""
import asyncio

from snitun.server.run import SniTunServer, SniTunServerSingle

from .const_fernet import FERNET_TOKENS


async def test_snitun_runner():
    """Test SniTun Server runner object."""
    server = SniTunServer(
        FERNET_TOKENS, peer_host="127.0.0.1", sni_host="127.0.0.1")

    await server.start()

    await asyncio.sleep(0.1)

    await server.stop()


async def test_snitun_single_runner():
    """Test SniTunSingle Server runner object."""
    server = SniTunServerSingle(FERNET_TOKENS, host="127.0.0.1")

    await server.start()

    await asyncio.sleep(0.1)

    await server.stop()
