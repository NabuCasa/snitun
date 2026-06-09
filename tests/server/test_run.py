"""Test runner of SniTun Server."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import ipaddress
import os
import socket
import struct
import time
from unittest.mock import MagicMock, patch

import pytest

import snitun
from snitun.exceptions import ParseProxyProtocolError
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.crypto import CBCCryptoTransport
from snitun.server.run import (
    Connection,
    SniTunServer,
    SniTunServerSingle,
    SniTunServerWorker,
    create_listen_sockets,
)

from .const_fernet import FERNET_TOKENS, create_peer_config
from .const_tls import TLS_1_2

IP_ADDR = ipaddress.ip_address("127.0.0.1")


def _ipv6_loopback_available() -> bool:
    """Return True if we can bind the IPv6 loopback."""
    if not socket.has_ipv6:
        return False
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        sock.bind(("::1", 0))
    except OSError:
        return False
    finally:
        sock.close()
    return True


skip_without_ipv6 = pytest.mark.skipif(
    not _ipv6_loopback_available(),
    reason="IPv6 loopback not available",
)


async def test_snitun_runner_updown() -> None:
    """Test SniTun Server runner object."""
    server = SniTunServer(
        FERNET_TOKENS,
        peer_host="127.0.0.1",
        sni_host="127.0.0.1",
        sni_port=32000,
    )

    await server.start()

    await asyncio.sleep(0.1)

    await server.stop()


async def test_snitun_single_runner_updown() -> None:
    """Test SniTun Single Server runner object."""
    server = SniTunServerSingle(FERNET_TOKENS, host="127.0.0.1", port=32000)

    await server.start()

    await asyncio.sleep(0.1)

    await server.stop()


def test_snitun_worker_runner_accept_exception(
    caplog: pytest.LogCaptureFixture,
    event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Test SniTunWorker Server handles accept() exception."""
    server = SniTunServerWorker(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32003,
        worker_size=2,
    )

    server.start()
    with patch("socket.socket.accept", side_effect=OSError("BOOM!")):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", 32003))
        sock.close()

        time.sleep(0.1)

    assert "Accept failed: BOOM!" in caplog.text
    server.stop()


def test_snitun_worker_runner_updown(event_loop: asyncio.AbstractEventLoop) -> None:
    """Test SniTun Worker Server runner object."""
    server = SniTunServerWorker(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32001,
        worker_size=2,
    )

    server.start()

    time.sleep(0.1)

    server.stop()


async def test_snitun_single_runner() -> None:
    """Test SniTunSingle Server runner object."""
    peer_messages = []
    peer_address = []

    server = SniTunServerSingle(FERNET_TOKENS, host="127.0.0.1", port=32000)
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1",
        port="32000",
    )

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    crypto = CBCCryptoTransport(aes_key, aes_iv)

    writer_peer.write(fernet_token)
    await writer_peer.drain()

    token = await reader_peer.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    writer_peer.write(crypto.encrypt(token))

    await writer_peer.drain()
    await asyncio.sleep(0.1)

    assert server.peers.peer_available(hostname)

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""
        while True:
            message = await channel.read()
            peer_messages.append(message)
            peer_address.append(channel.ip_address)

    _, writer_ssl = await asyncio.open_connection(host="127.0.0.1", port="32000")

    multiplexer = Multiplexer(
        crypto,
        reader_peer,
        writer_peer,
        snitun.PROTOCOL_VERSION,
        mock_new_channel,
    )

    writer_ssl.write(TLS_1_2)
    await writer_ssl.drain()
    await asyncio.sleep(0.1)

    assert peer_messages
    assert peer_messages[0] == TLS_1_2
    assert peer_address
    assert peer_address[0] == IP_ADDR

    multiplexer.shutdown()
    await multiplexer.wait()
    await asyncio.sleep(0.1)

    assert not server.peers.peer_available(hostname)

    writer_ssl.close()
    await server.stop()


async def test_snitun_single_runner_timeout(raise_timeout: None) -> None:
    """Test SniTunSingle Server runner object."""
    server = SniTunServerSingle(FERNET_TOKENS, host="127.0.0.1", port="32000")
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1",
        port="32000",
    )

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    crypto = CBCCryptoTransport(aes_key, aes_iv)

    writer_peer.write(fernet_token)
    await writer_peer.drain()

    with pytest.raises(ConnectionResetError):
        token = await reader_peer.readexactly(32)
        token = hashlib.sha256(crypto.decrypt(token)).digest()
        writer_peer.write(crypto.encrypt(token))

        await writer_peer.drain()
        await asyncio.sleep(0.1)

    assert not server.peers.peer_available(hostname)

    await server.stop()


async def test_snitun_single_runner_invalid_payload(raise_timeout: None) -> None:
    """Test SniTunSingle Server runner object with invalid payload."""
    server = SniTunServerSingle(FERNET_TOKENS, host="127.0.0.1", port="32000")
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1",
        port="32000",
    )

    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"

    crypto = CBCCryptoTransport(aes_key, aes_iv)

    writer_peer.write(b"INVALID")
    await writer_peer.drain()

    with pytest.raises(ConnectionResetError):
        token = await reader_peer.readexactly(32)
        token = hashlib.sha256(crypto.decrypt(token)).digest()
        writer_peer.write(crypto.encrypt(token))

        await writer_peer.drain()
        await asyncio.sleep(0.1)

    assert not server.peers.peer_available(hostname)

    await server.stop()


async def test_snitun_single_runner_throttling() -> None:
    """Test SniTunSingle Server runner object."""
    peer_messages = []
    peer_address = []

    server = SniTunServerSingle(
        FERNET_TOKENS,
        host="127.0.0.1",
        port="32000",
        throttling=500,
    )
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1",
        port="32000",
    )

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    crypto = CBCCryptoTransport(aes_key, aes_iv)

    writer_peer.write(fernet_token)
    await writer_peer.drain()

    token = await reader_peer.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    writer_peer.write(crypto.encrypt(token))

    await writer_peer.drain()
    await asyncio.sleep(0.1)

    assert server.peers.peer_available(hostname)

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""
        while True:
            message = await channel.read()
            peer_messages.append(message)
            peer_address.append(channel.ip_address)

    _, writer_ssl = await asyncio.open_connection(host="127.0.0.1", port="32000")

    multiplexer = Multiplexer(
        crypto,
        reader_peer,
        writer_peer,
        snitun.PROTOCOL_VERSION,
        mock_new_channel,
    )

    writer_ssl.write(TLS_1_2)
    await writer_ssl.drain()
    await asyncio.sleep(0.1)

    assert peer_messages
    assert peer_messages[0] == TLS_1_2
    assert peer_address
    assert peer_address[0] == IP_ADDR

    peer = server.peers.get_peer(hostname)
    assert peer._multiplexer._throttling == 0.002

    multiplexer.shutdown()
    await multiplexer.wait()
    await asyncio.sleep(0.1)

    assert not server.peers.peer_available(hostname)

    writer_ssl.close()
    await server.stop()


@pytest.mark.parametrize(
    "payloads",
    [
        [TLS_1_2],
        [TLS_1_2[:6], TLS_1_2[6:]],
        [TLS_1_2[:6], TLS_1_2[6:20], TLS_1_2[20:]],
        [TLS_1_2[:6], TLS_1_2[6:20], TLS_1_2[20:32], TLS_1_2[32:]],
    ],
)
def test_snitun_worker_runner(
    event_loop: asyncio.AbstractEventLoop,
    payloads: list[bytes],
) -> None:
    """Test SniTunWorker Server runner object."""
    loop = event_loop
    peer_messages = []
    peer_address = []

    server = SniTunServerWorker(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32001,
        worker_size=2,
    )
    server.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 32001))

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    crypto = CBCCryptoTransport(aes_key, aes_iv)

    sock.sendall(fernet_token)

    token = sock.recv(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    sock.sendall(crypto.encrypt(token))

    time.sleep(1)
    assert any(worker.is_responsible_peer(hostname) for worker in server._workers)
    assert server.peer_counter == 1

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""
        while True:
            message = await channel.read()
            peer_messages.append(message)
            peer_address.append(channel.ip_address)

    sock_ssl = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock_ssl.connect(("127.0.0.1", 32001))

    async def _create_multiplexer() -> Multiplexer:
        """Create and return the peer multiplexer."""
        reader_peer, writer_peer = await asyncio.open_connection(sock=sock)
        return Multiplexer(
            crypto,
            reader_peer,
            writer_peer,
            snitun.PROTOCOL_VERSION,
            mock_new_channel,
        )

    multiplexer = loop.run_until_complete(_create_multiplexer())

    for payload in payloads:
        sock_ssl.sendall(payload)
        loop.run_until_complete(asyncio.sleep(0.1))

    assert peer_messages
    assert peer_messages[0] == TLS_1_2
    assert peer_address
    assert peer_address[0] == IP_ADDR

    loop.call_soon_threadsafe(multiplexer.shutdown)

    async def _wait_for_shutdown() -> None:
        """Wait for shutdown."""
        waiter = multiplexer.wait()
        await waiter

    loop.run_until_complete(_wait_for_shutdown())
    time.sleep(1)

    assert not any(worker.is_responsible_peer(hostname) for worker in server._workers)

    sock_ssl.close()
    server.stop()


def test_snitun_worker_timeout(event_loop: asyncio.AbstractEventLoop) -> None:
    """Test SniTunWorker Server runner object timeout."""
    from snitun.server import run

    run.WORKER_STALE_MAX = 1
    server = SniTunServerWorker(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32001,
        worker_size=2,
    )

    server.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 32001))

    time.sleep(1.5)

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)
    crypto = CBCCryptoTransport(aes_key, aes_iv)

    with pytest.raises(OSError):
        sock.sendall(fernet_token)

        token = sock.recv(32)
        token = hashlib.sha256(crypto.decrypt(token)).digest()
        sock.sendall(crypto.encrypt(token))

    server.stop()


def test_snitun_worker_runner_invalid_payload(
    event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Test SniTunWorker Server runner invalid payload."""
    server = SniTunServerWorker(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32001,
        worker_size=2,
    )
    server.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 32001))

    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    crypto = CBCCryptoTransport(aes_key, aes_iv)

    sock.sendall(b"INVALID")

    with pytest.raises(OSError):
        for _ in range(3):
            token = sock.recv(32)
            token = hashlib.sha256(crypto.decrypt(token)).digest()
            sock.sendall(crypto.encrypt(token))

    server.stop()


@patch("snitun.server.run.os.kill")
def test_snitun_worker_crash(
    kill: MagicMock,
    event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Test SniTunWorker Server runner object with crashing worker."""
    server = SniTunServerWorker(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32001,
        worker_size=2,
    )

    server.start()

    for worker in server._workers:
        worker.shutdown()
        break

    time.sleep(1.5)

    assert kill.called

    server.stop()


_PROXY_V1 = b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n"


async def test_single_strip_proxy_protocol_v1() -> None:
    """SniTunServerSingle strips a v1 header and returns the source IP."""
    server = SniTunServerSingle(FERNET_TOKENS, proxy_protocol=True)
    reader = asyncio.StreamReader()
    payload, source = await server._strip_proxy_protocol(reader, _PROXY_V1 + TLS_1_2)
    assert payload == TLS_1_2
    assert source == ipaddress.IPv4Address("1.2.3.4")


async def test_single_strip_proxy_protocol_split_reads() -> None:
    """A header split across reads is reassembled."""
    server = SniTunServerSingle(FERNET_TOKENS, proxy_protocol=True)
    reader = asyncio.StreamReader()
    reader.feed_data(b" 5.6.7.8 1111 443\r\n" + TLS_1_2)
    payload, source = await server._strip_proxy_protocol(reader, b"PROXY TCP4 1.2.3.4")
    assert payload == TLS_1_2
    assert source == ipaddress.IPv4Address("1.2.3.4")


async def test_single_strip_proxy_protocol_payload_after_header() -> None:
    """When the header consumes the read, the payload is fetched separately."""
    server = SniTunServerSingle(FERNET_TOKENS, proxy_protocol=True)
    reader = asyncio.StreamReader()
    reader.feed_data(TLS_1_2)
    payload, source = await server._strip_proxy_protocol(reader, _PROXY_V1)
    assert payload == TLS_1_2
    assert source == ipaddress.IPv4Address("1.2.3.4")


async def test_single_strip_proxy_protocol_no_header() -> None:
    """Without a header the payload is returned unchanged and no source IP."""
    server = SniTunServerSingle(FERNET_TOKENS, proxy_protocol=True)
    reader = asyncio.StreamReader()
    payload, source = await server._strip_proxy_protocol(reader, TLS_1_2)
    assert payload == TLS_1_2
    assert source is None


async def test_single_strip_proxy_protocol_v6() -> None:
    """An IPv6 source from a v1 header is parsed and returned."""
    server = SniTunServerSingle(FERNET_TOKENS, proxy_protocol=True)
    reader = asyncio.StreamReader()
    header = b"PROXY TCP6 2001:db8::1 2001:db8::2 1111 443\r\n"
    payload, source = await server._strip_proxy_protocol(reader, header + TLS_1_2)
    assert payload == TLS_1_2
    assert source == ipaddress.IPv6Address("2001:db8::1")


def test_worker_strip_proxy_protocol_v1() -> None:
    """SniTunServerWorker strips a v1 header and records the source IP."""
    server = SniTunServerWorker(FERNET_TOKENS, proxy_protocol=True)
    client = Connection(MagicMock(), MagicMock(), buffer=_PROXY_V1 + TLS_1_2)

    assert server._strip_proxy_protocol(client) is True
    assert client.proxy_done
    assert client.buffer == TLS_1_2
    assert client.peer_address == ipaddress.IPv4Address("1.2.3.4")


def test_worker_strip_proxy_protocol_disabled() -> None:
    """A disabled worker never strips or trusts a PROXY header."""
    server = SniTunServerWorker(FERNET_TOKENS)
    client = Connection(MagicMock(), MagicMock(), buffer=_PROXY_V1 + TLS_1_2)

    assert server._strip_proxy_protocol(client) is True
    assert client.buffer.startswith(b"PROXY")
    assert client.peer_address is None


def test_worker_strip_proxy_protocol_incomplete() -> None:
    """An incomplete header makes the worker wait for more data."""
    server = SniTunServerWorker(FERNET_TOKENS, proxy_protocol=True)
    client = Connection(MagicMock(), MagicMock(), buffer=b"PROXY TCP4 1.2.3.4")

    assert server._strip_proxy_protocol(client) is False
    assert not client.proxy_done


def test_worker_strip_proxy_protocol_malformed_closes() -> None:
    """A malformed header closes the connection."""
    server = SniTunServerWorker(FERNET_TOKENS, proxy_protocol=True)
    epoll = MagicMock()
    client = Connection(MagicMock(), epoll, buffer=b"PROXY TCP4 invalid\r\n" + TLS_1_2)

    assert server._strip_proxy_protocol(client) is False
    assert client.close
    epoll.unregister.assert_called_once()


async def test_snitun_single_runner_proxy_protocol() -> None:
    """End-to-end: a PROXY header's source IP is forwarded to the peer."""
    peer_address: list[ipaddress.IPv4Address] = []

    server = SniTunServerSingle(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32000,
        proxy_protocol=True,
    )
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1",
        port="32000",
    )

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)
    crypto = CBCCryptoTransport(aes_key, aes_iv)

    writer_peer.write(fernet_token)
    await writer_peer.drain()
    token = await reader_peer.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    writer_peer.write(crypto.encrypt(token))
    await writer_peer.drain()
    await asyncio.sleep(0.1)

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""
        while True:
            await channel.read()
            peer_address.append(channel.ip_address)

    _, writer_ssl = await asyncio.open_connection(host="127.0.0.1", port="32000")
    multiplexer = Multiplexer(
        crypto,
        reader_peer,
        writer_peer,
        snitun.PROTOCOL_VERSION,
        mock_new_channel,
    )

    writer_ssl.write(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n" + TLS_1_2)
    await writer_ssl.drain()
    await asyncio.sleep(0.1)

    assert peer_address
    assert peer_address[0] == ipaddress.IPv4Address("1.2.3.4")

    multiplexer.shutdown()
    await multiplexer.wait()
    writer_ssl.close()
    await server.stop()


_PROXY_V2_SIGNATURE = b"\r\n\r\n\x00\r\nQUIT\n"


async def test_single_strip_proxy_protocol_closed_connection() -> None:
    """A connection closing mid PROXY header is rejected."""
    server = SniTunServerSingle(FERNET_TOKENS, proxy_protocol=True)
    reader = asyncio.StreamReader()
    reader.feed_eof()
    with pytest.raises(ParseProxyProtocolError):
        await server._strip_proxy_protocol(reader, b"PROXY TCP4 1.2.3.4")


def test_worker_strip_proxy_protocol_no_header() -> None:
    """An enabled worker leaves a non-PROXY buffer untouched."""
    server = SniTunServerWorker(FERNET_TOKENS, proxy_protocol=True)
    client = Connection(MagicMock(), MagicMock(), buffer=TLS_1_2)

    assert server._strip_proxy_protocol(client) is True
    assert client.proxy_done
    assert client.buffer == TLS_1_2
    assert client.peer_address is None


def test_worker_strip_proxy_protocol_unknown_source() -> None:
    """A header without an address is stripped but yields no source IP."""
    server = SniTunServerWorker(FERNET_TOKENS, proxy_protocol=True)
    client = Connection(MagicMock(), MagicMock(), buffer=b"PROXY UNKNOWN\r\n" + TLS_1_2)

    assert server._strip_proxy_protocol(client) is True
    assert client.buffer == TLS_1_2
    assert client.peer_address is None


def test_worker_strip_proxy_protocol_oversize_closes() -> None:
    """An over-long incomplete header closes the connection."""
    server = SniTunServerWorker(FERNET_TOKENS, proxy_protocol=True)
    epoll = MagicMock()
    # v2 header advertising an address block that never arrives.
    buffer = (
        _PROXY_V2_SIGNATURE
        + bytes([0x21, 0x11])
        + struct.pack("!H", 0xFFFF)
        + b"\x00" * 200
    )
    client = Connection(MagicMock(), epoll, buffer=buffer)

    with patch("snitun.server.run.MAX_BUFFER_SIZE", 64):
        assert server._strip_proxy_protocol(client) is False
    assert client.close
    epoll.unregister.assert_called_once()


async def test_snitun_single_runner_proxy_protocol_separate_writes() -> None:
    """End-to-end Single server: PROXY header then a separate TLS ClientHello."""
    peer_address: list[ipaddress.IPv4Address] = []

    server = SniTunServerSingle(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32000,
        proxy_protocol=True,
    )
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1",
        port="32000",
    )

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)
    crypto = CBCCryptoTransport(aes_key, aes_iv)

    writer_peer.write(fernet_token)
    await writer_peer.drain()
    token = await reader_peer.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    writer_peer.write(crypto.encrypt(token))
    await writer_peer.drain()
    await asyncio.sleep(0.1)

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""
        while True:
            await channel.read()
            peer_address.append(channel.ip_address)

    _, writer_ssl = await asyncio.open_connection(host="127.0.0.1", port="32000")
    multiplexer = Multiplexer(
        crypto,
        reader_peer,
        writer_peer,
        snitun.PROTOCOL_VERSION,
        mock_new_channel,
    )

    # PROXY header first, then the TLS ClientHello as a separate write.
    writer_ssl.write(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n")
    await writer_ssl.drain()
    await asyncio.sleep(0.1)
    writer_ssl.write(TLS_1_2)
    await writer_ssl.drain()
    await asyncio.sleep(0.1)

    assert peer_address
    assert peer_address[0] == ipaddress.IPv4Address("1.2.3.4")

    multiplexer.shutdown()
    await multiplexer.wait()
    writer_ssl.close()
    await server.stop()


async def test_snitun_single_runner_proxy_protocol_fragmented_hello() -> None:
    """Single server completes a ClientHello fragmented after the PROXY header."""
    peer_address: list[ipaddress.IPv4Address] = []

    server = SniTunServerSingle(
        FERNET_TOKENS,
        host="127.0.0.1",
        port=32000,
        proxy_protocol=True,
    )
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1",
        port="32000",
    )

    valid = datetime.now(tz=UTC) + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)
    crypto = CBCCryptoTransport(aes_key, aes_iv)

    writer_peer.write(fernet_token)
    await writer_peer.drain()
    token = await reader_peer.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    writer_peer.write(crypto.encrypt(token))
    await writer_peer.drain()
    await asyncio.sleep(0.1)

    async def mock_new_channel(
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Mock new channel."""
        while True:
            await channel.read()
            peer_address.append(channel.ip_address)

    _, writer_ssl = await asyncio.open_connection(host="127.0.0.1", port="32000")
    multiplexer = Multiplexer(
        crypto,
        reader_peer,
        writer_peer,
        snitun.PROTOCOL_VERSION,
        mock_new_channel,
    )

    # PROXY header, then the ClientHello split into fragments across writes.
    writer_ssl.write(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n")
    await writer_ssl.drain()
    await asyncio.sleep(0.1)
    writer_ssl.write(TLS_1_2[:40])
    await writer_ssl.drain()
    await asyncio.sleep(0.1)
    writer_ssl.write(TLS_1_2[40:])
    await writer_ssl.drain()
    await asyncio.sleep(0.1)

    assert peer_address
    assert peer_address[0] == ipaddress.IPv4Address("1.2.3.4")

    multiplexer.shutdown()
    await multiplexer.wait()
    writer_ssl.close()
    await server.stop()


def test_create_listen_sockets_ipv4() -> None:
    """A single IPv4 host yields one bound AF_INET socket."""
    sockets = create_listen_sockets(["127.0.0.1"], 32020)
    try:
        assert len(sockets) == 1
        assert sockets[0].family == socket.AF_INET
    finally:
        for sock in sockets:
            sock.close()


def test_create_listen_sockets_dedupes() -> None:
    """Repeated addresses are bound only once."""
    sockets = create_listen_sockets(["127.0.0.1", "127.0.0.1"], 32021)
    try:
        assert len(sockets) == 1
    finally:
        for sock in sockets:
            sock.close()


@skip_without_ipv6
def test_create_listen_sockets_dual_stack() -> None:
    """IPv4 and IPv6 hosts each yield a socket of the right family."""
    sockets = create_listen_sockets(["0.0.0.0", "::"], 32022)
    try:
        families = {sock.family for sock in sockets}
        assert families == {socket.AF_INET, socket.AF_INET6}
        # The IPv6 socket must be v6-only so it does not collide with 0.0.0.0.
        ipv6 = next(s for s in sockets if s.family == socket.AF_INET6)
        assert ipv6.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 1
    finally:
        for sock in sockets:
            sock.close()


@skip_without_ipv6
def test_snitun_worker_dual_stack(event_loop: asyncio.AbstractEventLoop) -> None:
    """The worker server accepts connections on both IPv4 and IPv6."""
    server = SniTunServerWorker(
        FERNET_TOKENS,
        host=["127.0.0.1", "::1"],
        port=32023,
        worker_size=2,
    )
    server.start()
    try:
        for family, address in (
            (socket.AF_INET, ("127.0.0.1", 32023)),
            (socket.AF_INET6, ("::1", 32023)),
        ):
            sock = socket.socket(family, socket.SOCK_STREAM)
            # connect() succeeding proves the address is bound and listening.
            sock.connect(address)
            sock.close()
        time.sleep(0.1)
    finally:
        server.stop()


@skip_without_ipv6
async def test_snitun_single_dual_stack() -> None:
    """SniTunServerSingle binds a list of hosts (IPv4 + IPv6).

    Also exercises passing ipaddress objects (not just strings) as hosts.
    """
    server = SniTunServerSingle(
        FERNET_TOKENS,
        host=[ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")],
        port=32024,
    )
    await server.start()
    try:
        for host in ("127.0.0.1", "::1"):
            reader, writer = await asyncio.open_connection(host=host, port=32024)
            writer.close()
            await writer.wait_closed()
            assert reader is not None
    finally:
        await server.stop()
