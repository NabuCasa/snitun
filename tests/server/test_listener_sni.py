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
    assert client_hello == TLS_1_2

    test_client_ssl.writer.write(b"Very secret!")
    await test_client_ssl.writer.drain()

    data = await channel.read()
    assert data == b"Very secret!"

    await channel.write(b"my answer")
    data = await test_client_ssl.reader.read(1024)
    assert data == b"my answer"


async def test_sni_proxy_flow_close_by_client(multiplexer_client,
                                              test_client_ssl, loop):
    """Test a normal flow of connection data and close by client."""
    test_client_ssl.writer.write(TLS_1_2)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))

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


async def test_sni_proxy_flow_close_by_server(multiplexer_client,
                                              test_client_ssl, loop):
    """Test a normal flow of connection data and close by server."""
    test_client_ssl.writer.write(TLS_1_2)
    await test_client_ssl.writer.drain()
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    channel = next(iter(multiplexer_client._channels.values()))

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
