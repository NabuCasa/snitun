"""Test for SSL SNI proxy."""
import asyncio

from snitun.server.listener_sni import SNIProxy

from .const_tls import TLS_1_2


async def test_proxy_up_down():
    """Simple start stop of proxy."""
    proxy = SNIProxy({}, "127.0.0.1", "8863")

    await proxy.start()
    await proxy.stop()


async def test_sni_proxy_flow(multiplexer_client, test_client_ssl):
    """Test a normal flow of connection and exchange data."""
    test_client_ssl.writer.write(TLS_1_2)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))

    client_hello = await channel.read()
    client_hello == TLS_1_2

    test_client_ssl.writer.write(b"Very secret!")
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    data = await channel.read()
    assert data == b"Very secret!"

    await channel.write(b"my answer")
    await asyncio.sleep(0.1)

    data = await test_client_ssl.reader.read(1024)
    assert data == b"my answer"
