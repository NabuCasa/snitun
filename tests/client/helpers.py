"""Test client connector."""

import asyncio
import asyncio.sslproto
import ipaddress
import ssl
from typing import TYPE_CHECKING

from aiohttp import ClientConnectorError, ClientRequest, ClientTimeout
from aiohttp.client_proto import ResponseHandler
from aiohttp.connector import BaseConnector

from snitun.exceptions import MultiplexerTransportClose

if TYPE_CHECKING:
    from aiohttp.tracing import Trace

from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.transport import ChannelTransport
from snitun.utils.asyncio import create_eager_task

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
        channel = await self._multiplexer_server.create_channel(self._ip_address, lambda _: None)
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
