"""Test Client Peer connections."""
import asyncio
from datetime import datetime, timedelta
import ipaddress
import os

import pytest

from snitun.client.client_peer import ClientPeer
from snitun.client.connector import Connector
from snitun.exceptions import SniTunConnectionError

from ..server.const_fernet import create_peer_config

IP_ADDR = ipaddress.ip_address("8.8.8.8")


async def test_init_client_peer(peer_listener, peer_manager, test_endpoint):
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected
    assert client._multiplexer._throttling is None

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")


async def test_init_client_peer_invalid_token(
    peer_listener, peer_manager, test_endpoint
):
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = datetime.utcnow() + timedelta(days=-1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    with pytest.raises(SniTunConnectionError):
        await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert not peer_manager.peer_available("localhost")


async def test_flow_client_peer(peer_listener, peer_manager, test_endpoint):
    """Test setup of ClientPeer, test flow."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    peer = peer_manager.get_peer("localhost")

    channel = await peer.multiplexer.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"
    assert channel.ip_address == IP_ADDR

    test_connection.writer.write(b"Hiro")
    await test_connection.writer.drain()

    data = await channel.read()
    assert data == b"Hiro"

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    test_connection.close.set()


async def test_close_client_peer(peer_listener, peer_manager, test_endpoint):
    """Test setup of ClientPeer, test flow - close it."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    peer = peer_manager.get_peer("localhost")

    channel = await peer.multiplexer.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"
    assert channel.ip_address == IP_ADDR

    test_connection.writer.write(b"Hiro")
    await test_connection.writer.drain()

    data = await channel.read()
    assert data == b"Hiro"

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    data = await test_connection.reader.read(1024)
    assert not data

    test_connection.close.set()


async def test_init_client_peer_wait(peer_listener, peer_manager, test_endpoint):
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected

    assert not client.wait().done()

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    with pytest.raises(RuntimeError):
        assert client.wait().done()


async def test_init_client_peer_throttling(peer_listener, peer_manager, test_endpoint):
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv, throttling=500)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected
    assert client._multiplexer._throttling == 0.002

    await client.stop()
    await asyncio.sleep(0.1)
    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")
