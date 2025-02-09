"""Pytest fixtures for SniTun."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import ipaddress
import logging
import os
import select
import socket
import ssl
from threading import Thread
from unittest.mock import patch

from aiohttp import web
import attr
import pytest
from pytest_aiohttp import AiohttpServer
import trustme

from snitun.client.connector import Connector
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.listener_peer import PeerListener
from snitun.server.listener_sni import SNIProxy
from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager
from snitun.utils.aiohttp_client import SniTunClientAioHttp
from snitun.utils.asyncio import asyncio_timeout

from .server.const_fernet import FERNET_TOKENS

logging.basicConfig(level=logging.DEBUG)


IP_ADDR = ipaddress.ip_address("8.8.8.8")
BAD_ADDR = ipaddress.ip_address("8.8.1.1")


@attr.s
class Client:
    """Represent a TCP client object."""

    reader = attr.ib(type=asyncio.StreamReader)
    writer = attr.ib(type=asyncio.StreamWriter)
    close = attr.ib(type=asyncio.Event, default=asyncio.Event())


@pytest.fixture
def raise_timeout() -> Generator[None, None, None]:
    """Raise timeout on async-timeout."""
    with patch.object(asyncio_timeout, "timeout", side_effect=TimeoutError()):
        yield


@pytest.fixture
async def test_server() -> AsyncGenerator[list[Client], None]:
    """Create a TCP test server."""
    connections = []

    async def process_data(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Read data from client."""
        client = Client(reader, writer)
        connections.append(client)
        await client.close.wait()

    server = await asyncio.start_server(process_data, host="127.0.0.1", port="8866")

    yield connections

    server.close()


@pytest.fixture
async def test_client(test_server: list[Client]) -> AsyncGenerator[Client, None]:
    """Create a TCP test client."""
    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8866")

    yield Client(reader, writer)

    writer.close()


@pytest.fixture
def test_server_sync(
    event_loop: asyncio.AbstractEventLoop,
) -> Generator[list[socket.socket], None, None]:
    """Create a TCP test server."""
    connections: list[socket.socket] = []
    shutdown = False

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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

        poller.close()

    runner = Thread(target=_incoming)
    runner.start()

    yield connections

    shutdown = True
    runner.join()
    sock.close()


@pytest.fixture
def test_client_sync(
    test_server_sync: list[socket.socket],
) -> Generator[socket.socket, None, None]:
    """Create a TCP test client."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 8366))

    yield sock

    sock.close()


@pytest.fixture
def test_client_ssl_sync(
    test_server_sync: list[socket.socket],
) -> Generator[socket.socket, None, None]:
    """Create a TCP test client for SSL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 8366))

    yield sock

    sock.close()


@pytest.fixture
async def multiplexer_server(
    test_server: list[Client],
    test_client: Client,
    crypto_transport: CryptoTransport,
) -> AsyncGenerator[Multiplexer, None]:
    """Create a multiplexer client from server."""
    client = test_server[0]

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""

    multiplexer = Multiplexer(
        crypto_transport,
        client.reader,
        client.writer,
        mock_new_channel,
    )

    yield multiplexer

    multiplexer.shutdown()
    client.close.set()


@pytest.fixture
async def multiplexer_client(
    test_client: Client,
    crypto_transport: CryptoTransport,
) -> AsyncGenerator[Multiplexer, None]:
    """Create a multiplexer client from server."""

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""

    multiplexer = Multiplexer(
        crypto_transport,
        test_client.reader,
        test_client.writer,
        mock_new_channel,
    )

    yield multiplexer

    multiplexer.shutdown()


@pytest.fixture
async def peer_manager(multiplexer_server: Multiplexer, peer: Peer) -> PeerManager:
    """Create a localhost peer for tests."""
    manager = PeerManager(FERNET_TOKENS)
    manager._peers[peer.hostname] = peer
    return manager


@pytest.fixture
async def sni_proxy(peer_manager: PeerManager) -> AsyncGenerator[SNIProxy, None]:
    """Create a SNI Proxy."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863")
    await proxy.start()

    yield proxy
    await proxy.stop()


@pytest.fixture
async def test_client_ssl(sni_proxy: SNIProxy) -> AsyncGenerator[Client, None]:
    """Create a TCP test client."""
    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    yield Client(reader, writer)

    writer.close()


@pytest.fixture
def crypto_transport() -> CryptoTransport:
    """Create a CryptoTransport object."""
    key = os.urandom(32)
    iv = os.urandom(16)
    crypto = CryptoTransport(key, iv)

    return crypto


@pytest.fixture
async def peer(
    crypto_transport: CryptoTransport,
    multiplexer_server: Multiplexer,
) -> Peer:
    """Init a peer with transport."""
    valid = datetime.now(tz=UTC) + timedelta(days=1)
    peer = Peer("localhost", valid, os.urandom(32), os.urandom(16))
    peer._crypto = crypto_transport
    peer._multiplexer = multiplexer_server

    return peer


@pytest.fixture
async def peer_listener(
    peer_manager: PeerManager,
    peer: Peer,
) -> AsyncGenerator[PeerListener, None]:
    """Create a Peer listener."""
    listener = PeerListener(peer_manager, "127.0.0.1", "8893")
    await listener.start()

    # Cleanup mock peer
    peer_manager.remove_peer(peer)

    yield listener
    await listener.stop()


@pytest.fixture
async def test_client_peer(peer_listener: PeerListener) -> AsyncGenerator[Client, None]:
    """Create a TCP test client."""
    reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8893")

    yield Client(reader, writer)

    writer.close()


@pytest.fixture
def tls_certificate_authority() -> trustme.CA:
    return trustme.CA()


@pytest.fixture
def tls_certificate(tls_certificate_authority: trustme.CA) -> trustme.LeafCert:
    return tls_certificate_authority.issue_cert(
        "localhost",
        "localhost.localdomain",
        "127.0.0.1",
        "::1",
    )


@pytest.fixture
async def server_ssl_context(tls_certificate: trustme.LeafCert) -> ssl.SSLContext:
    """Create a SSL context for the server."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls_certificate.configure_cert(context)
    return context


@pytest.fixture
async def server_ssl_context_missing_cert() -> ssl.SSLContext:
    """Create a SSL context for the server without a certificate."""
    return ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)


@pytest.fixture
async def client_ssl_context(tls_certificate_authority: trustme.CA) -> ssl.SSLContext:
    """Create a SSL context for the client."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_certificate_authority.configure_trust(context)
    return context


@asynccontextmanager
async def make_snitun_client_aiohttp(
    aiohttp_server: AiohttpServer,
    server_ssl_context: ssl.SSLContext,
) -> SniTunClientAioHttp:
    """Create a SniTunClientAioHttp."""
    app = web.Application()
    app.add_routes(
        [
            web.get("/", lambda _: web.Response(text="Hello world")),
            web.get("/large_file", lambda _: web.Response(body=b"X" * 1024 * 1024 * 4)),
        ],
    )
    server = await aiohttp_server(app)
    client = SniTunClientAioHttp(server.runner, server_ssl_context, "127.0.0.1", "4242")
    await client.start(whitelist=True)
    client._connector.whitelist.add(IP_ADDR)
    yield client
    await client.stop()
    await server.close()


@pytest.fixture
async def snitun_client_aiohttp(
    aiohttp_server: AiohttpServer,
    server_ssl_context: ssl.SSLContext,
) -> AsyncGenerator[SniTunClientAioHttp, None]:
    """Create a SniTunClientAioHttp."""
    async with make_snitun_client_aiohttp(aiohttp_server, server_ssl_context) as client:
        yield client


@pytest.fixture
async def snitun_client_aiohttp_missing_certificate(
    aiohttp_server: AiohttpServer,
    server_ssl_context_missing_cert: ssl.SSLContext,
) -> AsyncGenerator[SniTunClientAioHttp, None]:
    """Create a SniTunClientAioHttp with the certificate missing."""
    async with make_snitun_client_aiohttp(
        aiohttp_server,
        server_ssl_context_missing_cert,
    ) as client:
        yield client


@pytest.fixture
async def connector(snitun_client_aiohttp: SniTunClientAioHttp) -> Connector:
    """Create a connector."""
    return snitun_client_aiohttp._connector


@pytest.fixture
async def connector_missing_certificate(
    snitun_client_aiohttp_missing_certificate: SniTunClientAioHttp,
) -> Connector:
    """Create a connector."""
    return snitun_client_aiohttp_missing_certificate._connector
