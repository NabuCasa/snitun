"""Pytest fixtures for SniTun."""

import asyncio
import asyncio.sslproto
from asyncio.streams import StreamReader
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import ipaddress
import logging
import os
import select
import socket
import ssl
from threading import Thread
from typing import Any, cast
from unittest.mock import patch

from aiohttp import web
import pytest
from pytest_aiohttp import AiohttpServer
import trustme

from snitun.client.connector import Connector, ConnectorHandler
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.crypto import CryptoTransport
from snitun.multiplexer.transport import ChannelTransport
from snitun.server.listener_peer import PeerListener
from snitun.server.listener_sni import SNIProxy
from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager
from snitun.utils.aiohttp_client import SniTunClientAioHttp
from snitun.utils.asyncio import asyncio_timeout

from .server.const_fernet import FERNET_TOKENS

_LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.DEBUG)


IP_ADDR = ipaddress.ip_address("8.8.8.8")
BAD_ADDR = ipaddress.ip_address("8.8.1.1")


@dataclass
class Client:
    """Represent a TCP client object."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    close: asyncio.Event = field(default_factory=asyncio.Event)


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


class BufferedStreamReaderProtocol(asyncio.StreamReaderProtocol):
    """Buffered stream reader protocol."""

    writer: asyncio.StreamWriter
    reader: asyncio.StreamReader

    def __init__(
        self,
        stream_reader: asyncio.StreamReader,
        loop: asyncio.AbstractEventLoop,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        """Initialize buffered stream reader protocol."""
        self.reader = stream_reader
        self.loop = loop
        super().__init__(stream_reader, loop=loop, **kwargs)

    def connection_made(self, transport: asyncio.Transport) -> None:
        """Handle connection made."""
        _LOGGER.debug("BufferedStreamReaderProtocol.connection_made: %s", transport)
        self.writer = asyncio.StreamWriter(transport, self, self.reader, self.loop)
        self.transport = transport

    def data_received(self, data: bytes) -> None:
        """Handle data received."""
        _LOGGER.debug("BufferedStreamReaderProtocol.data_received: %s", data)
        super().data_received(data)

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle Connection lost."""
        _LOGGER.debug("BufferedStreamReaderProtocol.connection_lost: %s", exc)
        super().connection_lost(exc)


@dataclass
class _ConnectorWithStreams:
    """Connector with streams."""

    connections: list[BufferedStreamReaderProtocol]
    connector: Connector


def make_snitun_connector(
    ssl_context: ssl.SSLContext,
    whitelist: bool = False,
) -> _ConnectorWithStreams:
    """Make connector."""
    connections: list[BufferedStreamReaderProtocol] = []
    loop = asyncio.get_running_loop()

    def protocol_factory() -> BufferedStreamReaderProtocol:
        reader = StreamReader(loop=loop)
        protocol = BufferedStreamReaderProtocol(reader, loop=loop)
        connections.append(protocol)
        return protocol

    return _ConnectorWithStreams(
        connections,
        Connector(
            protocol_factory=protocol_factory,
            ssl_context=ssl_context,
            whitelist=whitelist,
        ),
    )


@dataclass
class TLSWrappedTransport:
    """TLS wrapped transport."""

    channel: MultiplexerChannel
    protocol: BufferedStreamReaderProtocol
    transport: ChannelTransport


@dataclass
class SNITunLoopback:
    """Server Transport wrapper."""

    client: TLSWrappedTransport
    server: TLSWrappedTransport


@pytest.fixture
async def snitun_loopback(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    client_ssl_context: ssl.SSLContext,
    server_ssl_context: ssl.SSLContext,
) -> SNITunLoopback:
    """Make a snitun end to end loopback."""
    connector_with_streams = make_snitun_connector(server_ssl_context, whitelist=False)
    connector = connector_with_streams.connector
    multiplexer_client._new_connections = connector.handler  # noqa: SLF001
    connector_handler: ConnectorHandler | None = None

    def save_connector_handler(
        loop: asyncio.AbstractEventLoop,
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
        transport: ChannelTransport,
    ) -> ConnectorHandler:
        nonlocal connector_handler
        connector_handler = ConnectorHandler(loop, multiplexer, channel, transport)
        return connector_handler

    loop = asyncio.get_running_loop()

    with patch("snitun.client.connector.ConnectorHandler", save_connector_handler):
        server_channel = await multiplexer_server.create_channel(
            IP_ADDR,
            lambda _: None,
        )
        server_transport = ChannelTransport(server_channel, multiplexer_server)
        server_transport.start_reader()
        server_reader = asyncio.StreamReader(loop=loop)
        server_protocol = BufferedStreamReaderProtocol(server_reader, loop=loop)
        tls_wrapped_server_transport = await loop.start_tls(
            server_transport,
            server_protocol,
            client_ssl_context,
            server_side=False,
        )
        assert tls_wrapped_server_transport is not None, "Failed to start TLS"
        server_protocol.connection_made(tls_wrapped_server_transport)

    assert isinstance(connector_handler, ConnectorHandler)
    handler = cast(ConnectorHandler, connector_handler)
    client_channel = handler._channel  # noqa: SLF001
    assert client_channel._pause_resume_reader_callback is not None  # noqa: SLF001
    assert (
        client_channel._pause_resume_reader_callback  # noqa: SLF001
        == handler._pause_resume_reader_callback  # noqa: SLF001
    )

    assert connector_with_streams.connections
    assert len(connector_with_streams.connections) == 1
    client_protocol = connector_with_streams.connections[0]
    client_transport = handler._transport  # noqa: SLF001
    await asyncio.sleep(0.1)
    assert client_protocol.writer
    assert server_protocol.writer
    assert isinstance(server_transport.get_protocol(), asyncio.sslproto.SSLProtocol)
    assert isinstance(client_transport.get_protocol(), asyncio.sslproto.SSLProtocol)

    return SNITunLoopback(
        client=TLSWrappedTransport(client_channel, client_protocol, client_transport),
        server=TLSWrappedTransport(server_channel, server_protocol, server_transport),
    )
