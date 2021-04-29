"""Pytest fixtures for SniTun."""
import asyncio
from datetime import datetime, timedelta
import logging
import os
from unittest.mock import patch
import select
import socket
from threading import Thread

import attr
import pytest
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.listener_peer import PeerListener
from snitun.server.listener_sni import SNIProxy
from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager

from .server.const_fernet import FERNET_TOKENS

logging.basicConfig(level=logging.DEBUG)

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
    with patch("async_timeout.timeout", side_effect=asyncio.TimeoutError()):
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

    server = await asyncio.start_server(process_data, host="127.0.0.1", port="8866")

    yield connections

    server.close()
    await server.wait_closed()


@pytest.fixture
async def test_endpoint(loop):
    """Create a TCP test endpoint."""
    connections = []

    async def process_data(reader, writer):
        """Read data from client."""
        client = Client(reader, writer)
        connections.append(client)
        await client.close.wait()

    server = await asyncio.start_server(process_data, host="127.0.0.1", port="8822")

    yield connections

    server.close()
    await server.wait_closed()


@pytest.fixture
async def test_client(test_server):
    """Create a TCP test client."""

    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8866")

    yield Client(reader, writer)

    writer.close()


@pytest.fixture
def test_server_sync(loop):
    """Create a TCP test server."""
    connections = []
    shutdown = False

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 8366))
    sock.listen(2)
    sock.setblocking(False)

    def _incoming() -> None:
        nonlocal shutdown
        poller = select.epoll()

        poller.register(sock, select.EPOLLIN)
        while not shutdown:
            events = poller.poll(0.1)
            for _, _ in events:
                connection, _ = sock.accept()
                connections.append(connection)

    runner = Thread(target=_incoming)
    runner.start()

    yield connections

    shutdown = True
    runner.join()
    sock.close()


@pytest.fixture
def test_client_sync(test_server_sync):
    """Create a TCP test client."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 8366))

    yield sock

    sock.close()


@pytest.fixture
def test_client_ssl_sync(test_server_sync):
    """Create a TCP test client for SSL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 8366))

    yield sock

    sock.close()


@pytest.fixture
async def multiplexer_server(test_server, test_client, crypto_transport):
    """Create a multiplexer client from server."""
    client = test_server[0]

    async def mock_new_channel(multiplexer, channel):
        """Mock new channel."""

    multiplexer = Multiplexer(
        crypto_transport, client.reader, client.writer, mock_new_channel
    )

    yield multiplexer

    multiplexer.shutdown()
    client.close.set()


@pytest.fixture
async def multiplexer_client(test_client, crypto_transport):
    """Create a multiplexer client from server."""

    async def mock_new_channel(multiplexer, channel):
        """Mock new channel."""

    multiplexer = Multiplexer(
        crypto_transport, test_client.reader, test_client.writer, mock_new_channel
    )

    yield multiplexer

    multiplexer.shutdown()


@pytest.fixture
async def peer_manager(multiplexer_server, peer):
    """Create a localhost peer for tests."""
    manager = PeerManager(FERNET_TOKENS)
    manager._peers[peer.hostname] = peer
    yield manager


@pytest.fixture
async def sni_proxy(peer_manager):
    """Create a SNI Proxy."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863")
    await proxy.start()

    yield proxy
    await proxy.stop()


@pytest.fixture
async def test_client_ssl(sni_proxy):
    """Create a TCP test client."""

    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    yield Client(reader, writer)

    writer.close()


@pytest.fixture
def crypto_transport():
    """Create a CryptoTransport object."""
    key = os.urandom(32)
    iv = os.urandom(16)
    crypto = CryptoTransport(key, iv)

    yield crypto


@pytest.fixture
async def peer(loop, crypto_transport, multiplexer_server):
    """Init a peer with transport."""
    valid = datetime.utcnow() + timedelta(days=1)
    peer = Peer("localhost", valid, os.urandom(32), os.urandom(16))
    peer._crypto = crypto_transport
    peer._multiplexer = multiplexer_server

    yield peer


@pytest.fixture
async def peer_listener(peer_manager, peer):
    """Create a Peer listener."""
    listener = PeerListener(peer_manager, "127.0.0.1", "8893")
    await listener.start()

    # Cleanup mock peer
    peer_manager.remove_peer(peer)

    yield listener
    await listener.stop()


@pytest.fixture
async def test_client_peer(peer_listener):
    """Create a TCP test client."""

    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8893")

    yield Client(reader, writer)

    writer.close()
