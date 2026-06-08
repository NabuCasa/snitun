"""Test helpers that simulate a browser connecting through the cloud.

In production, a browser connects to the NabuCasa cloud which forwards
the connection through the multiplexer to the Home Assistant instance.
These helpers simulate the browser/cloud side of that connection for
end-to-end testing:

    Browser (ChannelConnector)
        |
    SSLProtocol (client-side TLS)
        |
    ChannelTransport
        |
    MultiplexerChannel  ---multiplexer--->  MultiplexerChannel
                                                |
                                            ChannelTransport
                                                |
                                            SSLProtocol (server-side TLS)
                                                |
                                            aiohttp RequestHandler
"""

import asyncio
import asyncio.sslproto
import ipaddress
import logging
import ssl
from typing import TYPE_CHECKING

from aiohttp import ClientConnectorError, ClientRequest, ClientTimeout
from aiohttp.client_proto import ResponseHandler
from aiohttp.connector import BaseConnector

from snitun.exceptions import MultiplexerTransportClose
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.transport import ChannelTransport

from ..conftest import IP_ADDR

if TYPE_CHECKING:
    from aiohttp.tracing import Trace


_LOGGER = logging.getLogger(__name__)


class ResponseHandlerWithTransportReader(ResponseHandler):
    """aiohttp ResponseHandler that aborts the SSL transport on close.

    In production, when a browser disconnects the TCP socket simply drops
    and the cloud multiplexer sends a CLOSE message — there is no clean
    SSL shutdown. This subclass simulates that behavior by calling
    transport.abort() before the normal close, which sets the SSLProtocol
    state to _UNWRAPPED and skips the SSL shutdown handshake.
    """

    def __init__(
        self,
        channel_transport: ChannelTransport,
    ) -> None:
        """Initialize response handler."""
        super().__init__(loop=asyncio.get_running_loop())
        self._channel_transport = channel_transport

    def close(self) -> None:
        """Close connection.

        Abort the SSL transport to skip SSL shutdown. In production,
        the TCP connection drops without SSL shutdown and the cloud
        multiplexer sends a CLOSE message. Aborting simulates this.

        After abort, super().close() handles ResponseHandler cleanup.
        The SSL shutdown is skipped because abort sets the SSL protocol
        state to _UNWRAPPED.
        """
        transport = self.transport
        if transport is not None:
            transport.abort()
        super().close()


class ChannelConnector(BaseConnector):
    """aiohttp connector that routes requests through a multiplexer channel.

    Simulates the browser/cloud side of a snitun connection. Instead of
    opening a TCP socket, _create_connection() creates a MultiplexerChannel,
    wraps it in a ChannelTransport, performs client-side TLS via start_tls(),
    and returns an aiohttp ResponseHandler wired to the TLS transport.

    This is the mirror image of what ConnectorHandler does on the Home
    Assistant side (server-side TLS), allowing full end-to-end tests
    through the multiplexer without any real network sockets.
    """

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
