"""Test Client Peer connections."""
import asyncio
from datetime import datetime, timedelta
import os

import pytest

from snitun.client.client_peer import ClientPeer
from snitun.client.connector import Connector
from snitun.exceptions import SniTunConnectionError

from ..server.const_fernet import create_peer_config


async def test_init_client_peer(peer_listener, peer_manager, test_endpoint):
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not client.is_connected
    assert not peer_manager.peer_available("localhost")

    valid = datetime.utcnow() + timedelta(days=1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    whitelist = []
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")
    assert client.is_connected

    await client.stop()
    await asyncio.sleep(0.1)
    assert not peer_manager.peer_available("localhost")


async def test_init_client_peer_invalid_token(peer_listener, peer_manager,
                                              test_endpoint):
    """Test setup of ClientPeer."""
    client = ClientPeer("127.0.0.1", "8893")
    connector = Connector("127.0.0.1", "8822")

    assert not peer_manager.peer_available("localhost")

    valid = datetime.utcnow() + timedelta(days=-1)
    aes_key = os.urandom(32)
    aes_iv = os.urandom(16)
    whitelist = []
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

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
    whitelist = []
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    peer = peer_manager.get_peer("localhost")

    channel = await peer.multiplexer.create_channel()
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.writer.write(b"Hiro")
    await test_connection.writer.drain()

    data = await channel.read()
    assert data == b"Hiro"

    await client.stop()
    await asyncio.sleep(0.1)
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
    whitelist = []
    hostname = "localhost"
    fernet_token = create_peer_config(valid.timestamp(), hostname, whitelist,
                                      aes_key, aes_iv)

    await client.start(connector, fernet_token, aes_key, aes_iv)
    await asyncio.sleep(0.1)
    assert peer_manager.peer_available("localhost")

    peer = peer_manager.get_peer("localhost")

    channel = await peer.multiplexer.create_channel()
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.writer.write(b"Hiro")
    await test_connection.writer.drain()

    data = await channel.read()
    assert data == b"Hiro"

    await client.stop()
    await asyncio.sleep(0.1)
    assert not peer_manager.peer_available("localhost")

    data = await test_connection.reader.read(1024)
    assert not data

    test_connection.close.set()
