"""Tests for core multiplexer handler."""
import asyncio

from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.message import CHANNEL_FLOW_PING


async def test_init_multiplexer_server(test_server, test_client):
    """Test to create a new Multiplexer from server socket."""
    client = test_server[0]

    multiplexer = Multiplexer(client.reader, client.writer)

    assert not multiplexer.wait().done()
    await multiplexer.shutdown()
    client.close.set()


async def test_init_multiplexer_client(test_client):
    """Test to create a new Multiplexer from client socket."""
    multiplexer = Multiplexer(test_client.reader, test_client.writer)

    assert not multiplexer.wait().done()
    await multiplexer.shutdown()


async def test_multiplexer_server_close(multiplexer_server, multiplexer_client):
    """Test a close from server peers."""
    assert not multiplexer_server.wait().done()
    assert not multiplexer_client.wait().done()

    await multiplexer_server.shutdown()
    await asyncio.sleep(0.2)

    assert multiplexer_server.wait().done()
    assert multiplexer_client.wait().done()


async def test_multiplexer_client_close(multiplexer_server, multiplexer_client):
    """Test a close from client peers."""
    assert not multiplexer_server.wait().done()
    assert not multiplexer_client.wait().done()

    await multiplexer_client.shutdown()
    await asyncio.sleep(0.2)

    assert multiplexer_server.wait().done()
    assert multiplexer_client.wait().done()


async def test_multiplexer_ping(test_server, multiplexer_client):
    """Test a ping between peers."""
    client = test_server[0]
    multiplexer_client.ping()

    await asyncio.sleep(0.2)

    data = await client.reader.read(60)
    assert data[16] == CHANNEL_FLOW_PING
