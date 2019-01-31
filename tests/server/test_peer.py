"""Test a Peer object."""
import asyncio
import os

import pytest

from snitun.server.peer import Peer
from snitun.multiplexer.message import CHANNEL_FLOW_PING


def test_init_peer():
    """Test simple init of peer."""
    peer = Peer("localhost", [], os.urandom(32), os.urandom(16))

    assert peer.hostname == "localhost"
    assert peer.multiplexer is None


async def test_init_peer_multiplexer(test_client, test_server):
    """Test setup multiplexer."""
    client = test_server[0]
    peer = Peer("localhost", [], os.urandom(32), os.urandom(16))

    with pytest.raises(RuntimeError):
        await peer.wait_disconnect()

    peer.init_multiplexer(test_client.reader, test_client.writer)
    assert not peer.multiplexer.wait().done()

    client.writer.close()
    client.close.set()

    await asyncio.sleep(0.1)
    assert peer.multiplexer.wait().done()


async def test_init_peer_multiplexer_crypto(test_client, test_server):
    """Test setup multiplexer with crypto."""
    client = test_server[0]
    peer = Peer("localhost", [], os.urandom(32), os.urandom(16))

    peer.init_multiplexer(test_client.reader, test_client.writer)
    assert not peer.multiplexer.wait().done()

    peer.multiplexer.ping()
    await asyncio.sleep(0.1)

    ping_data = await client.reader.read(1024)
    ping = peer._crypto.decrypt(ping_data)

    assert ping[16] == CHANNEL_FLOW_PING
    assert int.from_bytes(ping[17:21], 'big') == 0

    client.writer.close()
    client.close.set()

    await asyncio.sleep(0.1)
    assert peer.multiplexer.wait().done()
