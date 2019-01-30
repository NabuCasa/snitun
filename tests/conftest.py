"""Pytest fixtures for SniTun."""
import asyncio
from unittest.mock import patch

import attr
import pytest

from snitun.multiplexer.core import Multiplexer

# pylint: disable=redefined-outer-name


@attr.s
class Client:
    """Represent a TCP client object."""

    reader = attr.ib(type=asyncio.StreamReader)
    writer = attr.ib(type=asyncio.StreamWriter)
    close = attr.ib(type=asyncio.Event, default=asyncio.Event())


@pytest.fixture
def raise_timeout():
    """Raise timeout on async-timeout."""
    with patch('async_timeout.timeout', side_effect=asyncio.TimeoutError()):
        yield


@pytest.fixture
async def test_server(loop):
    """Create a TCP test server."""
    connections = []

    async def process_data(reader, writer):
        """Read data from client."""
        client = Client(reader, writer)
        connections.append(client)
        await client.close.wait()

    server = await asyncio.start_server(
        process_data, host="127.0.0.1", port="8866")

    loop.create_task(server.serve_forever())
    yield connections

    server.close()
    await server.wait_closed()


@pytest.fixture
async def test_client(test_server):
    """Create a TCP test client."""

    reader, writer = await asyncio.open_connection(
        host="127.0.0.1", port="8866")

    yield Client(reader, writer)

    writer.close()
    await writer.wait_closed()


@pytest.fixture
async def multiplexer_server(test_server, test_client):
    """Create a multiplexer client from server."""
    client = test_server[0]

    async def mock_new_channel(channel):
        """Mock new channel."""

    multiplexer = Multiplexer(client.reader, client.writer, mock_new_channel)

    yield multiplexer

    await multiplexer.shutdown()
    client.close.set()


@pytest.fixture
async def multiplexer_client(test_client):
    """Create a multiplexer client from server."""

    async def mock_new_channel(channel):
        """Mock new channel."""

    multiplexer = Multiplexer(test_client.reader, test_client.writer,
                              mock_new_channel)

    yield multiplexer

    await multiplexer.shutdown()
