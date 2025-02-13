"""Test client connector."""

import asyncio
import asyncio.sslproto
from asyncio.streams import StreamReader
from dataclasses import dataclass
import ipaddress
import ssl
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

from aiohttp import ClientConnectorError, ClientRequest, ClientTimeout
from aiohttp.client_proto import ResponseHandler
from aiohttp.connector import BaseConnector

from snitun.client.connector import Connector, ConnectorHandler
from snitun.exceptions import MultiplexerTransportClose
from snitun.multiplexer.channel import MultiplexerChannel

if TYPE_CHECKING:
    from aiohttp.tracing import Trace

import logging

from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.transport import ChannelTransport
from snitun.utils.asyncio import create_eager_task

_LOGGER = logging.getLogger(__name__)
from ..conftest import IP_ADDR


class ResponseHandlerWithTransportReader(ResponseHandler):
    """Response handler with transport reader."""

    def __init__(
        self,
        channel_transport: ChannelTransport,
    ) -> None:
        """Initialize response handler."""
        super().__init__(loop=asyncio.get_running_loop())
        self._channel_transport = channel_transport

    def close(self) -> None:
        """Close connection."""
        super().close()
        create_eager_task(self._channel_transport.stop_reader(), loop=self._loop)
        self._channel_transport.close()


class ChannelConnector(BaseConnector):
    """Channel connector."""

    def __init__(
        self,
        multiplexer_server: Multiplexer,
        ssl_context: ssl.SSLContext,
        ip_address: ipaddress.IPv4Address = IP_ADDR,
    ) -> None:
        """Initialize connector."""
        super().__init__()
        self._multiplexer_server = multiplexer_server
        self._ssl_context = ssl_context
        self._ip_address = ip_address

    async def _create_connection(
        self,
        req: ClientRequest,
        traces: list["Trace"],
        timeout: "ClientTimeout",
    ) -> ResponseHandler:
        """Create connection."""
        channel = await self._multiplexer_server.create_channel(
            self._ip_address,
            lambda _: None,
        )
        transport = ChannelTransport(channel, self._multiplexer_server)
        transport.start_reader()
        protocol = ResponseHandlerWithTransportReader(channel_transport=transport)
        try:
            new_transport = await self._loop.start_tls(
                transport,
                protocol,
                self._ssl_context,
                server_side=False,
            )
        except MultiplexerTransportClose as ex:
            raise ClientConnectorError(
                req.connection_key,
                OSError(None, "Connection closed by remote host"),
            ) from ex
        if not new_transport:
            raise ClientConnectorError(
                req.connection_key,
                OSError(None, "Connection aborted by remote host"),
            )
        protocol.connection_made(new_transport)
        return protocol


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
class SNITunWrapper:
    """Server Transport wrapper."""

    client: TLSWrappedTransport
    server: TLSWrappedTransport


async def make_snitun_server_transport(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    client_ssl_context: ssl.SSLContext,
    server_ssl_context: ssl.SSLContext,
) -> SNITunWrapper:
    """Make snitun server transport."""
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

    return SNITunWrapper(
        client=TLSWrappedTransport(client_channel, client_protocol, client_transport),
        server=TLSWrappedTransport(server_channel, server_protocol, server_transport),
    )
