"""Test for SSL SNI proxy."""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import struct
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from snitun.exceptions import MultiplexerTransportError
from snitun.multiplexer.core import Multiplexer
from snitun.server.listener_sni import ProxyPeerHandler, SNIProxy
from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager

from ..conftest import Client
from .const_tls import TLS_1_2

_PROXY_V2_SIGNATURE = b"\r\n\r\n\x00\r\nQUIT\n"


def _proxy_v2_tcp4(source: str) -> bytes:
    """Build a v2 PROXY header advertising ``source`` as the client IPv4."""
    block = (
        ipaddress.IPv4Address(source).packed
        + ipaddress.IPv4Address("5.6.7.8").packed
        + struct.pack("!HH", 1111, 443)
    )
    return (
        _PROXY_V2_SIGNATURE
        + bytes([0x21, 0x11])
        + struct.pack("!H", len(block))
        + block
    )


IP_ADDR = ipaddress.ip_address("127.0.0.1")


async def test_proxy_up_down() -> None:
    """Simple start stop of proxy."""
    proxy = SNIProxy({}, "127.0.0.1", "8863")

    await proxy.start()
    await proxy.stop()


@pytest.mark.parametrize(
    "payloads",
    [
        [TLS_1_2],
        [TLS_1_2[:6], TLS_1_2[6:]],
        [TLS_1_2[:6], TLS_1_2[6:20], TLS_1_2[20:]],
        [TLS_1_2[:6], TLS_1_2[6:20], TLS_1_2[20:32], TLS_1_2[32:]],
    ],
)
async def test_sni_proxy_flow(
    multiplexer_client: Multiplexer,
    test_client_ssl: Client,
    payloads: list[bytes],
) -> None:
    """Test a normal flow of connection and exchange data."""
    for payload in payloads:
        test_client_ssl.writer.write(payload)
        await asyncio.sleep(0.1)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == IP_ADDR

    client_hello = await channel.read()
    assert client_hello == TLS_1_2

    test_client_ssl.writer.write(b"Very secret!")
    await test_client_ssl.writer.drain()

    data = await channel.read()
    assert data == b"Very secret!"

    await channel.write(b"my answer")
    data = await test_client_ssl.reader.read(1024)
    assert data == b"my answer"


async def test_sni_proxy_flow_close_by_client(
    multiplexer_client: Multiplexer,
    test_client_ssl: Client,
) -> None:
    """Test a normal flow of connection data and close by client."""
    loop = asyncio.get_running_loop()
    test_client_ssl.writer.write(TLS_1_2)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == IP_ADDR

    client_hello = await channel.read()
    assert client_hello == TLS_1_2

    test_client_ssl.writer.write(b"Very secret!")
    await test_client_ssl.writer.drain()

    data = await channel.read()
    assert data == b"Very secret!"

    ssl_client_read = loop.create_task(test_client_ssl.reader.read(2024))
    await asyncio.sleep(0.1)
    assert not ssl_client_read.done()

    multiplexer_client.delete_channel(channel)
    await asyncio.sleep(0.1)

    assert ssl_client_read.done()


async def test_sni_proxy_flow_close_by_server(
    multiplexer_client: Multiplexer,
    test_client_ssl: Client,
) -> None:
    """Test a normal flow of connection data and close by server."""
    loop = asyncio.get_running_loop()
    test_client_ssl.writer.write(TLS_1_2)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == IP_ADDR

    client_hello = await channel.read()
    assert client_hello == TLS_1_2

    test_client_ssl.writer.write(b"Very secret!")
    await test_client_ssl.writer.drain()

    data = await channel.read()
    assert data == b"Very secret!"

    client_read = loop.create_task(channel.read())
    await asyncio.sleep(0.1)
    assert not client_read.done()

    test_client_ssl.writer.close()
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels
    assert client_read.done()


async def test_sni_proxy_flow_peer_not(
    peer: Peer,
    multiplexer_client: Multiplexer,
    test_client_ssl: Client,
) -> None:
    """Test a normal flow of connection with peer is not ready."""
    peer._multiplexer = None  # Fake peer state

    test_client_ssl.writer.write(TLS_1_2)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels


async def test_sni_proxy_timeout(
    multiplexer_client: Multiplexer,
    test_client_ssl: Client,
    raise_timeout: None,
) -> None:
    """Test a normal flow of connection and exchange data."""
    test_client_ssl.writer.write(TLS_1_2)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels


async def test_sni_proxy_flow_timeout(
    multiplexer_client: Multiplexer,
    test_client_ssl: Client,
) -> None:
    """Test a normal flow of connection and exchange data."""
    from snitun.server import listener_sni

    with (
        patch.object(listener_sni, "PEER_TCP_SESSION_MIN_TIMEOUT", 0.1),
        patch.object(listener_sni, "PEER_TCP_SESSION_MAX_TIMEOUT", 0.2),
    ):
        test_client_ssl.writer.write(TLS_1_2)
        await test_client_ssl.writer.drain()
        await asyncio.sleep(0.1)

        assert multiplexer_client._channels
        channel = next(iter(multiplexer_client._channels.values()))
        assert channel.ip_address == IP_ADDR

        client_hello = await channel.read()
        assert client_hello == TLS_1_2

        test_client_ssl.writer.write(b"Very secret!")
        await test_client_ssl.writer.drain()

        data = await channel.read()
        assert data == b"Very secret!"

        await channel.write(b"my answer")
        data = await test_client_ssl.reader.read(1024)
        assert data == b"my answer"

        await asyncio.sleep(0.3)

    assert not multiplexer_client._channels


async def test_proxy_peer_handler_cancels_timeout_on_close(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """The idle timeout is cancelled once the session ends (no timer leak)."""
    proxy_peer_handler: ProxyPeerHandler | None = None

    def save_proxy_peer_handler(
        ip_address: ipaddress.IPv4Address,
    ) -> ProxyPeerHandler:
        nonlocal proxy_peer_handler
        proxy_peer_handler = ProxyPeerHandler(ip_address)
        return proxy_peer_handler

    with patch("snitun.server.listener_sni.ProxyPeerHandler", save_proxy_peer_handler):
        proxy = SNIProxy(peer_manager, "127.0.0.1", "8863")
        await proxy.start()
        reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")
        test_client_ssl = Client(reader, writer)
        test_client_ssl.writer.write(TLS_1_2)
        await test_client_ssl.writer.drain()
        await asyncio.sleep(0.1)

        assert isinstance(proxy_peer_handler, ProxyPeerHandler)
        handler = cast(ProxyPeerHandler, proxy_peer_handler)
        # While the session is alive the timer is armed.
        assert handler._ranged_timeout._timer is not None

        # Client goes away -> session tears down.
        test_client_ssl.writer.close()
        await asyncio.sleep(0.1)

    assert not multiplexer_client._channels
    # The timer must be cancelled so it cannot fire after the session closed.
    assert handler._ranged_timeout._timer is None
    await proxy.stop()


async def test_proxy_peer_handler_channel_create_fails() -> None:
    """A failed channel creation returns cleanly and arms no idle timeout."""
    multiplexer = MagicMock()
    multiplexer.create_channel = AsyncMock(side_effect=MultiplexerTransportError)

    handler = ProxyPeerHandler(IP_ADDR)
    await handler.start(multiplexer, TLS_1_2, MagicMock(), MagicMock())

    # The timeout is only armed after the channel exists, so the early return
    # must leave no timer behind that could later fire against an unset state.
    assert not hasattr(handler, "_ranged_timeout")


async def test_proxy_peer_handler_can_pause(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """Test proxy peer handler can pause."""
    proxy_peer_handler: ProxyPeerHandler | None = None
    loop = asyncio.get_running_loop()

    def save_proxy_peer_handler(
        ip_address: ipaddress.IPv4Address,
    ) -> ProxyPeerHandler:
        nonlocal proxy_peer_handler
        proxy_peer_handler = ProxyPeerHandler(ip_address)
        return proxy_peer_handler

    with patch("snitun.server.listener_sni.ProxyPeerHandler", save_proxy_peer_handler):
        proxy = SNIProxy(peer_manager, "127.0.0.1", "8863")
        await proxy.start()
        reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")
        test_client_ssl = Client(reader, writer)
        test_client_ssl.writer.write(TLS_1_2)
        await test_client_ssl.writer.drain()
        await asyncio.sleep(0.1)

    assert isinstance(proxy_peer_handler, ProxyPeerHandler)
    handler = cast(ProxyPeerHandler, proxy_peer_handler)
    client_channel = handler._channel
    assert client_channel._pause_resume_reader_callback is not None
    assert (
        client_channel._pause_resume_reader_callback
        == handler._pause_resume_reader_callback
    )

    assert multiplexer_client._channels
    server_channel = next(iter(multiplexer_client._channels.values()))
    assert server_channel.ip_address == IP_ADDR

    client_hello = await server_channel.read()
    assert client_hello == TLS_1_2

    test_client_ssl.writer.write(b"Very secret!")
    await test_client_ssl.writer.drain()

    data = await server_channel.read()
    assert data == b"Very secret!"

    # Now simulate that the remote input is under water
    client_channel.on_remote_input_under_water(True)
    assert handler._pause_future is not None
    assert not handler._pause_future.done()

    # This is an implementation detail that we might
    # change in the future, but for now we need to
    # to read one more message because we don't cancel
    # the current read when the reader pauses as the additional
    # complexity is not worth it.
    test_client_ssl.writer.write(b"one more in before we pause")
    await test_client_ssl.writer.drain()

    data = await server_channel.read()
    assert data == b"one more in before we pause"

    test_client_ssl.writer.write(b"now we are paused")
    await test_client_ssl.writer.drain()

    read_task = loop.create_task(server_channel.read())
    await asyncio.sleep(0.1)
    # Make sure reader is actually paused
    assert not read_task.done()

    # Now simulate that the remote input is no longer under water
    assert handler._pause_future is not None
    assert not handler._pause_future.done()
    client_channel.on_remote_input_under_water(False)
    assert handler._pause_future is None
    data = await read_task
    assert data == b"now we are paused"

    test_client_ssl.writer.close()
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels

    await proxy.stop()


async def test_proxy_peer_os_error_on_write(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test proxy peer handler handles oserror."""
    proxy_peer_handler: ProxyPeerHandler | None = None

    class InstrumentedProxyPeerHandler(ProxyPeerHandler):
        """Instrumented Proxy Peer Handler.

        This class is used to test the ProxyPeerHandler class
        and save the reader and writer for testing.
        """

        writer: asyncio.StreamWriter
        reader: asyncio.StreamReader

        async def start(
            self,
            multiplexer: Multiplexer,
            client_hello: bytes,
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            self.reader = reader
            self.writer = writer
            await super().start(multiplexer, client_hello, reader, writer)

    def save_proxy_peer_handler(
        ip_address: ipaddress.IPv4Address,
    ) -> ProxyPeerHandler:
        nonlocal proxy_peer_handler
        proxy_peer_handler = InstrumentedProxyPeerHandler(ip_address)
        return proxy_peer_handler

    with patch("snitun.server.listener_sni.ProxyPeerHandler", save_proxy_peer_handler):
        proxy = SNIProxy(peer_manager, "127.0.0.1", "8863")
        await proxy.start()
        reader, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")
        test_client_ssl = Client(reader, writer)
        test_client_ssl.writer.write(TLS_1_2)
        await test_client_ssl.writer.drain()
        await asyncio.sleep(0.1)

    assert isinstance(proxy_peer_handler, ProxyPeerHandler)

    assert multiplexer_client._channels
    server_channel = next(iter(multiplexer_client._channels.values()))
    assert server_channel.ip_address == IP_ADDR

    client_hello = await server_channel.read()
    assert client_hello == TLS_1_2

    test_client_ssl.writer.write(b"Very secret!")
    await test_client_ssl.writer.drain()

    data = await server_channel.read()
    assert data == b"Very secret!"

    await server_channel.write(b"from server to ssl client")
    data = await test_client_ssl.reader.read(1024)
    assert data == b"from server to ssl client"

    with patch.object(
        proxy_peer_handler.writer,
        "write",
        side_effect=OSError(errno.EPIPE, "Broken Pipe"),
    ):
        await server_channel.write(b"some data that will trigger oserror")
        await asyncio.sleep(0.1)

    assert not multiplexer_client._channels
    assert "Broken Pipe" in caplog.text
    await proxy.stop()


async def test_proxy_protocol_v1_forwards_source_ip(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """With proxy_protocol enabled, a v1 header's source IP reaches the channel."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    writer.write(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n" + TLS_1_2)
    await writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    # The forwarded source IP is the one from the PROXY header, not 127.0.0.1.
    assert channel.ip_address == ipaddress.IPv4Address("1.2.3.4")
    assert await channel.read() == TLS_1_2

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


async def test_proxy_protocol_v2_forwards_source_ip(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """With proxy_protocol enabled, a v2 header's source IP reaches the channel."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    writer.write(_proxy_v2_tcp4("9.8.7.6") + TLS_1_2)
    await writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == ipaddress.IPv4Address("9.8.7.6")
    assert await channel.read() == TLS_1_2

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


async def test_proxy_protocol_disabled_does_not_strip_header(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """Without proxy_protocol a PROXY header is not trusted (no IP spoofing).

    The header bytes are treated as (invalid) TLS, so the connection is
    rejected and no channel is created.
    """
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863")
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    writer.write(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n" + TLS_1_2)
    await writer.drain()
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


async def test_proxy_protocol_enabled_without_header_uses_peername(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """With proxy_protocol enabled but no header sent, fall back to the peer."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    writer.write(TLS_1_2)
    await writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == IP_ADDR  # socket peername (127.0.0.1)
    assert await channel.read() == TLS_1_2

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


async def test_proxy_peer_aborts_without_source_ip(
    peer_manager: PeerManager,
) -> None:
    """_proxy_peer aborts cleanly when no source IP can be determined."""
    proxy = SNIProxy(peer_manager)
    writer = MagicMock()
    writer.get_extra_info.return_value = None  # peername unavailable
    multiplexer = MagicMock()

    await proxy._proxy_peer(multiplexer, b"hello", MagicMock(), writer)

    # No channel is opened when the source IP cannot be read.
    multiplexer.create_channel.assert_not_called()


async def test_proxy_protocol_v1_then_sni_separate_writes(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """PROXY header first, then the TLS ClientHello: SNI routing still works."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    # Send the PROXY header on its own first.
    writer.write(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n")
    await writer.drain()
    await asyncio.sleep(0.1)
    # Nothing routed yet: the ClientHello (and its SNI) has not arrived.
    assert not multiplexer_client._channels

    # Now the TLS ClientHello (SNI "localhost") follows.
    writer.write(TLS_1_2)
    await writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    # Routed by SNI to the localhost peer, with the PROXY source IP forwarded.
    assert channel.ip_address == ipaddress.IPv4Address("1.2.3.4")
    assert await channel.read() == TLS_1_2

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


async def test_proxy_protocol_v2_then_sni_separate_writes(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """Same as above for a v2 binary header."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    writer.write(_proxy_v2_tcp4("9.8.7.6"))
    await writer.drain()
    await asyncio.sleep(0.1)
    assert not multiplexer_client._channels

    writer.write(TLS_1_2)
    await writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == ipaddress.IPv4Address("9.8.7.6")
    assert await channel.read() == TLS_1_2

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


async def test_proxy_protocol_then_chunked_sni(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """The ClientHello may arrive in several chunks after the PROXY header."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    # Header glued to the first TLS fragment, remainder dribbled in.
    writer.write(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n" + TLS_1_2[:6])
    await writer.drain()
    await asyncio.sleep(0.05)
    writer.write(TLS_1_2[6:30])
    await writer.drain()
    await asyncio.sleep(0.05)
    writer.write(TLS_1_2[30:])
    await writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == ipaddress.IPv4Address("1.2.3.4")
    assert await channel.read() == TLS_1_2

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


async def test_proxy_protocol_then_invalid_tls_rejected(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """A valid PROXY header followed by non-TLS data is rejected (no channel)."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    writer.write(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\nnot-a-tls-hello")
    await writer.drain()
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


def _proxy_v2_tcp6(source: str) -> bytes:
    """Build a v2 PROXY header advertising ``source`` as the client IPv6."""
    block = (
        ipaddress.IPv6Address(source).packed
        + ipaddress.IPv6Address("::1").packed
        + struct.pack("!HH", 1111, 443)
    )
    return (
        _PROXY_V2_SIGNATURE + bytes([0x21, 0x21]) + struct.pack("!H", len(block)) + block
    )


async def test_proxy_protocol_v1_forwards_ipv6_source(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """A v1 TCP6 header's IPv6 source is carried end-to-end to the channel."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    writer.write(b"PROXY TCP6 2001:db8::dead 2001:db8::1 1111 443\r\n" + TLS_1_2)
    await writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == ipaddress.IPv6Address("2001:db8::dead")
    assert await channel.read() == TLS_1_2

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()


async def test_proxy_protocol_v2_forwards_ipv6_source(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """A v2 INET6 header's IPv6 source is carried end-to-end to the channel."""
    proxy = SNIProxy(peer_manager, "127.0.0.1", "8863", proxy_protocol=True)
    await proxy.start()
    _, writer = await asyncio.open_connection(host="127.0.0.1", port="8863")

    writer.write(_proxy_v2_tcp6("2001:db8::beef") + TLS_1_2)
    await writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))
    assert channel.ip_address == ipaddress.IPv6Address("2001:db8::beef")
    assert await channel.read() == TLS_1_2

    writer.close()
    await asyncio.sleep(0.1)
    await proxy.stop()
