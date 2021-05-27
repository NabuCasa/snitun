"""Test runner of SniTun Server."""
import asyncio
from datetime import datetime, timedelta
import hashlib
import ipaddress
import os
import socket
import time

import pytest

from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.crypto import CryptoTransport
from snitun.server.run import SniTunServer, SniTunServerSingle, SniTunServerWorker

from .const_fernet import FERNET_TOKENS, create_peer_config
from .const_tls import TLS_1_2

IP_ADDR = ipaddress.ip_address("127.0.0.1")


async def test_snitun_runner_updown():
    """Test SniTun Server runner object."""
    server = SniTunServer(
        FERNET_TOKENS, peer_host="127.0.0.1", sni_host="127.0.0.1", sni_port=32000
    )

    await server.start()

    await asyncio.sleep(0.1)

    await server.stop()


async def test_snitun_single_runner_updown():
    """Test SniTun Single Server runner object."""
    server = SniTunServerSingle(FERNET_TOKENS, host="127.0.0.1", port=32000)

    await server.start()

    await asyncio.sleep(0.1)

    await server.stop()


def test_snitun_worker_runner_updown(loop):
    """Test SniTun Worker Server runner object."""
    server = SniTunServerWorker(
        FERNET_TOKENS, host="127.0.0.1", port=32001, worker_size=2
    )

    server.start()

    time.sleep(0.1)

    server.stop()


async def test_snitun_single_runner():
    """Test SniTunSingle Server runner object."""
    peer_messages = []
    peer_address = []

    server = SniTunServerSingle(FERNET_TOKENS, host="127.0.0.1", port=32000)
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1", port="32000"
    )

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    crypto = CryptoTransport(aes_key, aes_iv)

    writer_peer.write(fernet_token)
    await writer_peer.drain()

    token = await reader_peer.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    writer_peer.write(crypto.encrypt(token))

    await writer_peer.drain()
    await asyncio.sleep(0.1)

    assert server.peers.peer_available(hostname)

    async def mock_new_channel(multiplexer, channel):
        """Mock new channel."""
        while True:
            message = await channel.read()
            peer_messages.append(message)
            peer_address.append(channel.ip_address)

    _, writer_ssl = await asyncio.open_connection(host="127.0.0.1", port="32000")

    multiplexer = Multiplexer(crypto, reader_peer, writer_peer, mock_new_channel)

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


async def test_snitun_single_runner_timeout(raise_timeout):
    """Test SniTunSingle Server runner object."""
    server = SniTunServerSingle(FERNET_TOKENS, host="127.0.0.1", port="32000")
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1", port="32000"
    )

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    crypto = CryptoTransport(aes_key, aes_iv)

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


async def test_snitun_single_runner_throttling():
    """Test SniTunSingle Server runner object."""
    peer_messages = []
    peer_address = []

    server = SniTunServerSingle(
        FERNET_TOKENS, host="127.0.0.1", port="32000", throttling=500
    )
    await server.start()

    reader_peer, writer_peer = await asyncio.open_connection(
        host="127.0.0.1", port="32000"
    )

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    crypto = CryptoTransport(aes_key, aes_iv)

    writer_peer.write(fernet_token)
    await writer_peer.drain()

    token = await reader_peer.readexactly(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    writer_peer.write(crypto.encrypt(token))

    await writer_peer.drain()
    await asyncio.sleep(0.1)

    assert server.peers.peer_available(hostname)

    async def mock_new_channel(multiplexer, channel):
        """Mock new channel."""
        while True:
            message = await channel.read()
            peer_messages.append(message)
            peer_address.append(channel.ip_address)

    _, writer_ssl = await asyncio.open_connection(host="127.0.0.1", port="32000")

    multiplexer = Multiplexer(crypto, reader_peer, writer_peer, mock_new_channel)

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


def test_snitun_worker_runner(loop):
    """Test SniTunWorker Server runner object."""
    peer_messages = []
    peer_address = []

    server = SniTunServerWorker(
        FERNET_TOKENS, host="127.0.0.1", port=32001, worker_size=2
    )
    server.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 32001))

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    crypto = CryptoTransport(aes_key, aes_iv)

    sock.sendall(fernet_token)

    token = sock.recv(32)
    token = hashlib.sha256(crypto.decrypt(token)).digest()
    sock.sendall(crypto.encrypt(token))

    time.sleep(1)
    assert any(worker.is_responsible_peer(hostname) for worker in server._workers)
    assert server.peer_counter == 1

    async def mock_new_channel(multiplexer, channel):
        """Mock new channel."""
        while True:
            message = await channel.read()
            peer_messages.append(message)
            peer_address.append(channel.ip_address)

    sock_ssl = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock_ssl.connect(("127.0.0.1", 32001))

    async def _create_multiplexer() -> Multiplexer:
        """create and return the peer multiplexer."""
        reader_peer, writer_peer = await asyncio.open_connection(sock=sock)
        return Multiplexer(crypto, reader_peer, writer_peer, mock_new_channel)

    multiplexer = loop.run_until_complete(_create_multiplexer())

    sock_ssl.sendall(TLS_1_2)
    loop.run_until_complete(asyncio.sleep(0.5))

    assert peer_messages
    assert peer_messages[0] == TLS_1_2
    assert peer_address
    assert peer_address[0] == IP_ADDR

    loop.call_soon_threadsafe(multiplexer.shutdown)
    loop.run_until_complete(multiplexer.wait())
    time.sleep(1)

    assert not any(worker.is_responsible_peer(hostname) for worker in server._workers)

    sock_ssl.close()
    server.stop()


def test_snitun_worker_timeout(loop):
    """Test SniTunWorker Server runner object timeout."""
    from snitun.server import run

    run.WORKER_STALE_MAX = 1
    server = SniTunServerWorker(
        FERNET_TOKENS, host="127.0.0.1", port=32001, worker_size=2
    )

    server.start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", 32001))

    time.sleep(2)

    with pytest.raises(OSError):
        valid = datetime.utcnow() + timedelta(days=1)
        aes_key = os.urandom(32)
        aes_iv = os.urandom(16)
        hostname = "localhost"
        fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

        crypto = CryptoTransport(aes_key, aes_iv)

        sock.sendall(fernet_token)

        token = sock.recv(32)
        token = hashlib.sha256(crypto.decrypt(token)).digest()
        sock.sendall(crypto.encrypt(token))

    server.stop()
