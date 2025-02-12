"""Test for SSL SNI proxy."""

from __future__ import annotations

import asyncio
import ipaddress
from typing import cast
from unittest.mock import patch

import pytest

from snitun.multiplexer.core import Multiplexer
from snitun.server.listener_sni import ProxyPeerHandler, SNIProxy
from snitun.server.peer import Peer
from snitun.server.peer_manager import PeerManager

from ..conftest import Client
from .const_tls import TLS_1_2

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
    event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Test a normal flow of connection data and close by client."""
    loop = event_loop
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

    await multiplexer_client.delete_channel(channel)
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

    listener_sni.TCP_SESSION_TIMEOUT = 0.2

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


async def test_proxy_peer_handler_can_pause(
    multiplexer_client: Multiplexer,
    peer_manager: PeerManager,
) -> None:
    """Test proxy peer handler can pause."""
    proxy_peer_handler: ProxyPeerHandler | None = None
    loop = asyncio.get_running_loop()

    def save_proxy_peer_handler(
        loop: asyncio.AbstractEventLoop,
        ip_address: ipaddress.IPv4Address,
    ) -> ProxyPeerHandler:
        nonlocal proxy_peer_handler
        proxy_peer_handler = ProxyPeerHandler(loop, ip_address)
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
